"""Panel client for node to connect to panel"""
import asyncio
import httpx
import hashlib
import os
import socket
import logging
from pathlib import Path
from typing import Optional
from app.config import settings
from app.frp_comm_client import frp_comm_client

logger = logging.getLogger(__name__)


class PanelClient:
    """Client connecting to panel via HTTP/HTTPS or FRP"""
    
    def __init__(self):
        self.panel_address = settings.panel_address
        self.ca_path = Path(settings.panel_ca_path)
        self.client = None
        self.node_id = None
        self.fingerprint = None
        self.registered = False
        self.using_frp = False
        self.frp_panel_url: Optional[str] = None
        self.blocked = False  # set when the panel revokes this node (HTTP 403)
    
    async def start(self):
        """Start client and connect to panel"""
        if not self.ca_path.exists():
            raise FileNotFoundError(f"CA certificate not found at {self.ca_path}")
        
        await self._generate_fingerprint()
        
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            verify=False
        )
        
        logger.info(f"Node client ready, panel address: {self.panel_address}")
    
    async def stop(self):
        """Stop client"""
        frp_comm_client.stop()
        if self.client:
            await self.client.aclose()
            self.client = None
    
    async def register_with_panel(self):
        """Auto-register with panel"""
        if not self.client:
            await self.start()
        
        if "://" in self.panel_address:
            protocol, rest = self.panel_address.split("://", 1)
            if ":" in rest:
                panel_host, panel_hysteria_port = rest.split(":", 1)
            else:
                panel_host = rest
                panel_hysteria_port = "443"
        else:
            protocol = "http"
            if ":" in self.panel_address:
                panel_host, panel_hysteria_port = self.panel_address.split(":", 1)
            else:
                panel_host = self.panel_address
                panel_hysteria_port = "443"
        
        panel_api_port = settings.panel_api_port
        
        panel_api_url = f"http://{panel_host}:{panel_api_port}"
        
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            node_ip = s.getsockname()[0]
            s.close()
        except:
            node_ip = "0.0.0.0"
        
        registration_data = {
            "name": settings.node_name,
            "ip_address": node_ip,
            "api_port": settings.node_api_port,
            "fingerprint": self.fingerprint,
            "metadata": {
                "api_address": f"http://{node_ip}:{settings.node_api_port}",
                "node_name": settings.node_name,
                "panel_address": self.panel_address,
                "role": settings.node_role  # "iran" or "foreign"
            }
        }
        
        try:
            url = f"{panel_api_url}/api/nodes"
            is_initial = not self.registered
            if is_initial:
                logger.info(f"[HTTP] Registering with panel at {url}...")
            else:
                logger.debug(f"[HTTP] Re-registering with panel at {url}...")
            response = await self.client.post(url, json=registration_data, timeout=10.0)
            
            if response.status_code in [200, 201]:
                data = response.json()
                self.node_id = data.get("id")
                was_registered = self.registered
                self.registered = True
                if was_registered:
                    logger.debug(f"[HTTP] Node re-registered successfully with ID: {self.node_id}")
                else:
                    logger.info(f"[HTTP] Node registered successfully with ID: {self.node_id}")
                
                metadata = data.get("metadata", {})
                frp_config = metadata.get("frp_config")
                if frp_config and frp_config.get("enabled"):
                    # Check if FRP is already running with the same config
                    if frp_comm_client.is_running():
                        current_config = frp_comm_client.get_config()
                        if (current_config.get("server_addr") == frp_config.get("server_addr") and
                            current_config.get("server_port") == frp_config.get("server_port") and
                            current_config.get("token") == frp_config.get("token")):
                            logger.debug("[FRP] FRP client already running with correct config, skipping setup")
                        else:
                            logger.info(f"[FRP] FRP config changed, restarting FRP client...")
                            frp_comm_client.stop()
                            await self._setup_frp(frp_config)
                    else:
                        logger.info(f"[FRP] FRP communication enabled by panel, setting up FRP client...")
                        await self._setup_frp(frp_config)
                else:
                    # FRP is disabled, stop it if running
                    if frp_comm_client.is_running():
                        logger.info(f"[FRP] FRP communication disabled, stopping FRP client...")
                        frp_comm_client.stop()
                        self.using_frp = False
                    logger.info(f"[HTTP] FRP communication not enabled, continuing with HTTP")
                
                return True
            else:
                if response.status_code == 403:
                    self.blocked = True
                    logger.error(
                        "Panel revoked this node (HTTP 403): it was deleted in the panel. "
                        "Stopping auto-registration. Clear its revocation in the panel to re-enroll."
                    )
                logger.error(f"Registration failed: {response.status_code} - {response.text}")
                return False
        except httpx.ConnectError as e:
            logger.error(f"Cannot connect to panel at {panel_api_url}: {str(e)}. Make sure panel is running and accessible")
            return False
        except Exception as e:
            logger.error(f"Registration error: {str(e)}")
            return False
    
    async def _setup_frp(self, frp_config: dict):
        """Setup FRP client connection"""
        try:
            server_addr = frp_config.get("server_addr")
            server_port = frp_config.get("server_port", 7000)
            token = frp_config.get("token")
            
            if not server_addr:
                logger.warning("FRP enabled but server_addr not provided")
                return
            
            logger.info(f"[FRP] Starting FRP client: server={server_addr}:{server_port}")
            frp_comm_client.start(server_addr, server_port, token, self.node_id)
            
            await asyncio.sleep(3)
            
            if frp_comm_client.is_running():
                config = frp_comm_client.get_config()
                remote_port = config.get("remote_port")
                
                if remote_port:
                    logger.info(f"[HTTP] Reporting FRP status to panel (last HTTP call before switching to FRP)")
                    await self._report_frp_status(remote_port)
                    
                    logger.info(f"[FRP] FRP client connected successfully. All panel->node communication will now use FRP tunnel (remote_port={remote_port})")
                    self.using_frp = True
                else:
                    logger.warning("FRP client started but remote_port not available")
            else:
                logger.error("FRP client failed to start")
        except Exception as e:
            logger.error(f"Failed to setup FRP: {e}", exc_info=True)
    
    async def _report_frp_status(self, remote_port: int):
        """Report FRP connection status to panel"""
        if not self.node_id:
            return
        
        try:
            if "://" in self.panel_address:
                protocol, rest = self.panel_address.split("://", 1)
                if ":" in rest:
                    panel_host, _ = rest.split(":", 1)
                else:
                    panel_host = rest
            else:
                if ":" in self.panel_address:
                    panel_host, _ = self.panel_address.split(":", 1)
                else:
                    panel_host = self.panel_address
            
            panel_api_port = settings.panel_api_port
            panel_api_url = f"http://{panel_host}:{panel_api_port}"
            
            url = f"{panel_api_url}/api/nodes/{self.node_id}/frp-status"
            _tok = os.environ.get("NODE_API_TOKEN", "")
            response = await self.client.put(url, json={
                "connected": True,
                "remote_port": remote_port
            }, headers=({"X-Node-Token": _tok} if _tok else None), timeout=10.0)
            
            if response.status_code == 200:
                logger.info(f"[HTTP] FRP status reported to panel: remote_port={remote_port} (last HTTP call)")
            else:
                logger.warning(f"[HTTP] Failed to report FRP status: {response.status_code}")
        except Exception as e:
            logger.error(f"Error reporting FRP status: {e}")
    
    async def _generate_fingerprint(self):
        """Generate node fingerprint for identification"""
        import socket
        hostname = socket.gethostname()
        fingerprint_data = f"{hostname}-{settings.node_name}".encode()
        self.fingerprint = hashlib.sha256(fingerprint_data).hexdigest()[:16]
        print(f"Node fingerprint: {self.fingerprint}")
    
