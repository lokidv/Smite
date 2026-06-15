"""Panel API endpoints"""
import logging
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from app.config import settings
from app.models import Admin
from app.routers.auth import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


def _resolve_env_file() -> Path:
    """Locate the .env that the running panel actually reads (native: /opt/smite/.env)."""
    candidates = [
        os.environ.get("SMITE_ENV_FILE"),
        "/opt/smite/.env",
        str(Path.cwd() / ".env"),
        str(Path(__file__).resolve().parents[3] / ".env"),
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return Path(c)
    return Path("/opt/smite/.env")


def _install_kind() -> str:
    return "docker" if Path("/.dockerenv").exists() else "native"


class PanelPortRequest(BaseModel):
    port: int


@router.get("/ca")
async def get_ca_cert(download: bool = False):
    """Get CA certificate for Iran node enrollment"""
    from app.node_server import NodeServer
    import os
    
    cert_path_str = settings.node_cert_path
    cert_path = Path(cert_path_str)
    
    if not cert_path.is_absolute():
        base_dir = Path(os.getcwd())
        cert_path = base_dir / cert_path
    
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    
    needs_generation = False
    if not cert_path.exists():
        needs_generation = True
        logger.info(f"CA certificate missing at {cert_path}, generating...")
    elif cert_path.stat().st_size == 0:
        needs_generation = True
        logger.info(f"CA certificate is empty (0 bytes) at {cert_path}, deleting and regenerating...")
        try:
            cert_path.unlink()
        except:
            pass
    
    if needs_generation:
        h2_server = NodeServer()
        h2_server.cert_path = str(cert_path)
        h2_server.key_path = str(cert_path.parent / "ca.key")
        await h2_server._generate_certs()
        logger.info(f"Certificate generated at {cert_path}")
    
    if not cert_path.exists():
        raise HTTPException(status_code=500, detail=f"Failed to generate CA certificate at {cert_path}")
    
    try:
        cert_content = cert_path.read_text()
        if not cert_content or not cert_content.strip():
            raise HTTPException(status_code=500, detail="CA certificate is empty after generation")
    except Exception as e:
        logger.error(f"Error reading certificate: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to read certificate: {str(e)}")
    
    if download:
        return FileResponse(
            cert_path,
            media_type="application/x-pem-file",
            filename="ca.crt",
            headers={"Content-Disposition": "attachment; filename=ca.crt"}
        )
    
    return Response(content=cert_content, media_type="text/plain")


@router.get("/ca/server")
async def get_server_ca_cert(download: bool = False):
    """Get CA certificate for foreign server enrollment"""
    from app.node_server import NodeServer
    import os
    
    cert_path_str = settings.node_server_cert_path
    cert_path = Path(cert_path_str)
    
    if not cert_path.is_absolute():
        base_dir = Path(os.getcwd())
        cert_path = base_dir / cert_path
    
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    
    needs_generation = False
    if not cert_path.exists():
        needs_generation = True
        logger.info(f"Server CA certificate missing at {cert_path}, generating...")
    elif cert_path.stat().st_size == 0:
        needs_generation = True
        logger.info(f"Server CA certificate is empty (0 bytes) at {cert_path}, deleting and regenerating...")
        try:
            cert_path.unlink()
        except:
            pass
    
    if needs_generation:
        h2_server = NodeServer()
        h2_server.cert_path = str(cert_path)
        h2_server.key_path = str(cert_path.parent / "ca-server.key")
        await h2_server._generate_certs(common_name="Smite Server CA")
        logger.info(f"Server certificate generated at {cert_path}")
    
    if not cert_path.exists():
        raise HTTPException(status_code=500, detail=f"Failed to generate server CA certificate at {cert_path}")
    
    try:
        cert_content = cert_path.read_text()
        if not cert_content or not cert_content.strip():
            raise HTTPException(status_code=500, detail="Server CA certificate is empty after generation")
    except Exception as e:
        logger.error(f"Error reading server certificate: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to read server certificate: {str(e)}")
    
    if download:
        return FileResponse(
            cert_path,
            media_type="application/x-pem-file",
            filename="ca-server.crt",
            headers={"Content-Disposition": "attachment; filename=ca-server.crt"}
        )
    
    return Response(content=cert_content, media_type="text/plain")


@router.get("/health")
async def health():
    """Health check"""
    return {"status": "ok"}


@router.get("/config")
async def get_panel_config(_user: Admin = Depends(get_current_user)):
    """Current panel listen settings (admin only)."""
    install = _install_kind()
    return {
        "port": settings.panel_port,
        "host": settings.panel_host,
        "install": install,
        "env_file": str(_resolve_env_file()),
        "self_restart_supported": install == "native",
    }


@router.put("/config/port")
async def set_panel_port(req: PanelPortRequest, _user: Admin = Depends(get_current_user)):
    """Change the panel listen port (admin only).

    Rewrites PANEL_PORT in the .env and, on native installs, restarts the panel
    out-of-band so the response is delivered before the restart. NOTE: registered
    nodes target this port, so changing it requires updating the nodes too.
    """
    port = req.port
    if port < 1 or port > 65535:
        raise HTTPException(status_code=400, detail="Port must be between 1 and 65535")
    if port == settings.node_port:
        raise HTTPException(status_code=400, detail=f"Port {port} is reserved for the node TLS channel")

    install = _install_kind()
    env_file = _resolve_env_file()

    try:
        lines = env_file.read_text().splitlines() if env_file.exists() else []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cannot read {env_file}: {e}")

    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith("PANEL_PORT="):
            lines[i] = f"PANEL_PORT={port}"
            found = True
            break
    if not found:
        lines.append(f"PANEL_PORT={port}")

    try:
        env_file.parent.mkdir(parents=True, exist_ok=True)
        env_file.write_text("\n".join(lines) + "\n")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cannot write {env_file}: {e}")

    if install == "docker":
        return {
            "status": "saved",
            "port": port,
            "restarted": False,
            "message": "Saved PANEL_PORT. Docker installs cannot self-restart; run `smite restart` on the host to apply.",
        }

    # Native: defer the restart so this HTTP response is returned first.
    ts = int(datetime.utcnow().timestamp())
    restart_cmd = "sleep 1; systemctl restart smite-panel"
    if shutil.which("systemd-run"):
        cmd = ["systemd-run", f"--unit=smite-panel-portchange-{ts}", "--collect", "/bin/bash", "-c", restart_cmd]
    else:
        cmd = ["setsid", "/bin/bash", "-c", restart_cmd]
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except Exception as e:
        return {
            "status": "saved",
            "port": port,
            "restarted": False,
            "message": f"Saved PANEL_PORT but auto-restart failed: {e}. Run `smite restart` on the host.",
        }
    return {"status": "restarting", "port": port, "restarted": True, "message": "Panel is restarting on the new port."}

