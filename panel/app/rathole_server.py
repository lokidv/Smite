"""Rathole server management for panel"""
import subprocess
import time
import logging
from pathlib import Path
from typing import Dict, Optional

from app.utils import parse_address_port, format_address_port

logger = logging.getLogger(__name__)


class RatholeServerManager:
    """Manages Rathole server processes on the panel"""
    
    def __init__(self):
        self.config_dir = Path("/app/data/rathole")
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.active_servers: Dict[str, subprocess.Popen] = {}
        self.server_configs: Dict[str, dict] = {}
    
    def start_server(
        self,
        tunnel_id: str,
        remote_addr: str,
        token: str,
        proxy_port: int,
        use_ipv6: bool = False,
        transport: str = "tcp",
        service_type: str = "tcp",
        tls_pkcs12_b64: Optional[str] = None,
        tls_pkcs12_password: str = "",
    ) -> bool:
        """
        Start a Rathole server for a tunnel
        """
        try:
            _, port, _ = parse_address_port(remote_addr)
            if port is None:
                raise ValueError(f"Invalid remote_addr format: {remote_addr} (port required)")
            
            bind_addr = f"0.0.0.0:{port}"
            proxy_bind_addr = f"0.0.0.0:{proxy_port}"
            
            if tunnel_id in self.active_servers:
                logger.warning(f"Rathole server for tunnel {tunnel_id} already exists, stopping it first")
                self.stop_server(tunnel_id)
            
            config = f"""[server]
bind_addr = "{bind_addr}"
default_token = "{token}"
"""
            if transport == "tls" and tls_pkcs12_b64:
                import base64
                p12_path = self.config_dir / f"{tunnel_id}.p12"
                with open(p12_path, "wb") as f:
                    f.write(base64.b64decode(tls_pkcs12_b64))
                config += f"""
[server.transport]
type = "tls"

[server.transport.tls]
pkcs12 = "{p12_path}"
pkcs12_password = "{tls_pkcs12_password}"
"""
            svc_type_line = '\ntype = "udp"' if service_type == "udp" else ""
            config += f"""
[server.services.{tunnel_id}]{svc_type_line}
bind_addr = "{proxy_bind_addr}"
"""
            
            config_path = self.config_dir / f"{tunnel_id}.toml"
            with open(config_path, "w") as f:
                f.write(config)
            
            self.server_configs[tunnel_id] = {
                "remote_addr": remote_addr,
                "token": token,
                "proxy_port": proxy_port,
                "bind_addr": bind_addr,
                "config_path": str(config_path)
            }
            
            log_file = self.config_dir / f"rathole_{tunnel_id}.log"
            try:
                log_f = open(log_file, 'w', buffering=1)
                log_f.write(f"Starting rathole server for tunnel {tunnel_id}\n")
                log_f.write(f"Config: bind_addr={bind_addr}, proxy_port={proxy_port}\n")
                log_f.write(f"Config file: {config_path}\n")
                log_f.write(f"Config content:\n{config}\n")
                log_f.flush()
                proc = subprocess.Popen(
                    ["/usr/local/bin/rathole", "-s", str(config_path)],
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    cwd=str(self.config_dir),
                    start_new_session=True
                )
            except FileNotFoundError:
                log_f = open(log_file, 'w', buffering=1)
                log_f.write(f"Starting rathole server (system binary) for tunnel {tunnel_id}\n")
                log_f.flush()
                proc = subprocess.Popen(
                    ["rathole", "-s", str(config_path)],
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    cwd=str(self.config_dir),
                    start_new_session=True
                )
            
            self.active_servers[f"{tunnel_id}_log"] = log_f
            self.active_servers[tunnel_id] = proc
            
            time.sleep(1.0)
            if proc.poll() is not None:
                try:
                    if log_file.exists():
                        with open(log_file, 'r') as f:
                            error_output = f.read()
                    else:
                        error_output = "Log file not found"
                    error_msg = f"rathole server failed to start (exit code: {proc.poll()}): {error_output[-500:] if len(error_output) > 500 else error_output}"
                    logger.error(error_msg)
                except Exception as e:
                    error_msg = f"rathole server failed to start (exit code: {proc.poll()}), could not read log: {e}"
                    logger.error(error_msg)
                finally:
                    del self.active_servers[tunnel_id]
                    if f"{tunnel_id}_log" in self.active_servers:
                        try:
                            self.active_servers[f"{tunnel_id}_log"].close()
                        except:
                            pass
                        del self.active_servers[f"{tunnel_id}_log"]
                    if tunnel_id in self.server_configs:
                        del self.server_configs[tunnel_id]
                raise RuntimeError(error_msg)
            
            try:
                import socket
                _, port, _ = parse_address_port(bind_addr)
                if port:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(1)
                    result = sock.connect_ex(('127.0.0.1', port))
                    sock.close()
                    if result != 0:
                        logger.warning(f"Rathole server port {port} not listening after start, but process is running. PID: {proc.pid}")
            except Exception as e:
                logger.warning(f"Could not verify rathole server port is listening: {e}")
            
            logger.info(f"Started Rathole server for tunnel {tunnel_id} on {bind_addr}, proxy port: {proxy_port}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start Rathole server for tunnel {tunnel_id}: {e}")
            raise
    
    def stop_server(self, tunnel_id: str):
        """Stop Rathole server for a tunnel"""
        if tunnel_id in self.active_servers:
            proc = self.active_servers[tunnel_id]
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            except Exception as e:
                logger.warning(f"Error stopping Rathole server for tunnel {tunnel_id}: {e}")
            finally:
                del self.active_servers[tunnel_id]
                log_key = f"{tunnel_id}_log"
                if log_key in self.active_servers:
                    try:
                        self.active_servers[log_key].close()
                    except:
                        pass
                    del self.active_servers[log_key]
            
            logger.info(f"Stopped Rathole server for tunnel {tunnel_id}")
        
        if tunnel_id in self.server_configs:
            config_path = Path(self.server_configs[tunnel_id]["config_path"])
            if config_path.exists():
                try:
                    config_path.unlink()
                except Exception as e:
                    logger.warning(f"Failed to delete config file {config_path}: {e}")
            del self.server_configs[tunnel_id]
    
    def is_running(self, tunnel_id: str) -> bool:
        """Check if server is running for a tunnel"""
        if tunnel_id not in self.active_servers:
            return False
        proc = self.active_servers[tunnel_id]
        return proc.poll() is None
    
    def get_active_servers(self) -> list:
        """Get list of tunnel IDs with active servers"""
        active = []
        for tunnel_id, proc in list(self.active_servers.items()):
            if proc.poll() is None:
                active.append(tunnel_id)
            else:
                del self.active_servers[tunnel_id]
                if tunnel_id in self.server_configs:
                    del self.server_configs[tunnel_id]
        return active
    
    def cleanup_all(self):
        """Stop all Rathole servers"""
        tunnel_ids = list(self.active_servers.keys())
        for tunnel_id in tunnel_ids:
            self.stop_server(tunnel_id)


rathole_server_manager = RatholeServerManager()

