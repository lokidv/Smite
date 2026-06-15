"""FRP communication client for node-panel communication"""
import os
import subprocess
import time
import logging
from pathlib import Path
from typing import Dict, Optional
from app.config import settings

logger = logging.getLogger(__name__)


class FrpCommClient:
    """Manages FRP client for node-panel communication"""
    
    def __init__(self):
        self.config_dir = Path("/etc/smite-node/frp_comm")
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.process: Optional[subprocess.Popen] = None
        self.config_file = self.config_dir / "frpc_comm.yaml"
        self.log_file = self.config_dir / "frpc_comm.log"
        self.enabled = False
        self.server_addr: Optional[str] = None
        self.server_port: Optional[int] = None
        self.token: Optional[str] = None
        self.local_port = settings.node_api_port
        self.remote_port: Optional[int] = None
    
    def _resolve_binary_path(self) -> Path:
        """Resolve frpc binary path"""
        env_path = os.environ.get("FRPC_BINARY")
        if env_path:
            resolved = Path(env_path)
            if resolved.exists() and resolved.is_file():
                return resolved
        
        common_paths = [
            Path("/usr/local/bin/frpc"),
            Path("/usr/bin/frpc"),
        ]
        
        for path in common_paths:
            if path.exists() and path.is_file():
                return path
        
        import shutil
        resolved = shutil.which("frpc")
        if resolved:
            return Path(resolved)
        
        raise FileNotFoundError(
            "frpc binary not found. Expected at FRPC_BINARY, '/usr/local/bin/frpc', or in PATH."
        )
    
    def start(self, server_addr: str, server_port: int, token: Optional[str] = None, node_id: Optional[str] = None) -> bool:
        """Start FRP client for node-panel communication"""
        if self.process and self.process.poll() is None:
            logger.warning("FRP communication client already running")
            return True
        
        try:
            self.server_addr = server_addr
            self.server_port = server_port
            self.token = token
            self.enabled = True
            
            if node_id:
                import hashlib
                port_hash = int(hashlib.md5(node_id.encode()).hexdigest()[:8], 16)
                self.remote_port = 10000 + (port_hash % 10000)
            else:
                self.remote_port = None
            
            # loginFailExit: false -> frpc keeps retrying instead of exiting the
            # moment the panel's FRP port is briefly unreachable (firewall not yet
            # open, panel restarting, transient network). Without this, the very
            # first failed login kills the reverse tunnel permanently until the
            # node re-registers, which is exactly how foreign nodes end up with a
            # dead/defunct frpc and an unreachable API.
            config_content = f"""serverAddr: {server_addr}
serverPort: {server_port}
loginFailExit: false
transport:
  dialServerTimeout: 10
  dialServerKeepalive: 7200
"""
            if token:
                config_content += f"""auth:
  method: token
  token: "{token}"
"""
            
            # FRP proxy names should be alphanumeric and reasonably short
            if node_id:
                clean_id = node_id.replace("-", "")[:12]
                proxy_name = f"node_{clean_id}"
            else:
                if self.remote_port:
                    proxy_name = f"node_{self.remote_port}"
                else:
                    proxy_name = "node_api"
            
            config_content += f"""
proxies:
  - name: {proxy_name}
    type: tcp
    localIP: 127.0.0.1
    localPort: {self.local_port}
"""
            if self.remote_port:
                config_content += f"    remotePort: {self.remote_port}\n"
            
            with open(self.config_file, 'w') as f:
                f.write(config_content)
            
            binary_path = self._resolve_binary_path()
            cmd = [str(binary_path), "-c", str(self.config_file)]
            
            log_f = open(self.log_file, 'w', buffering=1)
            log_f.write(f"Starting FRP communication client\n")
            log_f.write(f"Server: {server_addr}:{server_port}\n")
            log_f.write(f"Local: 127.0.0.1:{self.local_port}\n")
            if self.remote_port:
                log_f.write(f"Remote port: {self.remote_port}\n")
            log_f.write(f"Command: {' '.join(cmd)}\n")
            log_f.flush()
            
            self.process = subprocess.Popen(
                cmd,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                cwd=str(self.config_dir),
                start_new_session=True
            )
            
            time.sleep(1.0)
            if self.process.poll() is not None:
                if self.log_file.exists():
                    with open(self.log_file, 'r') as f:
                        error_output = f.read()
                else:
                    error_output = "Log file not found"
                error_msg = f"FRP communication client failed to start: {error_output[-500:] if len(error_output) > 500 else error_output}"
                logger.error(error_msg)
                self.enabled = False
                raise RuntimeError(error_msg)
            
            logger.info(f"[FRP] FRP communication client started (PID: {self.process.pid}, remote_port={self.remote_port})")
            
            if self.remote_port:
                time.sleep(1)
                if self.log_file.exists():
                    with open(self.log_file, 'r') as f:
                        log_content = f.read()
                        if 'remotePort' in log_content or 'start proxy success' in log_content.lower():
                            logger.info(f"[FRP] FRP client connected successfully, remote port: {self.remote_port}")
                            logger.info(f"[FRP] Node API is now accessible to panel via FRP tunnel at 127.0.0.1:{self.remote_port}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start FRP communication client: {e}")
            self.enabled = False
            raise
    
    def stop(self):
        """Stop FRP communication client"""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            except Exception as e:
                logger.warning(f"Error stopping FRP communication client: {e}")
            finally:
                self.process = None
                self.enabled = False
                logger.info("[FRP] FRP communication client stopped")
    
    def is_running(self) -> bool:
        """Check if client is running"""
        if not self.process:
            return False
        return self.process.poll() is None
    
    def get_config(self) -> Dict[str, any]:
        """Get current configuration"""
        return {
            "enabled": self.enabled,
            "server_addr": self.server_addr,
            "server_port": self.server_port,
            "token": self.token,
            "local_port": self.local_port,
            "remote_port": self.remote_port,
            "running": self.is_running()
        }


frp_comm_client = FrpCommClient()

