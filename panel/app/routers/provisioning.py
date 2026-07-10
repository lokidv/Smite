"""Remote provisioning (Install Node) API endpoints.

Lets an admin install the Smite node, the 3x-ui panel and WireGuard on a remote
server over SSH straight from the panel UI. For Iran / no-internet targets the
admin first uploads the required artifacts (Smite offline bundle, 3x-ui release
tarball); the panel then pushes them via SFTP.
"""
from __future__ import annotations

import asyncio
import os
import socket
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import ProxyServer
from app.routers.auth import get_current_user
from app.provisioning.vault import encrypt, decrypt
from app.provisioning.service import (
    ProvisionParams,
    apply_proxy_update,
    create_job,
    get_job,
    list_jobs,
    run_job,
)

router = APIRouter()

ALLOWED_ARTIFACT_KINDS = {"bundle", "xui"}


def _artifacts_dir() -> Path:
    data_dir = Path(settings.db_path)
    if not data_dir.is_absolute():
        data_dir = Path(os.getcwd()) / data_dir
    artifacts = data_dir.parent / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    return artifacts


def _safe_name(name: str) -> str:
    return Path(name).name


def _read_ca(role: str) -> str:
    cert = settings.node_cert_path if role == "iran" else settings.node_server_cert_path
    path = Path(cert)
    if not path.is_absolute():
        path = Path(os.getcwd()) / path
    if path.exists():
        try:
            return path.read_text()
        except Exception:  # noqa: BLE001
            return ""
    return ""


def _detect_panel_host() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        host = s.getsockname()[0]
        s.close()
        return host
    except Exception:  # noqa: BLE001
        return "127.0.0.1"


# -- artifacts ---------------------------------------------------------------
@router.post("/artifacts")
async def upload_artifact(
    kind: str = Form(...),
    file: UploadFile = File(...),
    _user=Depends(get_current_user),
):
    """Upload an installable artifact (kind: bundle | xui)."""
    if kind not in ALLOWED_ARTIFACT_KINDS:
        raise HTTPException(status_code=400, detail=f"Invalid kind '{kind}'")
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    dest = _artifacts_dir() / _safe_name(file.filename)
    size = 0
    with open(dest, "wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
            size += len(chunk)

    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # Integrity: a truncated/corrupt archive would only fail later during the SSH
    # install. Validate the archive header up-front and reject bad uploads.
    name_lower = dest.name.lower()
    try:
        if name_lower.endswith((".tar.gz", ".tgz")):
            import tarfile
            with tarfile.open(dest, "r:gz") as tf:
                if tf.next() is None:
                    raise ValueError("empty tar archive")
        elif name_lower.endswith(".gz"):
            import gzip
            with gzip.open(dest, "rb") as gz:
                gz.read(1024)
    except Exception as e:  # noqa: BLE001
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Uploaded archive is corrupt or truncated: {e}")

    return {"name": dest.name, "size": size, "kind": kind}


@router.get("/artifacts")
async def list_artifacts(_user=Depends(get_current_user)):
    """List uploaded artifacts."""
    items = []
    for f in sorted(_artifacts_dir().glob("*")):
        if f.is_file():
            items.append({"name": f.name, "size": f.stat().st_size})
    return items


@router.delete("/artifacts/{name}")
async def delete_artifact(name: str, _user=Depends(get_current_user)):
    """Delete an uploaded artifact."""
    path = _artifacts_dir() / _safe_name(name)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    path.unlink()
    return {"status": "deleted"}


# -- install -----------------------------------------------------------------
class ProvisionRequest(BaseModel):
    host: str
    ssh_port: int = 22
    username: str
    password: str
    role: str
    node_name: str = "node-1"
    panel_host: Optional[str] = None
    panel_api_port: int = 8000
    install_node: bool = False
    install_xui: bool = False
    install_wireguard: bool = False
    install_openvpn: bool = False
    install_warp: bool = False
    xui_version: str = "v2.9.4"
    xui_port: Optional[int] = None
    xui_username: Optional[str] = None
    xui_password: Optional[str] = None
    # OpenVPN options
    ovpn_vpn_port: int = 1194
    ovpn_protocol: str = "udp"
    ovpn_panel_port: int = 4000
    ovpn_default_limit_gb: Optional[float] = None
    # WARP (wginstaller-proxy) upstream-proxy egress options
    warp_mode: str = "warp"  # warp | proxy
    warp_panel_port: int = 4000
    warp_proxy_ip: Optional[str] = None
    warp_proxy_port: Optional[str] = None
    warp_proxy_type: str = "socks5"
    warp_proxy_user: Optional[str] = None
    warp_proxy_pass: Optional[str] = None
    bundle_artifact: Optional[str] = None
    xui_artifact: Optional[str] = None
    system_upgrade: bool = True


@router.post("/install")
async def start_install(req: ProvisionRequest, _user=Depends(get_current_user)):
    """Validate the request and start a background provisioning job."""
    if req.role not in ("iran", "foreign"):
        raise HTTPException(status_code=400, detail="role must be 'iran' or 'foreign'")
    if not (
        req.install_node
        or req.install_xui
        or req.install_wireguard
        or req.install_openvpn
        or req.install_warp
    ):
        raise HTTPException(status_code=400, detail="Select at least one component to install")
    if req.install_wireguard and req.role != "foreign":
        raise HTTPException(status_code=400, detail="WireGuard can only be installed on a foreign server")
    if req.install_openvpn and req.role != "foreign":
        raise HTTPException(status_code=400, detail="OpenVPN can only be installed on a foreign server")
    if req.install_warp and req.role != "foreign":
        raise HTTPException(status_code=400, detail="WARP can only be installed on a foreign server")
    if req.install_openvpn and req.ovpn_protocol not in ("udp", "tcp"):
        raise HTTPException(status_code=400, detail="OpenVPN protocol must be 'udp' or 'tcp'")
    if req.install_warp and (req.warp_mode or "warp") not in ("warp", "proxy"):
        raise HTTPException(status_code=400, detail="WARP mode must be 'warp' or 'proxy'")
    if req.install_warp and (req.warp_proxy_type or "socks5") not in ("socks5", "http-connect"):
        raise HTTPException(status_code=400, detail="WARP proxy type must be 'socks5' or 'http-connect'")
    if req.install_warp and (req.warp_mode or "warp") == "proxy" and not (
        (req.warp_proxy_ip or "").strip() and (req.warp_proxy_port or "").strip()
    ):
        raise HTTPException(status_code=400, detail="Proxy mode requires a proxy IP and port")
    if not req.host or not req.username or not req.password:
        raise HTTPException(status_code=400, detail="host, username and password are required")

    artifacts_dir = _artifacts_dir()

    # All uploaded offline bundles; the service auto-picks the one matching the
    # target's arch + Python version (their wheels are Python-version specific).
    bundle_candidates = [
        str(f)
        for f in sorted(artifacts_dir.glob("smite-offline-*.tar.gz"))
        if f.is_file()
    ]

    bundle_path: Optional[str] = None
    if req.bundle_artifact:
        candidate = artifacts_dir / _safe_name(req.bundle_artifact)
        if not candidate.exists():
            raise HTTPException(status_code=400, detail=f"Bundle artifact '{req.bundle_artifact}' not found")
        bundle_path = str(candidate)

    xui_tarball_path: Optional[str] = None
    if req.xui_artifact:
        candidate = artifacts_dir / _safe_name(req.xui_artifact)
        if not candidate.exists():
            raise HTTPException(status_code=400, detail=f"3x-ui artifact '{req.xui_artifact}' not found")
        xui_tarball_path = str(candidate)

    # An Iran target cannot reach GitHub, so the relevant artifacts must be
    # pre-uploaded for the components that need them. The exact bundle is chosen
    # at run time once the target's Python version is known, so here we only
    # require that at least one offline bundle has been uploaded.
    if req.role == "iran":
        if req.install_node and not (bundle_path or bundle_candidates):
            raise HTTPException(
                status_code=400,
                detail="Iran node install requires an uploaded Smite offline bundle",
            )
        if req.install_xui and not xui_tarball_path:
            raise HTTPException(
                status_code=400,
                detail="Iran 3x-ui install requires an uploaded x-ui release tarball",
            )

    ca_pem = _read_ca(req.role) if req.install_node else ""
    panel_host = req.panel_host or _detect_panel_host()

    params = ProvisionParams(
        host=req.host,
        username=req.username,
        password=req.password,
        role=req.role,
        ssh_port=req.ssh_port,
        node_name=req.node_name,
        panel_host=panel_host,
        panel_api_port=req.panel_api_port,
        install_node=req.install_node,
        install_xui=req.install_xui,
        install_wireguard=req.install_wireguard,
        install_openvpn=req.install_openvpn,
        install_warp=req.install_warp,
        ovpn_vpn_port=req.ovpn_vpn_port,
        ovpn_protocol=req.ovpn_protocol,
        ovpn_panel_port=req.ovpn_panel_port,
        ovpn_default_limit_gb=req.ovpn_default_limit_gb,
        warp_mode=(req.warp_mode or "warp"),
        warp_panel_port=req.warp_panel_port,
        warp_proxy_ip=(req.warp_proxy_ip or ""),
        warp_proxy_port=(req.warp_proxy_port or ""),
        warp_proxy_type=(req.warp_proxy_type or "socks5"),
        warp_proxy_user=(req.warp_proxy_user or ""),
        warp_proxy_pass=(req.warp_proxy_pass or ""),
        xui_version=req.xui_version,
        xui_port=req.xui_port,
        xui_username=req.xui_username,
        xui_password=req.xui_password,
        bundle_path=bundle_path,
        xui_tarball_path=xui_tarball_path,
        ca_pem=ca_pem,
        system_upgrade=req.system_upgrade,
        bundle_candidates=bundle_candidates,
    )

    # An explicit (re)install means the admin wants this host enrolled, so clear
    # any prior revocation for it. Otherwise the freshly provisioned node's
    # self-registration is rejected with 403 and the agent (which stops retrying
    # on 403) leaves the job hanging on "waiting for the node to register".
    # The node registers with its own IP and api_port 8888.
    if req.install_node:
        import hashlib
        from sqlalchemy import delete as _sa_delete
        from app.database import AsyncSessionLocal as _Session
        from app.models import RevokedNode as _Revoked
        _fp = hashlib.sha256(f"{req.host}:8888".encode()).hexdigest()[:16]
        try:
            async with _Session() as _s:
                await _s.execute(_sa_delete(_Revoked).where(_Revoked.fingerprint == _fp))
                await _s.commit()
        except Exception:
            pass

    job = create_job(params)
    asyncio.create_task(run_job(job))
    return {"job_id": job.id, "status": job.status}


@router.get("/install/{job_id}")
async def get_install(job_id: str, _user=Depends(get_current_user)):
    """Return the live status, logs and results of a provisioning job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.snapshot()


@router.get("/installs")
async def get_installs(_user=Depends(get_current_user)):
    """List recent provisioning jobs."""
    return list_jobs()


# -- WARP / proxy server management ------------------------------------------
def _serialize_proxy_server(row: ProxyServer) -> dict:
    """Public view of a persisted proxy/WARP server (no secrets)."""
    return {
        "id": row.id,
        "host": row.host,
        "ssh_port": row.ssh_port,
        "ssh_user": row.ssh_user,
        "has_ssh_password": bool(row.ssh_password_enc),
        "mode": row.mode,
        "wg_port": row.wg_port,
        "api_port": row.api_port,
        "api_base_url": f"http://{row.host}:{row.api_port}" if row.api_port else "",
        "proxy_ip": row.proxy_ip,
        "proxy_port": row.proxy_port,
        "proxy_type": row.proxy_type,
        "proxy_user": row.proxy_user,
        "proxy_endpoint": f"{row.proxy_ip}:{row.proxy_port}" if row.proxy_ip else "",
        "proxy_status": row.proxy_status,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


class ProxyUpdateRequest(BaseModel):
    mode: str = "proxy"  # warp | proxy
    proxy_ip: Optional[str] = None
    proxy_port: Optional[str] = None
    proxy_type: str = "socks5"
    proxy_user: Optional[str] = None
    proxy_pass: Optional[str] = None
    # Only needed if the stored SSH password is missing or the admin wants to
    # update it. When provided it replaces the stored (encrypted) password.
    ssh_password: Optional[str] = None


@router.get("/proxy-servers")
async def list_proxy_servers(
    db: AsyncSession = Depends(get_db), _user=Depends(get_current_user)
):
    """List foreign servers where WARP/proxy was installed (for later editing)."""
    rows = (await db.execute(select(ProxyServer))).scalars().all()
    rows = sorted(rows, key=lambda r: r.updated_at or r.created_at, reverse=True)
    return [_serialize_proxy_server(r) for r in rows]


@router.post("/proxy-servers/{server_id}/update-proxy")
async def update_proxy_server(
    server_id: str,
    req: ProxyUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Change the egress proxy (or switch WARP<->proxy) on an installed server,
    re-applying it over SSH so the new upstream takes effect and the old is dropped."""
    row = await db.get(ProxyServer, server_id)
    if not row:
        raise HTTPException(status_code=404, detail="Proxy server not found")

    mode = req.mode or "proxy"
    if mode not in ("warp", "proxy"):
        raise HTTPException(status_code=400, detail="mode must be 'warp' or 'proxy'")
    if req.proxy_type and req.proxy_type not in ("socks5", "http-connect"):
        raise HTTPException(status_code=400, detail="proxy_type must be 'socks5' or 'http-connect'")

    # SSH password: use the freshly provided one, else the stored (encrypted) one.
    ssh_pw = (req.ssh_password or "").strip() or decrypt(row.ssh_password_enc)
    if not ssh_pw:
        raise HTTPException(
            status_code=400,
            detail="SSH password required (none stored for this server); provide ssh_password.",
        )

    if mode == "warp":
        proxy_ip, proxy_port, proxy_type = "127.0.0.1", "40000", "socks5"
        proxy_user, proxy_pass = "", ""
    else:
        proxy_ip = (req.proxy_ip or "").strip()
        proxy_port = (req.proxy_port or "").strip()
        if not (proxy_ip and proxy_port):
            raise HTTPException(status_code=400, detail="Proxy mode requires proxy_ip and proxy_port")
        proxy_type = req.proxy_type or "socks5"
        proxy_user = req.proxy_user or ""
        # Keep the stored proxy password unless a new one was supplied.
        proxy_pass = req.proxy_pass if req.proxy_pass is not None else decrypt(row.proxy_password_enc)

    try:
        result = await asyncio.to_thread(
            apply_proxy_update,
            row.host,
            row.ssh_port,
            row.ssh_user,
            ssh_pw,
            mode,
            proxy_ip,
            proxy_port,
            proxy_type,
            proxy_user,
            proxy_pass,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Failed to apply proxy update: {exc}")

    # Persist the new state (encrypt any updated secrets).
    row.mode = mode
    row.proxy_ip = proxy_ip
    row.proxy_port = proxy_port
    row.proxy_type = proxy_type
    row.proxy_user = proxy_user
    row.proxy_password_enc = encrypt(proxy_pass)
    row.proxy_status = result.get("proxyStatus", "unknown")
    if (req.ssh_password or "").strip():
        row.ssh_password_enc = encrypt(req.ssh_password.strip())
    await db.commit()

    return {"status": "ok", "result": result, "server": _serialize_proxy_server(row)}


@router.delete("/proxy-servers/{server_id}")
async def delete_proxy_server(
    server_id: str, db: AsyncSession = Depends(get_db), _user=Depends(get_current_user)
):
    """Forget a proxy/WARP server record (does NOT uninstall anything remotely)."""
    row = await db.get(ProxyServer, server_id)
    if not row:
        raise HTTPException(status_code=404, detail="Proxy server not found")
    await db.delete(row)
    await db.commit()
    return {"status": "deleted"}
