"""FRP communication manager for panel-node communication"""
import os
import subprocess
import time
import logging
from pathlib import Path
from typing import Dict, Optional
import asyncio

logger = logging.getLogger(__name__)


class FrpCommManager:
    """Manages FRP server for panel-node communication"""
    
    @staticmethod
    def _resolve_config_dir() -> Path:
        """Resolve a writable config dir that works on both Docker and native installs.

        Order: FRP_COMM_DIR env -> directory next to the SQLite DB (DB_PATH) ->
        a 'data/frp_comm' folder under the current working directory.
        """
        env_dir = os.environ.get("FRP_COMM_DIR")
        if env_dir:
            return Path(env_dir)
        db_path = os.environ.get("DB_PATH")
        if db_path:
            try:
                return Path(db_path).expanduser().resolve().parent / "frp_comm"
            except Exception:
                pass
        return Path.cwd() / "data" / "frp_comm"

    def __init__(self):
        self.config_dir = self._resolve_config_dir()
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"Could not create FRP comm dir {self.config_dir}: {e}")
        self.process: Optional[subprocess.Popen] = None
        self.config_file = self.config_dir / "frps_comm.yaml"
        self.log_file = self.config_dir / "frps_comm.log"
        self.enabled = False
        self.port = 7000
        self.token: Optional[str] = None
    
    def _resolve_binary_path(self) -> Path:
        """Resolve frps binary path"""
        env_path = os.environ.get("FRPS_BINARY")
        if env_path:
            resolved = Path(env_path)
            if resolved.exists() and resolved.is_file():
                return resolved
        
        common_paths = [
            Path("/usr/local/bin/frps"),
            Path("/usr/bin/frps"),
        ]
        
        for path in common_paths:
            if path.exists() and path.is_file():
                return path
        
        resolved = subprocess.run(["which", "frps"], capture_output=True, text=True)
        if resolved.returncode == 0 and resolved.stdout.strip():
            return Path(resolved.stdout.strip())
        
        raise FileNotFoundError(
            "frps binary not found. Expected at FRPS_BINARY, '/usr/local/bin/frps', or in PATH."
        )
    
    def start(self, port: int, token: Optional[str] = None) -> bool:
        """Start FRP server for panel-node communication"""
        if self.process and self.process.poll() is None:
            logger.warning("FRP communication server already running")
            return True
        
        try:
            self.port = port
            self.token = token
            
            config_content = f"""bindPort: {port}
"""
            if token:
                config_content += f"""auth:
  method: token
  token: "{token}"
"""
            
            with open(self.config_file, 'w') as f:
                f.write(config_content)
            
            try:
                binary_path = self._resolve_binary_path()
            except FileNotFoundError as e:
                logger.warning(f"FRP binary not found: {e}. FRP communication will not be available.")
                self.enabled = False
                return False
            
            cmd = [str(binary_path), "-c", str(self.config_file)]
            
            log_f = open(self.log_file, 'w', buffering=1)
            log_f.write(f"Starting FRP communication server on port {port}\n")
            log_f.write(f"Config: bind_port={port}, token={'set' if token else 'none'}\n")
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
                error_msg = f"FRP communication server failed to start: {error_output[-500:] if len(error_output) > 500 else error_output}"
                logger.error(error_msg)
                self.enabled = False
                return False
            
            self.enabled = True
            logger.info(f"[FRP] FRP communication server started on port {port} (PID: {self.process.pid})")
            logger.info(f"[FRP] Panel is now ready to accept FRP connections from nodes")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start FRP communication server: {e}")
            self.enabled = False
            return False
    
    def stop(self):
        """Stop FRP communication server"""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            except Exception as e:
                logger.warning(f"Error stopping FRP communication server: {e}")
            finally:
                self.process = None
                self.enabled = False
                logger.info("[FRP] FRP communication server stopped")
    
    def is_running(self) -> bool:
        """Check if server is running"""
        if not self.process:
            return False
        return self.process.poll() is None
    
    def get_config(self) -> Dict[str, any]:
        """Get current configuration"""
        return {
            "enabled": self.enabled,
            "port": self.port,
            "token": self.token,
            "running": self.is_running()
        }


frp_comm_manager = FrpCommManager()


