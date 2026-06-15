"""Settings API endpoints"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime
from app.database import get_db, AsyncSessionLocal
from app.models import Settings
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Returned by GET in place of stored secrets so they are never exposed; on PUT,
# this placeholder (or an empty value) means "keep the existing secret".
SECRET_MASK = "********"


class FrpSettings(BaseModel):
    enabled: bool = False
    port: int = 7000
    token: Optional[str] = None


class TelegramSettings(BaseModel):
    enabled: bool = False
    bot_token: Optional[str] = None
    admin_ids: List[str] = []
    backup_enabled: bool = False
    backup_interval: int = 60
    backup_interval_unit: str = "minutes"


class TunnelSettings(BaseModel):
    auto_reapply_enabled: bool = False
    auto_reapply_interval: int = 60
    auto_reapply_interval_unit: str = "minutes"


class SettingsUpdate(BaseModel):
    frp: Optional[FrpSettings] = None
    telegram: Optional[TelegramSettings] = None
    tunnel: Optional[TunnelSettings] = None


@router.get("")
async def get_settings(db: AsyncSession = Depends(get_db)):
    """Get all settings"""
    result = await db.execute(select(Settings))
    settings_list = result.scalars().all()
    
    settings_dict = {s.key: s.value for s in settings_list}
    
    frp_settings = settings_dict.get("frp", {})
    telegram_settings = settings_dict.get("telegram", {})
    tunnel_settings = settings_dict.get("tunnel", {})  # Backward compatible: defaults to {} if not exists
    
    return {
        "frp": {
            "enabled": frp_settings.get("enabled", False),
            "port": frp_settings.get("port", 7000),
            "token": SECRET_MASK if frp_settings.get("token") else None
        },
        "telegram": {
            "enabled": telegram_settings.get("enabled", False),
            "bot_token": SECRET_MASK if telegram_settings.get("bot_token") else None,
            "admin_ids": telegram_settings.get("admin_ids", []),
            "backup_enabled": telegram_settings.get("backup_enabled", False),
            "backup_interval": telegram_settings.get("backup_interval", 60),
            "backup_interval_unit": telegram_settings.get("backup_interval_unit", "minutes")
        },
        "tunnel": {
            "auto_reapply_enabled": tunnel_settings.get("auto_reapply_enabled", False) if tunnel_settings else False,
            "auto_reapply_interval": tunnel_settings.get("auto_reapply_interval", 60) if tunnel_settings else 60,
            "auto_reapply_interval_unit": tunnel_settings.get("auto_reapply_interval_unit", "minutes") if tunnel_settings else "minutes"
        }
    }


@router.put("")
async def update_settings(settings_update: SettingsUpdate, request: Request, db: AsyncSession = Depends(get_db)):
    """Update settings"""
    from app.frp_comm_manager import frp_comm_manager
    
    if settings_update.frp:
        result = await db.execute(select(Settings).where(Settings.key == "frp"))
        setting = result.scalar_one_or_none()
        
        old_value = dict(setting.value) if (setting and setting.value) else {}
        old_enabled = old_value.get("enabled", False)
        
        new_enabled = settings_update.frp.enabled
        
        frp_value = settings_update.frp.dict(exclude_none=True)
        # Never overwrite the stored token with the masked placeholder/empty value
        # (GET returns SECRET_MASK so the real token is never exposed).
        new_token = frp_value.get("token")
        if not new_token or new_token == SECRET_MASK:
            if old_value.get("token"):
                frp_value["token"] = old_value["token"]
            else:
                frp_value.pop("token", None)
        
        if setting:
            setting.value = frp_value
            setting.updated_at = datetime.utcnow()
        else:
            setting = Settings(key="frp", value=frp_value)
            db.add(setting)
        
        await db.commit()
        await db.refresh(setting)
        
        resolved_token = frp_value.get("token")
        if new_enabled and not old_enabled:
            try:
                success = frp_comm_manager.start(settings_update.frp.port, resolved_token)
                if success:
                    logger.info(f"FRP communication server started on port {settings_update.frp.port}")
                else:
                    logger.warning(f"FRP communication server failed to start (binary may not be available)")
            except Exception as e:
                logger.error(f"Failed to start FRP communication server: {e}", exc_info=True)
        elif not new_enabled and old_enabled:
            frp_comm_manager.stop()
            logger.info("FRP communication server stopped")
    
    if settings_update.telegram:
        from app.telegram_bot import telegram_bot
        
        result = await db.execute(select(Settings).where(Settings.key == "telegram"))
        setting = result.scalar_one_or_none()
        
        old_value = dict(setting.value) if (setting and setting.value) else {}
        old_enabled = old_value.get("enabled", False)
        
        new_enabled = settings_update.telegram.enabled
        
        telegram_value = settings_update.telegram.dict(exclude_none=True)
        # Keep the stored bot token when the client sends the masked placeholder.
        new_bot_token = telegram_value.get("bot_token")
        if not new_bot_token or new_bot_token == SECRET_MASK:
            if old_value.get("bot_token"):
                telegram_value["bot_token"] = old_value["bot_token"]
            else:
                telegram_value.pop("bot_token", None)
        
        if setting:
            setting.value = telegram_value
            setting.updated_at = datetime.utcnow()
        else:
            setting = Settings(key="telegram", value=telegram_value)
            db.add(setting)
        
        await db.commit()
        await db.refresh(setting)
        
        if new_enabled and not old_enabled:
            try:
                await telegram_bot.start()
                logger.info("Telegram bot started")
            except Exception as e:
                logger.error(f"Failed to start Telegram bot: {e}", exc_info=True)
        elif not new_enabled and old_enabled:
            await telegram_bot.stop()
            logger.info("Telegram bot stopped")
        elif new_enabled and old_enabled:
            await telegram_bot.start_backup_task()
            logger.info("Telegram bot backup task restarted")
    
    if settings_update.tunnel:
        result = await db.execute(select(Settings).where(Settings.key == "tunnel"))
        setting = result.scalar_one_or_none()
        
        if setting:
            setting.value = settings_update.tunnel.dict(exclude_none=True)
            setting.updated_at = datetime.utcnow()
        else:
            setting = Settings(
                key="tunnel",
                value=settings_update.tunnel.dict(exclude_none=True)
            )
            db.add(setting)
        
        await db.commit()
        await db.refresh(setting)
        
        # Start/stop auto reapply task
        from app.tunnel_reapply_manager import tunnel_reapply_manager
        if settings_update.tunnel.auto_reapply_enabled:
            await tunnel_reapply_manager.start()
            logger.info("Tunnel auto reapply task started")
        else:
            await tunnel_reapply_manager.stop()
            logger.info("Tunnel auto reapply task stopped")
    
    return {"status": "success"}

