"""Telegram bot for panel management"""
import asyncio
import logging
import os
import shutil
import zipfile
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import Node, Tunnel, Settings
import httpx

logger = logging.getLogger(__name__)

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton  # type: ignore
    from telegram.ext import (  # type: ignore
        Application, CommandHandler, CallbackQueryHandler, ContextTypes,
        ConversationHandler, MessageHandler, filters
    )
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    Update = None  # type: ignore
    InlineKeyboardButton = None  # type: ignore
    InlineKeyboardMarkup = None  # type: ignore
    ReplyKeyboardMarkup = None  # type: ignore
    KeyboardButton = None  # type: ignore
    Application = None  # type: ignore
    CommandHandler = None  # type: ignore
    CallbackQueryHandler = None  # type: ignore
    ContextTypes = None  # type: ignore
    ConversationHandler = None  # type: ignore
    MessageHandler = None  # type: ignore
    filters = None  # type: ignore
    logger.warning("python-telegram-bot not installed. Telegram bot will not work.")


# No conversation states needed


class TelegramBot:
    """Telegram bot for managing panel"""
    
    def __init__(self):
        self.application: Optional[Application] = None
        self.enabled = False
        self.bot_token: Optional[str] = None
        self.admin_ids: List[str] = []
        self.backup_task: Optional[asyncio.Task] = None
        self.backup_enabled = False
        self.backup_interval = 60
        self.backup_interval_unit = "minutes"
        self.user_states: Dict[int, Dict[str, Any]] = {}
        api_url = os.getenv("PANEL_API_URL")
        if not api_url:
            api_url = os.getenv("BACKEND_URL", "http://localhost:8000")
        self.api_base_url = api_url
    
    async def load_settings(self):
        """Load settings from database"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Settings).where(Settings.key == "telegram"))
            setting = result.scalar_one_or_none()
            if setting and setting.value:
                self.enabled = setting.value.get("enabled", False)
                self.bot_token = setting.value.get("bot_token")
                self.admin_ids = setting.value.get("admin_ids", [])
                self.backup_enabled = setting.value.get("backup_enabled", False)
                self.backup_interval = setting.value.get("backup_interval", 60)
                self.backup_interval_unit = setting.value.get("backup_interval_unit", "minutes")
            else:
                self.enabled = False
                self.bot_token = None
                self.admin_ids = []
                self.backup_enabled = False
                self.backup_interval = 60
                self.backup_interval_unit = "minutes"
    
    def t(self, user_id: int, key: str, **kwargs) -> str:
        """Get text (simplified - no translations)"""
        translations = {
            "welcome": "👋 Welcome to the Control Panel Bot!\n\nSelect an action:",
            "access_denied": "❌ Access denied. You are not an admin.",
            "node_stats": "📊 Node Stats",
            "tunnel_stats": "📊 Tunnel Stats",
            "logs": "📋 Logs",
            "backup": "📦 Backup",
            "no_nodes": "📭 No nodes found.",
            "no_tunnels": "📭 No tunnels found.",
            "error": "❌ Error: {error}",
        }
        text = translations.get(key, key)
        return text.format(**kwargs) if kwargs else text
    
    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        return str(user_id) in self.admin_ids
    
    async def start(self):
        """Start Telegram bot"""
        if not TELEGRAM_AVAILABLE:
            logger.error("python-telegram-bot not available. Cannot start bot.")
            return False
        
        await self.load_settings()
        
        if not self.enabled or not self.bot_token:
            logger.info("Telegram bot not enabled or token not set")
            return False
        
        # Stop existing instance if running
        await self.stop()
        
        try:
            self.application = Application.builder().token(self.bot_token).build()
            
            self.application.add_handler(CommandHandler("start", self.cmd_start))
            self.application.add_handler(CommandHandler("help", self.cmd_help))
            self.application.add_handler(CommandHandler("nodes", self.cmd_nodes))
            self.application.add_handler(CommandHandler("tunnels", self.cmd_tunnels))
            self.application.add_handler(CommandHandler("status", self.cmd_status))
            self.application.add_handler(CommandHandler("backup", self.cmd_backup))
            self.application.add_handler(CommandHandler("logs", self.cmd_logs))
            self.application.add_handler(CallbackQueryHandler(self.handle_callback, pattern="^(back_to_menu|node_stats|tunnel_stats|logs|cmd_nodes|cmd_tunnels|cmd_backup|cmd_status)$"))
            
            # Handle persistent keyboard buttons - must be after conversation handlers
            self.application.add_handler(MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                self.handle_text_message
            ))
            
            await self.start_backup_task()
            
            # Initialize and start the application (PTB v20+ async lifecycle)
            await self.application.initialize()
            await self.application.start()
            
            # Start polling using updater (PTB v20+ way for existing event loop)
            if hasattr(self.application, 'updater') and self.application.updater:
                await self.application.updater.start_polling(drop_pending_updates=True)
                logger.info("Telegram bot polling started successfully")
            else:
                logger.error("Application updater not available. Polling cannot be started.")
                await self.stop()
                return False
            
            logger.info("Telegram bot started successfully (polling mode)")
            
            return True
        except Exception as e:
            logger.error(f"Failed to start Telegram bot: {e}", exc_info=True)
            await self.stop()
            return False
    
    async def stop(self):
        """Stop Telegram bot (idempotent - safe to call multiple times)"""
        await self.stop_backup_task()
        
        if not self.application:
            return  # Already stopped
        
        try:
            # Stop updater first (if it exists and is running)
            if hasattr(self.application, 'updater') and self.application.updater:
                try:
                    # Check if updater is running before stopping
                    if hasattr(self.application.updater, 'running') and self.application.updater.running:
                        await self.application.updater.stop()
                        logger.info("Telegram bot updater stopped")
                except Exception as e:
                    logger.warning(f"Error stopping updater: {e}")
            
            # Stop and shutdown application
            await self.application.stop()
            await self.application.shutdown()
        except Exception as e:
            logger.warning(f"Error stopping Telegram bot: {e}")
        finally:
            self.application = None
            logger.info("Telegram bot stopped")
    
    async def start_backup_task(self):
        """Start automatic backup task"""
        await self.stop_backup_task()
        await self.load_settings()
        
        if self.backup_enabled and self.admin_ids:
            self.backup_task = asyncio.create_task(self._backup_loop())
            logger.info(f"Automatic backup task started: interval={self.backup_interval} {self.backup_interval_unit}")
    
    async def stop_backup_task(self):
        """Stop automatic backup task"""
        if self.backup_task:
            self.backup_task.cancel()
            try:
                await self.backup_task
            except asyncio.CancelledError:
                pass
            self.backup_task = None
            logger.info("Automatic backup task stopped")
    
    async def _backup_loop(self):
        """Background task for automatic backups"""
        try:
            while True:
                await self.load_settings()
                
                if not self.backup_enabled or not self.admin_ids:
                    await asyncio.sleep(60)
                    continue
                
                if self.backup_interval_unit == "hours":
                    sleep_seconds = self.backup_interval * 3600
                else:
                    sleep_seconds = self.backup_interval * 60
                
                await asyncio.sleep(sleep_seconds)
                
                if not self.backup_enabled:
                    continue
                
                try:
                    backup_path = await self.create_backup()
                    if backup_path and self.application and self.application.bot:
                        for admin_id_str in self.admin_ids:
                            try:
                                admin_id = int(admin_id_str)
                                with open(backup_path, 'rb') as f:
                                    await self.application.bot.send_document(
                                        chat_id=admin_id,
                                        document=f,
                                        filename=f"smite_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                                        caption=f"🔄 Automatic backup - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                                    )
                            except Exception as e:
                                logger.error(f"Failed to send backup to admin {admin_id_str}: {e}")
                        
                        if os.path.exists(backup_path):
                            os.remove(backup_path)
                        logger.info("Automatic backup sent successfully")
                except Exception as e:
                    logger.error(f"Error in automatic backup: {e}", exc_info=True)
        except asyncio.CancelledError:
            logger.info("Backup loop cancelled")
            raise
        except Exception as e:
            logger.error(f"Backup loop error: {e}", exc_info=True)
    
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        try:
            user_id = update.effective_user.id
            reply_markup = self._get_keyboard(user_id)
            
            if not self.is_admin(user_id):
                await update.message.reply_text(self.t(user_id, "access_denied"), reply_markup=reply_markup)
                return
            
            await update.message.reply_text(self.t(user_id, "welcome"), reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error in cmd_start: {e}", exc_info=True)
            try:
                user_id = update.effective_user.id
                reply_markup = self._get_keyboard(user_id)
                await update.message.reply_text("❌ Error: Please try again.", reply_markup=reply_markup)
            except:
                pass
    
    def _get_keyboard(self, user_id: int) -> ReplyKeyboardMarkup:
        """Get persistent keyboard markup"""
        keyboard = [
            [
                KeyboardButton(self.t(user_id, 'node_stats')),
                KeyboardButton(self.t(user_id, 'tunnel_stats'))
            ],
            [
                KeyboardButton(self.t(user_id, 'logs')),
                KeyboardButton(self.t(user_id, 'backup'))
            ],
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    
    async def show_main_menu(self, message_or_query):
        """Show main menu with persistent keyboard buttons"""
        try:
            # Get user_id and message object
            if hasattr(message_or_query, 'from_user'):
                user_id = message_or_query.from_user.id
                message = message_or_query
            elif hasattr(message_or_query, 'message'):
                user_id = message_or_query.message.from_user.id
                message = message_or_query.message
            else:
                user_id = message_or_query.chat.id if hasattr(message_or_query, 'chat') else 0
                message = message_or_query
            
            reply_markup = self._get_keyboard(user_id)
            text = self.t(user_id, "welcome")
            
            if hasattr(message, 'reply_text'):
                await message.reply_text(text, reply_markup=reply_markup)
            elif hasattr(message_or_query, 'edit_message_text'):
                await message_or_query.edit_message_text(text, reply_markup=reply_markup)
            elif hasattr(message_or_query, 'message'):
                await message_or_query.message.reply_text(text, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error showing main menu: {e}", exc_info=True)
            try:
                user_id = message_or_query.from_user.id if hasattr(message_or_query, 'from_user') else 0
                reply_markup = self._get_keyboard(user_id)
                if hasattr(message_or_query, 'reply_text'):
                    await message_or_query.reply_text(self.t(user_id, "welcome"), reply_markup=reply_markup)
            except:
                pass
    
    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        user_id = update.effective_user.id
        reply_markup = self._get_keyboard(user_id)
        
        if not self.is_admin(user_id):
            await update.message.reply_text(self.t(user_id, "access_denied"), reply_markup=reply_markup)
            return
        
        help_text = """📋 Available Commands:

/start - Show main menu
/nodes - List all nodes
/tunnels - List all tunnels
/status - Show panel status
/logs - Show recent logs
/backup - Create and send backup

Use buttons in messages to interact with nodes and tunnels."""
        
        await update.message.reply_text(help_text, reply_markup=reply_markup)
    
    async def cmd_nodes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /nodes command"""
        user_id = update.effective_user.id
        reply_markup = self._get_keyboard(user_id)
        
        if not self.is_admin(user_id):
            await update.message.reply_text(self.t(user_id, "access_denied"), reply_markup=reply_markup)
            return
        
        await self.cmd_nodes_callback(update.message)
    
    async def cmd_tunnels(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /tunnels command"""
        user_id = update.effective_user.id
        reply_markup = self._get_keyboard(user_id)
        
        if not self.is_admin(user_id):
            await update.message.reply_text(self.t(user_id, "access_denied"), reply_markup=reply_markup)
            return
        
        await self.cmd_tunnels_callback(update.message)
    
    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        user_id = update.effective_user.id
        reply_markup = self._get_keyboard(user_id)
        
        if not self.is_admin(user_id):
            await update.message.reply_text(self.t(user_id, "access_denied"), reply_markup=reply_markup)
            return
        
        await self.cmd_status_callback(update.message)
    
    async def cmd_backup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /backup command"""
        user_id = update.effective_user.id
        reply_markup = self._get_keyboard(user_id)
        
        if not self.is_admin(user_id):
            await update.message.reply_text(self.t(user_id, "access_denied"), reply_markup=reply_markup)
            return
        
        await update.message.reply_text("📦 Creating backup...", reply_markup=reply_markup)
        
        try:
            backup_path = await self.create_backup()
            if backup_path:
                with open(backup_path, 'rb') as f:
                    await update.message.reply_document(
                        document=f,
                        filename=f"smite_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                        caption="✅ Backup created successfully",
                        reply_markup=reply_markup
                    )
                os.remove(backup_path)
            else:
                await update.message.reply_text("❌ Failed to create backup", reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error creating backup: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error creating backup: {str(e)}", reply_markup=reply_markup)
    
    async def cmd_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /logs command"""
        user_id = update.effective_user.id
        reply_markup = self._get_keyboard(user_id)
        
        if not self.is_admin(user_id):
            await update.message.reply_text(self.t(user_id, "access_denied"), reply_markup=reply_markup)
            return
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.api_base_url}/api/logs?limit=20")
                if response.status_code == 200:
                    logs = response.json().get("logs", [])
                    if logs:
                        text = "📋 Recent Logs:\n\n"
                        for log in logs[-10:]:
                            text += f"`{log.get('level', 'INFO')}` {log.get('message', '')[:100]}\n\n"
                        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)
                    else:
                        await update.message.reply_text("No logs available.", reply_markup=reply_markup)
                else:
                    await update.message.reply_text("Failed to fetch logs.", reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error fetching logs: {e}", exc_info=True)
            await update.message.reply_text(f"Error: {str(e)}", reply_markup=reply_markup)
    
    async def create_backup(self) -> Optional[str]:
        """Create backup archive"""
        try:
            from app.config import settings
            import os
            
            backup_dir = Path("/tmp/smite_backup")
            backup_dir.mkdir(exist_ok=True)
            
            # Find panel root directory
            data_dir = Path("/opt/smite/panel/data")
            if not data_dir.exists():
                panel_root = Path(os.getcwd())
                if not (panel_root / "data").exists():
                    for possible_root in [Path("/opt/smite"), Path(__file__).parent.parent.parent]:
                        if (possible_root / "data").exists():
                            panel_root = possible_root
                            break
                data_dir = panel_root / "data"
            
            if data_dir.exists():
                shutil.copytree(data_dir, backup_dir / "data", dirs_exist_ok=True)
                logger.info(f"Backed up data folder from: {data_dir}")
            
            panel_root = data_dir.parent if data_dir.exists() else Path("/opt/smite/panel")
            if not (panel_root / "certs").exists():
                panel_root = Path(os.getcwd())
                if not (panel_root / "certs").exists():
                    for possible_root in [Path("/opt/smite"), Path(__file__).parent.parent.parent]:
                        if (possible_root / "certs").exists():
                            panel_root = possible_root
                            break
            
            certs_dir = panel_root / "certs"
            if certs_dir.exists():
                shutil.copytree(certs_dir, backup_dir / "certs", dirs_exist_ok=True)
            
            node_cert_path = Path(settings.node_cert_path)
            if not node_cert_path.is_absolute():
                node_cert_path = panel_root / node_cert_path
            if node_cert_path.exists():
                (backup_dir / "node_certs").mkdir(exist_ok=True)
                shutil.copy2(node_cert_path, backup_dir / "node_certs" / "ca.crt")
            
            node_key_path = Path(settings.node_key_path)
            if not node_key_path.is_absolute():
                node_key_path = panel_root / node_key_path
            if node_key_path.exists():
                (backup_dir / "node_certs").mkdir(exist_ok=True)
                shutil.copy2(node_key_path, backup_dir / "node_certs" / "ca.key")
            
            server_cert_path = Path(settings.node_server_cert_path)
            if not server_cert_path.is_absolute():
                server_cert_path = panel_root / server_cert_path
            if server_cert_path.exists():
                (backup_dir / "server_certs").mkdir(exist_ok=True)
                shutil.copy2(server_cert_path, backup_dir / "server_certs" / "ca-server.crt")
            
            server_key_path = Path(settings.node_server_key_path)
            if not server_key_path.is_absolute():
                server_key_path = panel_root / server_key_path
            if server_key_path.exists():
                (backup_dir / "server_certs").mkdir(exist_ok=True)
                shutil.copy2(server_key_path, backup_dir / "server_certs" / "ca-server.key")
            
            # Backup .env and docker-compose.yml from mounted config directory
            # These files are mounted into the container at /app/config/
            config_dir = Path("/app/config")
            
            # Also try common locations as fallback
            env_locations = [
                config_dir / ".env",
                Path("/opt/smite/.env"),
                Path(os.getcwd()) / ".env"
            ]
            
            compose_locations = [
                config_dir / "docker-compose.yml",
                Path("/opt/smite/docker-compose.yml"),
                Path(os.getcwd()) / "docker-compose.yml"
            ]
            
            # Find and backup .env
            env_file = None
            for env_path in env_locations:
                if env_path.exists():
                    env_file = env_path
                    break
            
            if env_file:
                # Use 'env' instead of '.env' to make it visible (not hidden)
                shutil.copy2(env_file, backup_dir / "env")
                logger.info(f"Backed up .env from: {env_file}")
            
            # Find and backup docker-compose.yml
            compose_file = None
            for compose_path in compose_locations:
                if compose_path.exists():
                    compose_file = compose_path
                    break
            
            if compose_file:
                shutil.copy2(compose_file, backup_dir / "docker-compose.yml")
                logger.info(f"Backed up docker-compose.yml from: {compose_file}")
            
            from app.config import settings
            if settings.https_enabled and settings.panel_domain:
                nginx_dir = panel_root / "nginx"
                if nginx_dir.exists():
                    shutil.copytree(nginx_dir, backup_dir / "nginx", dirs_exist_ok=True)
                
                letsencrypt_dir = Path("/etc/letsencrypt")
                if letsencrypt_dir.exists():
                    domain_dir = letsencrypt_dir / "live" / settings.panel_domain
                    if domain_dir.exists():
                        (backup_dir / "letsencrypt" / "live" / settings.panel_domain).mkdir(parents=True, exist_ok=True)
                        for cert_file in ["fullchain.pem", "privkey.pem", "chain.pem", "cert.pem"]:
                            cert_path = domain_dir / cert_file
                            if cert_path.exists():
                                shutil.copy2(cert_path, backup_dir / "letsencrypt" / "live" / settings.panel_domain / cert_file)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_file = f"/tmp/smite_backup_{timestamp}.zip"
            
            with zipfile.ZipFile(backup_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(backup_dir):
                    for file in files:
                        file_path = Path(root) / file
                        arcname = file_path.relative_to(backup_dir)
                        zipf.write(file_path, arcname)
            
            shutil.rmtree(backup_dir)
            
            return backup_file
        except Exception as e:
            logger.error(f"Error creating backup: {e}", exc_info=True)
            return None
    
    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages from persistent keyboard"""
        try:
            if not self.is_admin(update.effective_user.id):
                return
            
            # Skip if user is in a conversation (let conversation handlers handle it)
            user_id = update.effective_user.id
            if user_id in self.user_states:
                return
            
            text = update.message.text
            if not text:
                return
            
            # Check if it's a keyboard button
            if self.t(user_id, "node_stats") in text:
                await self.cmd_nodes_callback(update.message)
            elif self.t(user_id, "tunnel_stats") in text:
                await self.cmd_tunnels_callback(update.message)
            elif self.t(user_id, "logs") in text:
                await self.cmd_logs(update, context)
            elif self.t(user_id, "backup") in text:
                await self.cmd_backup(update, context)
        except Exception as e:
            logger.error(f"Error handling text message: {e}", exc_info=True)
            try:
                user_id = update.effective_user.id
                reply_markup = self._get_keyboard(user_id)
                await update.message.reply_text("❌ Error processing request", reply_markup=reply_markup)
            except:
                pass
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle callback queries"""
        try:
            query = update.callback_query
            await query.answer()
            
            if not query.message:
                return
            
            if not self.is_admin(query.from_user.id):
                await query.edit_message_text(self.t(query.from_user.id, "access_denied"))
                return
        except Exception as e:
            logger.error(f"Error in handle_callback: {e}", exc_info=True)
            return
        
        data = query.data
        
        if data == "back_to_menu":
            if query.message:
                text = self.t(query.from_user.id, "welcome")
                await query.edit_message_text(text)
        elif data == "node_stats":
            await self.cmd_nodes_callback(query)
        elif data == "tunnel_stats":
            await self.cmd_tunnels_callback(query)
        elif data == "logs":
            await self.cmd_logs_callback(query)
        elif data == "cmd_nodes":
            await self.cmd_nodes_callback(query)
        elif data == "cmd_tunnels":
            await self.cmd_tunnels_callback(query)
        elif data == "cmd_backup":
            await self.cmd_backup_callback(query)
        elif data == "cmd_status":
            await self.cmd_status_callback(query)
    
    async def cmd_nodes_callback(self, message_or_query):
        """Handle nodes command from callback"""
        try:
            # Get user_id and message object
            if hasattr(message_or_query, 'from_user'):
                user_id = message_or_query.from_user.id
                message = message_or_query
            elif hasattr(message_or_query, 'message') and hasattr(message_or_query.message, 'from_user'):
                user_id = message_or_query.message.from_user.id
                message = message_or_query.message
            else:
                user_id = message_or_query.chat.id if hasattr(message_or_query, 'chat') else 0
                message = message_or_query
            
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(Node))
                nodes = result.scalars().all()
                
                reply_markup = self._get_keyboard(user_id)
                
                if not nodes:
                    text = self.t(user_id, "no_nodes")
                    if hasattr(message, 'edit_message_text') and message:
                        await message.edit_message_text(text)
                    elif hasattr(message, 'reply_text'):
                        await message.reply_text(text, reply_markup=reply_markup)
                    return
                
                text = f"📊 {self.t(user_id, 'node_stats')}:\n\n"
                active = sum(1 for n in nodes if n.status == "active")
                text += f"Total: {len(nodes)}\n"
                text += f"Active: {active}\n\n"
                
                for node in nodes:
                    status = "🟢" if node.status == "active" else "🔴"
                    role = node.node_metadata.get("role", "unknown") if node.node_metadata else "unknown"
                    text += f"{status} {node.name} ({role})\n"
                    text += f"   ID: {node.id[:8]}...\n\n"
                
                if hasattr(message, 'edit_message_text') and message:
                    await message.edit_message_text(text)
                elif hasattr(message, 'reply_text'):
                    await message.reply_text(text, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error in cmd_nodes_callback: {e}", exc_info=True)
            try:
                user_id = message_or_query.from_user.id if hasattr(message_or_query, 'from_user') else 0
                reply_markup = self._get_keyboard(user_id)
                if hasattr(message_or_query, 'reply_text'):
                    await message_or_query.reply_text("❌ Error loading nodes", reply_markup=reply_markup)
                elif hasattr(message_or_query, 'edit_message_text') and message_or_query:
                    await message_or_query.edit_message_text("❌ Error loading nodes")
                elif hasattr(message_or_query, 'message'):
                    await message_or_query.message.reply_text("❌ Error loading nodes", reply_markup=reply_markup)
            except:
                pass
    
    async def cmd_tunnels_callback(self, message_or_query):
        """Handle tunnels command from callback"""
        try:
            if hasattr(message_or_query, 'from_user'):
                user_id = message_or_query.from_user.id
            elif hasattr(message_or_query, 'message') and hasattr(message_or_query.message, 'from_user'):
                user_id = message_or_query.message.from_user.id
            else:
                user_id = message_or_query.chat.id if hasattr(message_or_query, 'chat') else 0
            
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(Tunnel))
                tunnels = result.scalars().all()
                
                reply_markup = self._get_keyboard(user_id)
                
                if not tunnels:
                    text = self.t(user_id, "no_tunnels")
                    if hasattr(message_or_query, 'edit_message_text') and message_or_query:
                        await message_or_query.edit_message_text(text)
                    elif hasattr(message_or_query, 'reply_text'):
                        await message_or_query.reply_text(text, reply_markup=reply_markup)
                    else:
                        await message_or_query.message.reply_text(text, reply_markup=reply_markup)
                    return
                
                text = f"📊 {self.t(user_id, 'tunnel_stats')}:\n\n"
                active = sum(1 for t in tunnels if t.status == "active")
                text += f"Total: {len(tunnels)}\n"
                text += f"Active: {active}\n"
                text += f"Error: {len(tunnels) - active}\n\n"
                
                for tunnel in tunnels[:10]:
                    status = "🟢" if tunnel.status == "active" else "🔴"
                    text += f"{status} {tunnel.name} ({tunnel.core})\n"
                
                if len(tunnels) > 10:
                    text += f"\n... and {len(tunnels) - 10} more"
                
                if hasattr(message_or_query, 'edit_message_text') and message_or_query:
                    await message_or_query.edit_message_text(text)
                elif hasattr(message_or_query, 'reply_text'):
                    reply_markup = self._get_keyboard(user_id)
                    await message_or_query.reply_text(text, reply_markup=reply_markup)
                else:
                    reply_markup = self._get_keyboard(user_id)
                    await message_or_query.message.reply_text(text, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error in cmd_tunnels_callback: {e}", exc_info=True)
            try:
                user_id = message_or_query.from_user.id if hasattr(message_or_query, 'from_user') else 0
                reply_markup = self._get_keyboard(user_id)
                if hasattr(message_or_query, 'reply_text'):
                    await message_or_query.reply_text("❌ Error loading tunnels", reply_markup=reply_markup)
                elif hasattr(message_or_query, 'edit_message_text') and message_or_query:
                    await message_or_query.edit_message_text("❌ Error loading tunnels")
                elif hasattr(message_or_query, 'message'):
                    await message_or_query.message.reply_text("❌ Error loading tunnels", reply_markup=reply_markup)
            except:
                pass
    
    async def cmd_status_callback(self, message_or_query):
        """Handle status command from callback"""
        try:
            if hasattr(message_or_query, 'from_user'):
                user_id = message_or_query.from_user.id
            elif hasattr(message_or_query, 'message') and hasattr(message_or_query.message, 'from_user'):
                user_id = message_or_query.message.from_user.id
            else:
                user_id = message_or_query.chat.id if hasattr(message_or_query, 'chat') else 0
            
            async with AsyncSessionLocal() as session:
                nodes_result = await session.execute(select(Node))
                nodes = nodes_result.scalars().all()
                
                tunnels_result = await session.execute(select(Tunnel))
                tunnels = tunnels_result.scalars().all()
                
                active_nodes = sum(1 for n in nodes if n.status == "active")
                active_tunnels = sum(1 for t in tunnels if t.status == "active")
                
                text = f"""📊 Panel Status:

🖥️ Nodes: {active_nodes}/{len(nodes)} active
🔗 Tunnels: {active_tunnels}/{len(tunnels)} active
"""
                
                if hasattr(message_or_query, 'edit_message_text') and message_or_query:
                    await message_or_query.edit_message_text(text)
                elif hasattr(message_or_query, 'reply_text'):
                    reply_markup = self._get_keyboard(user_id)
                    await message_or_query.reply_text(text, reply_markup=reply_markup)
                else:
                    reply_markup = self._get_keyboard(user_id)
                    await message_or_query.message.reply_text(text, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error in cmd_status_callback: {e}", exc_info=True)
            try:
                user_id = message_or_query.from_user.id if hasattr(message_or_query, 'from_user') else 0
                if hasattr(message_or_query, 'reply_text'):
                    reply_markup = self._get_keyboard(user_id)
                    await message_or_query.reply_text("❌ Error loading status", reply_markup=reply_markup)
                elif hasattr(message_or_query, 'edit_message_text') and message_or_query:
                    await message_or_query.edit_message_text("❌ Error loading status")
                elif hasattr(message_or_query, 'message'):
                    await message_or_query.message.reply_text("❌ Error loading status", reply_markup=reply_markup)
            except:
                pass
    
    async def cmd_backup_callback(self, query):
        """Handle backup command from callback"""
        user_id = query.from_user.id
        if not query.message:
            return
        
        await query.edit_message_text("📦 Creating backup...")
        
        try:
            backup_path = await self.create_backup()
            if backup_path:
                reply_markup = self._get_keyboard(user_id)
                with open(backup_path, 'rb') as f:
                    await query.message.reply_document(
                        document=f,
                        filename=f"smite_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                        caption="✅ Backup created successfully",
                        reply_markup=reply_markup
                    )
                os.remove(backup_path)
                await query.edit_message_text("✅ Backup created and sent successfully!")
            else:
                await query.edit_message_text("❌ Failed to create backup")
        except Exception as e:
            logger.error(f"Error creating backup: {e}", exc_info=True)
            await query.edit_message_text(f"❌ Error creating backup: {str(e)}")
    
    async def cmd_logs_callback(self, query):
        """Handle logs command from callback"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.api_base_url}/api/logs?limit=20")
                if response.status_code == 200:
                    logs = response.json().get("logs", [])
                    if logs:
                        text = "📋 Recent Logs:\n\n"
                        for log in logs[-10:]:
                            text += f"`{log.get('level', 'INFO')}` {log.get('message', '')[:100]}\n\n"
                        await query.edit_message_text(text, parse_mode="Markdown")
                    else:
                        await query.edit_message_text("No logs available.")
                else:
                    await query.edit_message_text("Failed to fetch logs.")
        except Exception as e:
            logger.error(f"Error fetching logs: {e}", exc_info=True)
            await query.edit_message_text(f"Error: {str(e)}")


telegram_bot = TelegramBot()
