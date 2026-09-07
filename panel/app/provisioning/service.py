"""Remote provisioning orchestration.

A provisioning request becomes an in-memory :class:`ProvisioningJob` that runs
in a background thread (paramiko is blocking). Each selected step (Smite node,
3x-ui, WireGuard) runs independently so one failing does not abort the others.
Live log lines and structured results are exposed for the UI to poll.
"""
from __future__ import annotations

import asyncio
import json
import os
import shlex
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import logging

from .ssh_client import SSHError, SSHSession

logger = logging.getLogger(__name__)

SCRIPTS_DIR = Path(__file__).resolve().parent / "scripts"

# Remote temp locations used during provisioning.
REMOTE_CA = "/tmp/smite-panel-ca.crt"
REMOTE_BUNDLE = "/root/smite-offline.tar.gz"
REMOTE_BUNDLE_DIR = "/root/smite-bundle"
REMOTE_SMITE_NODE = "/root/smite-node.sh"
REMOTE_XUI_SCRIPT = "/root/smite-install-3xui.sh"
REMOTE_XUI_TARBALL = "/root/smite-x-ui.tar.gz"
REMOTE_WG_SCRIPT = "/root/smite-install-wireguard.sh"
REMOTE_OVPN_SCRIPT = "/root/smite-install-openvpn.sh"
REMOTE_OVPN_BUNDLE = "/root/smite-openvpn-bundle.tar.gz"
REMOTE_WARP_SCRIPT = "/root/smite-install-warp.sh"
REMOTE_WARP_BUNDLE = "/root/smite-warp-bundle.tar.gz"
REMOTE_UPDATE_PROXY_SCRIPT = "/root/smite-update-proxy.sh"
REMOTE_PREP_SCRIPT = "/tmp/smite-prepare.sh"
REMOTE_FETCH_SCRIPT = "/root/smite-fetch-bundle.sh"

# OpenVPN and WARP (wginstaller-proxy) are not published on GitHub like the base
# wginstaller is, so the panel ships their installer trees under scripts/ and
# uploads them as a tarball at install time (keeps them offline-capable too).
OPENVPN_BUNDLE_DIR = SCRIPTS_DIR / "openvpn"
WARP_BUNDLE_DIR = SCRIPTS_DIR / "warp"

# Foreign nodes have internet, so when no offline bundle is uploaded they install
# NATIVELY by downloading the matching release bundle from GitHub on the target.
# This keeps every node native and panel-updatable (no Docker dead-end).
PROVISION_REPO = os.environ.get("SMITE_UPDATE_REPO", "lokidv/Smite")
_PY_OSLABEL = {"3.10": "ubuntu22.04-py310", "3.11": "debian12-py311", "3.12": "ubuntu24.04-py312"}


class ProvisioningError(Exception):
    """A provisioning step failed."""


@dataclass
class ProvisionParams:
    host: str
    username: str
    password: str
    role: str  # "iran" | "foreign"
    ssh_port: int = 22
    node_name: str = "node-1"
    panel_host: str = ""
    panel_api_port: int = 8000
    install_node: bool = False
    install_xui: bool = False
    install_wireguard: bool = False
    install_openvpn: bool = False
    install_warp: bool = False
    # OpenVPN options
    ovpn_vpn_port: int = 1194
    ovpn_protocol: str = "udp"  # udp | tcp
    ovpn_panel_port: int = 4000
    ovpn_default_limit_gb: Optional[float] = None
    # WARP (wginstaller-proxy) upstream-proxy egress options
    warp_mode: str = "warp"  # warp | proxy
    warp_panel_port: int = 4000
    warp_proxy_ip: str = ""
    warp_proxy_port: str = ""
    warp_proxy_type: str = "socks5"  # socks5 | http-connect
    warp_proxy_user: str = ""
    warp_proxy_pass: str = ""
    xui_version: str = "v2.9.4"
    xui_port: Optional[int] = None
    xui_username: Optional[str] = None
    xui_password: Optional[str] = None
    bundle_path: Optional[str] = None
    xui_tarball_path: Optional[str] = None
    ca_pem: str = ""
    # Run apt-get update + upgrade on the target before installing.
    system_upgrade: bool = True
    # All uploaded Smite offline bundles (the panel auto-picks the one matching
    # the target's arch + Python version).
    bundle_candidates: List[str] = field(default_factory=list)


class ProvisioningJob:
    def __init__(self, params: ProvisionParams) -> None:
        self.id = uuid.uuid4().hex[:16]
        self.params = params
        self.status = "pending"  # pending | running | success | error
        self.logs: List[Dict[str, str]] = []
        self.results: Dict[str, Any] = {}
        self.error: Optional[str] = None
        self.had_error = False
        self.created_at = datetime.utcnow()
        self.finished_at: Optional[datetime] = None
        self._lock = threading.Lock()

    # -- logging -----------------------------------------------------------
    def log(self, message: str, level: str = "info") -> None:
        entry = {
            "time": datetime.utcnow().isoformat(),
            "level": level,
            "message": message,
        }
        with self._lock:
            self.logs.append(entry)
        logger.info("[provision %s] %s", self.id, message)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "id": self.id,
                "status": self.status,
                "error": self.error,
                "created_at": self.created_at.isoformat(),
                "finished_at": self.finished_at.isoformat() if self.finished_at else None,
                "logs": list(self.logs),
                "results": json.loads(json.dumps(self.results)),
                "request": {
                    "host": self.params.host,
                    "role": self.params.role,
                    "node_name": self.params.node_name,
                    "install_node": self.params.install_node,
                    "install_xui": self.params.install_xui,
                    "install_wireguard": self.params.install_wireguard,
                    "install_openvpn": self.params.install_openvpn,
                    "install_warp": self.params.install_warp,
                },
            }


_JOBS: Dict[str, ProvisioningJob] = {}
_JOBS_LOCK = threading.Lock()
_MAX_JOBS = 50


def create_job(params: ProvisionParams) -> ProvisioningJob:
    job = ProvisioningJob(params)
    with _JOBS_LOCK:
        _JOBS[job.id] = job
        # Trim oldest finished jobs to keep memory bounded.
        if len(_JOBS) > _MAX_JOBS:
            for old_id in sorted(_JOBS, key=lambda k: _JOBS[k].created_at)[: len(_JOBS) - _MAX_JOBS]:
                if _JOBS[old_id].status in ("success", "error"):
                    _JOBS.pop(old_id, None)
    return job


def get_job(job_id: str) -> Optional[ProvisioningJob]:
    with _JOBS_LOCK:
        return _JOBS.get(job_id)


def list_jobs() -> List[Dict[str, Any]]:
    with _JOBS_LOCK:
        jobs = sorted(_JOBS.values(), key=lambda j: j.created_at, reverse=True)
    return [
        {
            "id": j.id,
            "status": j.status,
            "host": j.params.host,
            "role": j.params.role,
            "created_at": j.created_at.isoformat(),
        }
        for j in jobs
    ]


async def run_job(job: ProvisioningJob) -> None:
    job.status = "running"
    try:
        await asyncio.to_thread(_execute, job)
        job.status = "error" if job.had_error else "success"
    except Exception as exc:  # noqa: BLE001
        job.status = "error"
        job.error = str(exc)
        job.log(f"Job failed: {exc}", "error")
    finally:
        job.finished_at = datetime.utcnow()
        job.log(f"Job finished with status: {job.status}", "step")
        try:
            await _persist_proxy_server(job)
        except Exception as exc:  # noqa: BLE001
            job.log(f"Could not persist proxy-server record: {exc}", "info")


async def _persist_proxy_server(job: ProvisioningJob) -> None:
    """After a successful WARP/proxy install, upsert a ProxyServer row so the
    admin can later change the upstream proxy from the Servers page."""
    p = job.params
    warp = job.results.get("warp") if isinstance(job.results, dict) else None
    if not p.install_warp or not warp or warp.get("status") != "success":
        return

    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models import ProxyServer
    from app.provisioning.vault import encrypt

    mode = warp.get("mode") or (p.warp_mode or "proxy")
    if mode == "warp":
        proxy_ip, proxy_port, proxy_type = "127.0.0.1", "40000", "socks5"
        proxy_user, proxy_pass = "", ""
    else:
        proxy_ip, proxy_port = p.warp_proxy_ip.strip(), p.warp_proxy_port.strip()
        proxy_type = p.warp_proxy_type or "socks5"
        proxy_user, proxy_pass = p.warp_proxy_user or "", p.warp_proxy_pass or ""

    async with AsyncSessionLocal() as s:
        existing = (
            await s.execute(select(ProxyServer).where(ProxyServer.host == p.host))
        ).scalar_one_or_none()
        row = existing or ProxyServer(host=p.host)
        row.ssh_port = p.ssh_port
        row.ssh_user = p.username
        row.ssh_password_enc = encrypt(p.password)
        row.mode = mode
        row.wg_port = str(warp.get("wgPort") or "")
        row.api_port = str(warp.get("apiPort") or "")
        row.api_key = warp.get("apiKey") or ""
        row.admin_path = warp.get("adminPath") or ""
        row.server_public_key = warp.get("serverPublicKey") or ""
        row.proxy_ip = proxy_ip
        row.proxy_port = proxy_port
        row.proxy_type = proxy_type
        row.proxy_user = proxy_user
        row.proxy_password_enc = encrypt(proxy_pass)
        row.proxy_status = warp.get("proxyStatus") or "unknown"
        if not existing:
            s.add(row)
        await s.commit()
    job.log(f"Recorded proxy-server {p.host} ({mode} mode) for later management.", "info")


# -- execution (runs in a worker thread) -----------------------------------
def _execute(job: ProvisioningJob) -> None:
    p = job.params
    job.log(f"Connecting to {p.host}:{p.ssh_port} as {p.username} ...", "step")
    try:
        ssh = SSHSession(p.host, p.username, p.password, p.ssh_port)
        ssh.connect()
    except SSHError as exc:
        job.error = str(exc)
        job.had_error = True
        job.log(str(exc), "error")
        return

    try:
        job.log("SSH connection established.", "info")
        arch, os_id = _detect_target(ssh, job)
        job.results["target"] = {"arch": arch, "os": os_id, "host": p.host}

        # Always prepare the server first: refresh package lists, optionally
        # upgrade, and install python/venv/curl prerequisites. This must run
        # before any component so apt-based installers have what they need.
        _step(
            job,
            "prepare",
            "Prepare server (update & prerequisites)",
            lambda: _prepare_server(ssh, job, os_id, p.system_upgrade),
        )

        # Detect the target's Python AFTER prepare so it reflects the installed
        # interpreter (used to pick the matching offline bundle).
        py = _detect_python(ssh, job)
        job.results["target"]["python"] = py

        if p.install_node:
            _step(job, "node", "Install Smite node", lambda: _install_node(ssh, job, arch, py))
        if p.install_xui:
            _step(job, "xui", "Install 3x-ui panel", lambda: _install_xui(ssh, job))
        if p.install_wireguard:
            _step(job, "wireguard", "Install WireGuard", lambda: _install_wireguard(ssh, job))
        if p.install_openvpn:
            _step(job, "openvpn", "Install OpenVPN", lambda: _install_openvpn(ssh, job))
        if p.install_warp:
            _step(job, "warp", "Install WARP (WireGuard + proxy egress)", lambda: _install_warp(ssh, job))
    finally:
        ssh.close()
        job.log("SSH connection closed.", "info")


def _step(job: ProvisioningJob, name: str, label: str, fn) -> None:
    job.log(f"===== {label} =====", "step")
    data = job.results.setdefault(name, {})
    data["status"] = "running"
    try:
        result = fn()
        if isinstance(result, dict):
            data.update(result)
        data["status"] = "success"
        job.log(f"{label}: completed successfully.", "step")
    except Exception as exc:  # noqa: BLE001
        data["status"] = "error"
        data["error"] = str(exc)
        job.had_error = True
        job.log(f"{label} FAILED: {exc}", "error")


def _run(job: ProvisioningJob, ssh: SSHSession, command: str, timeout: float = 1800.0, allow_fail: bool = False) -> tuple[int, str]:
    code, out = ssh.run(command, timeout=timeout, on_output=lambda line: job.log(line, "output"))
    if code != 0 and not allow_fail:
        raise ProvisioningError(f"remote command exited with code {code}")
    return code, out


def _detect_target(ssh: SSHSession, job: ProvisioningJob) -> tuple[str, str]:
    job.log("Detecting target architecture and OS ...", "info")
    _, arch_raw = ssh.run("uname -m")
    arch_raw = arch_raw.strip()
    if arch_raw in ("x86_64", "amd64"):
        arch = "amd64"
    elif arch_raw in ("aarch64", "arm64"):
        arch = "arm64"
    else:
        arch = arch_raw or "amd64"
    _, os_id = ssh.run(". /etc/os-release 2>/dev/null && echo $ID || echo unknown")
    os_id = os_id.strip() or "unknown"
    job.log(f"Target: arch={arch} os={os_id}", "info")
    return arch, os_id


def _detect_python(ssh: SSHSession, job: ProvisioningJob) -> str:
    """Return the target's default python3 minor version, e.g. "3.10"."""
    _, out = ssh.run(
        "python3 -c 'import sys;print(\"%d.%d\"%sys.version_info[:2])' 2>/dev/null || true"
    )
    py = out.strip().splitlines()[-1].strip() if out.strip() else ""
    if py.count(".") == 1 and py.replace(".", "").isdigit():
        job.log(f"Target Python: {py}", "info")
        return py
    job.log("Target Python: not detected (python3 missing?)", "info")
    return ""


# Build one prepare script and push it (avoids brittle inline quoting over SSH).
_PREPARE_SCRIPT_TEMPLATE = """#!/bin/bash
set +e
export DEBIAN_FRONTEND=noninteractive
# Avoid interactive service-restart prompts on Ubuntu 22.04+.
export NEEDRESTART_MODE=a
export NEEDRESTART_SUSPEND=1

if ! command -v apt-get >/dev/null 2>&1; then
    echo "apt-get not found; skipping system update (non-Debian/Ubuntu OS)."
    echo "Make sure python3, python3-venv, python3-pip, curl and tar are installed."
    exit 0
fi

echo "Updating package lists (apt-get update)..."
apt-get update -y || echo "WARNING: apt-get update reported errors (continuing)."

__UPGRADE_BLOCK__

echo "Installing prerequisites (python3, venv, pip, curl, tar)..."
apt-get install -y python3 python3-venv python3-pip python3-dev \\
    curl ca-certificates tar gzip git || \\
    echo "WARNING: some prerequisites failed to install (continuing)."

PYVER="$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || true)"
if [ -n "$PYVER" ]; then
    # The version-specific venv package is what actually ships ensurepip on
    # Ubuntu/Debian; install it but never fail if it is not in the repo.
    apt-get install -y "python${PYVER}-venv" 2>/dev/null || \\
        echo "Note: python${PYVER}-venv not available; relying on python3-venv."
fi

if python3 -c 'import ensurepip, venv' >/dev/null 2>&1; then
    echo "Python venv/ensurepip ready (python ${PYVER:-unknown})."
else
    echo "WARNING: python venv/ensurepip still unavailable; node install may fail."
fi
echo "Server preparation finished."
"""

_UPGRADE_BLOCK = """echo "Upgrading installed packages (apt-get upgrade; this can take a few minutes)..."
apt-get -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" upgrade || \\
    echo "WARNING: apt-get upgrade reported errors (continuing)."
"""


def _prepare_server(ssh: SSHSession, job: ProvisioningJob, os_id: str, do_upgrade: bool) -> Dict[str, Any]:
    """Update the server and install python/venv prerequisites before install."""
    script = _PREPARE_SCRIPT_TEMPLATE.replace(
        "__UPGRADE_BLOCK__", _UPGRADE_BLOCK if do_upgrade else 'echo "Skipping apt-get upgrade (disabled)."'
    )
    ssh.put_text(script, REMOTE_PREP_SCRIPT, mode=0o755)
    # Generous timeout: a full `apt-get upgrade` on a stale server is slow.
    _run(job, ssh, f"bash {REMOTE_PREP_SCRIPT}", timeout=2700, allow_fail=True)
    return {"upgraded": bool(do_upgrade), "os": os_id}


def _select_bundle(
    candidates: List[str], explicit: Optional[str], arch: str, py: str
) -> Optional[str]:
    """Pick the offline bundle matching the target's arch + Python version.

    Binary wheels in the bundle (uvloop, psutil, pydantic-core, ...) are built
    for one CPython minor version only, so the bundle's Python MUST match the
    target's python3. Returns the chosen path, or None if nothing matches.
    """
    pool: List[str] = []
    if explicit:
        pool.append(explicit)
    for c in candidates:
        if c not in pool:
            pool.append(c)
    if not pool:
        return None

    arch_frag = f"-{arch}-"
    pytag = ("py" + py.replace(".", "")) if py else ""

    if pytag:
        for c in pool:
            name = Path(c).name
            if arch_frag in name and name.endswith(f"-{pytag}.tar.gz"):
                return c
        return None  # no python-matching bundle => caller raises a clear error

    # Python version unknown: best-effort arch match (may still fail at pip).
    for c in pool:
        if arch_frag in Path(c).name:
            return c
    return pool[0]


def _read_script(name: str) -> str:
    path = SCRIPTS_DIR / name
    return path.read_text(encoding="utf-8")


def _make_bundle(src_dir: Path) -> str:
    """Tar+gzip a bundled installer tree into a temp file; return its path.

    node_modules/.git are already absent from the shipped tree, but exclude
    them defensively so a dev checkout never bloats the upload.
    """
    import tarfile
    import tempfile

    if not src_dir.is_dir():
        raise ProvisioningError(f"Installer bundle directory missing: {src_dir}")
    fd, tmp = tempfile.mkstemp(prefix="smite-bundle-", suffix=".tar.gz")
    os.close(fd)

    def _filter(ti: "tarfile.TarInfo"):
        parts = set(ti.name.split("/"))
        if parts & {"node_modules", ".git", "_ssh"}:
            return None
        if ti.name.endswith(".log"):
            return None
        return ti

    with tarfile.open(tmp, "w:gz") as tf:
        # arcname="." so the archive extracts the tree contents directly into
        # the target dir (install.sh sits at the root of the extracted dir).
        tf.add(str(src_dir), arcname=".", filter=_filter)
    return tmp


def _fetch_and_push_bundle(job: ProvisioningJob, ssh: SSHSession, url: str, asset: str) -> None:
    """Download the release bundle on the panel and upload it to the target.

    Fallback for targets whose own connectivity cannot sustain a ~100 MB
    download. The panel usually sits on a healthy link, so pulling once here and
    pushing over the existing SSH channel avoids the target's bad path entirely.
    """
    import shutil
    import tarfile
    import tempfile
    import urllib.request

    fd, tmp = tempfile.mkstemp(prefix="smite-release-", suffix=".tar.gz")
    os.close(fd)
    try:
        job.log(f"Panel is downloading {asset} ...", "info")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "smite-panel"})
            with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as out:
                shutil.copyfileobj(resp, out, 1024 * 1024)
        except Exception as exc:  # noqa: BLE001
            raise ProvisioningError(
                f"Neither the target nor the panel could download {asset} ({exc}). "
                f"Upload the offline bundle in the panel (Install Node -> Artifacts) and retry."
            ) from exc

        size = os.path.getsize(tmp)
        try:
            with tarfile.open(tmp, "r:gz") as tf:
                if tf.next() is None:
                    raise ValueError("empty tar archive")
        except Exception as exc:  # noqa: BLE001
            raise ProvisioningError(
                f"Panel downloaded {asset} but the archive is corrupt or truncated: {exc}"
            ) from exc

        job.log(f"Panel downloaded {asset} ({size} bytes); uploading to the target ...", "info")
        try:
            ssh.put_file(tmp, REMOTE_BUNDLE)
        except SSHError as exc:
            raise ProvisioningError(
                f"Could not upload the bundle to the target: {exc}. The target's network "
                f"appears unable to receive large transfers; check the server before retrying."
            ) from exc
        job.log("Bundle uploaded to the target.", "info")
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


# -- step: node --------------------------------------------------------------
def _install_node(ssh: SSHSession, job: ProvisioningJob, arch: str, py: str) -> Dict[str, Any]:
    p = job.params
    if not p.ca_pem.strip():
        raise ProvisioningError("Panel CA certificate is empty; cannot enroll node.")
    if not p.panel_host:
        raise ProvisioningError("Panel host is required to register the node.")

    # Pick the offline bundle whose wheels match the target's arch + Python.
    bundle = _select_bundle(p.bundle_candidates, p.bundle_path, arch, py)

    # An Iran target has no internet, so a matching offline bundle is mandatory.
    if not bundle and p.role == "iran":
        have = ", ".join(sorted({Path(c).name for c in (p.bundle_candidates or [])})) or "none"
        pyhint = f"py{py.replace('.', '')}" if py else "<server-python>"
        raise ProvisioningError(
            f"No offline bundle matches this server (arch={arch}, Python={py or 'unknown'}). "
            f"The bundle's Python must match the server because its wheels are compiled per "
            f"Python version. Upload smite-offline-{arch}-...-{pyhint}.tar.gz and retry. "
            f"Uploaded bundles: {have}."
        )

    job.log("Uploading panel CA certificate ...", "info")
    ssh.put_text(p.ca_pem, REMOTE_CA, mode=0o600)

    env = (
        f"SMITE_NONINTERACTIVE=1 "
        f"PANEL_ADDRESS={shlex.quote(p.panel_host)} "
        f"PANEL_API_PORT={shlex.quote(str(p.panel_api_port))} "
        f"NODE_API_PORT=8888 "
        f"NODE_NAME={shlex.quote(p.node_name)} "
        f"NODE_ROLE={shlex.quote(p.role)} "
        f"PANEL_CA_FILE={REMOTE_CA}"
    )

    if bundle:
        if p.bundle_path and Path(bundle) != Path(p.bundle_path):
            job.log(
                f"Selected bundle {Path(bundle).name} matching the server "
                f"(arch={arch}, Python={py or 'unknown'}) instead of the picked "
                f"{Path(p.bundle_path).name}.",
                "info",
            )
        job.log(f"Uploading offline bundle ({Path(bundle).name}) ...", "info")
        size = ssh.put_file(bundle, REMOTE_BUNDLE)
        job.log(f"Bundle uploaded ({size} bytes). Extracting ...", "info")
        _run(
            job,
            ssh,
            f"rm -rf {REMOTE_BUNDLE_DIR} && mkdir -p {REMOTE_BUNDLE_DIR} && "
            f"tar -xzf {REMOTE_BUNDLE} -C {REMOTE_BUNDLE_DIR} --strip-components=1",
            timeout=600,
        )
        job.log("Running native node installer (this may take a few minutes) ...", "info")
        _run(
            job,
            ssh,
            f"cd {REMOTE_BUNDLE_DIR} && {env} bash scripts/install-node-native.sh --yes",
            timeout=2400,
        )
        method = "offline-bundle (native)"
    else:
        # Foreign target with internet but no uploaded bundle: download the
        # matching offline bundle from the GitHub release ON the target and run
        # the NATIVE installer. Foreign nodes stay native (panel-updatable)
        # instead of becoming Docker containers the panel updater cannot touch.
        oslabel = _PY_OSLABEL.get(py, "ubuntu24.04-py312")
        asset = f"smite-offline-{arch}-{oslabel}.tar.gz"
        url = f"https://github.com/{PROVISION_REPO}/releases/latest/download/{asset}"
        job.log(
            f"No uploaded bundle; the target will download {asset} from GitHub and install natively.",
            "info",
        )
        # Remove any previous Docker-based node so the native install can take
        # over the API port (lets re-provisioning convert Docker -> native).
        _run(job, ssh, "(docker rm -f smite-node 2>/dev/null || true); exit 0", timeout=120)

        # fetch-bundle.sh resumes and falls back to chunked range requests; a
        # plain curl gives up on the first mid-transfer reset.
        ssh.put_text(_read_script("fetch-bundle.sh"), REMOTE_FETCH_SCRIPT, mode=0o755)
        code, _ = _run(
            job,
            ssh,
            f"bash {REMOTE_FETCH_SCRIPT} {shlex.quote(url)} {REMOTE_BUNDLE}",
            timeout=1800,
            allow_fail=True,
        )
        if code != 0:
            # The target cannot pull 100 MB reliably, but the panel usually can.
            # Download it here and push it over the SSH channel we already have.
            job.log(
                "Target could not download the bundle; retrying via the panel "
                "(panel downloads, then uploads over SSH) ...",
                "info",
            )
            _fetch_and_push_bundle(job, ssh, url, asset)
        _run(
            job,
            ssh,
            f"set -e; rm -rf {REMOTE_BUNDLE_DIR} && mkdir -p {REMOTE_BUNDLE_DIR} && "
            f"tar -xzf {REMOTE_BUNDLE} -C {REMOTE_BUNDLE_DIR} --strip-components=1",
            timeout=600,
        )
        job.log("Running native node installer (this may take a few minutes) ...", "info")
        _run(
            job,
            ssh,
            f"cd {REMOTE_BUNDLE_DIR} && {env} bash scripts/install-node-native.sh --yes",
            timeout=2400,
        )
        method = "github-release (native)"

    return {
        "method": method,
        "role": p.role,
        "node_name": p.node_name,
        "node_api_port": 8888,
        "panel_address": f"{p.panel_host}:{p.panel_api_port}",
        "note": "Node registers itself with the panel a few seconds after start; "
        "check the Nodes/Servers page for the new entry.",
    }


# -- step: 3x-ui -------------------------------------------------------------
def _install_xui(ssh: SSHSession, job: ProvisioningJob) -> Dict[str, Any]:
    p = job.params
    job.log("Uploading 3x-ui installer script ...", "info")
    ssh.put_text(_read_script("install-3xui.sh"), REMOTE_XUI_SCRIPT, mode=0o755)

    env_parts = [f"XUI_VERSION={shlex.quote(p.xui_version)}"]
    if p.role == "iran" and not p.xui_tarball_path:
        raise ProvisioningError(
            "Iran 3x-ui install requires an uploaded x-ui release tarball (panel has no internet)."
        )
    if p.xui_tarball_path:
        job.log(f"Uploading 3x-ui tarball ({Path(p.xui_tarball_path).name}) ...", "info")
        ssh.put_file(p.xui_tarball_path, REMOTE_XUI_TARBALL)
        env_parts.append(f"XUI_TARBALL={REMOTE_XUI_TARBALL}")
    if p.xui_port:
        env_parts.append(f"XUI_PORT={shlex.quote(str(p.xui_port))}")
    if p.xui_username:
        env_parts.append(f"XUI_USERNAME={shlex.quote(p.xui_username)}")
    if p.xui_password:
        env_parts.append(f"XUI_PASSWORD={shlex.quote(p.xui_password)}")

    job.log("Running 3x-ui installer ...", "info")
    _, out = _run(job, ssh, f"{' '.join(env_parts)} bash {REMOTE_XUI_SCRIPT}", timeout=2400)

    data = _parse_result_marker(out, "===SMITE_XUI_RESULT===")
    if not data:
        raise ProvisioningError("3x-ui installed but the result could not be parsed.")

    port = data.get("port", "")
    web_path = data.get("webBasePath", "")
    result = {
        "version": data.get("version", p.xui_version),
        "username": data.get("username", ""),
        "password": data.get("password", ""),
        "port": port,
        "webBasePath": web_path,
        "apiToken": data.get("apiToken", ""),
        "panelUrl": f"http://{p.host}:{port}/{web_path}" if port else "",
        "note": "Configure SSL inside the 3x-ui panel if you need HTTPS. "
        "Make sure the panel port is open in your firewall.",
    }
    return result


# -- step: WireGuard ---------------------------------------------------------
def _install_wireguard(ssh: SSHSession, job: ProvisioningJob) -> Dict[str, Any]:
    p = job.params
    if p.role != "foreign":
        raise ProvisioningError("WireGuard installation is only supported on foreign servers.")

    job.log("Uploading WireGuard installer script ...", "info")
    ssh.put_text(_read_script("install-wireguard.sh"), REMOTE_WG_SCRIPT, mode=0o755)

    job.log("Running WireGuard installer (this may take a few minutes) ...", "info")
    _, out = _run(job, ssh, f"bash {REMOTE_WG_SCRIPT}", timeout=2400)

    data = _parse_result_marker(out, "===SMITE_WG_RESULT===")
    if not data:
        raise ProvisioningError("WireGuard installed but the result could not be parsed.")

    wg_port = data.get("wgPort", "")
    api_port = data.get("apiPort", "4000")
    client_config = ""
    b64 = data.get("clientConfigB64", "")
    if b64:
        try:
            import base64

            client_config = base64.b64decode(b64).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            client_config = ""

    api_key = data.get("apiKey", "")
    return {
        "wgPort": wg_port,
        "serverPublicKey": data.get("serverPublicKey", ""),
        "serverEndpoint": f"{p.host}:{wg_port}" if wg_port else "",
        "apiPort": api_port,
        "apiBaseUrl": f"http://{p.host}:{api_port}",
        "apiEndpoints": "GET /create?publicKey=, /remove?publicKey=, /list, /check?publicKey=",
        "apiKey": api_key,
        "apiKeyNote": (
            "Send this key with every management API request (as required by wvpn). "
            "Keep it secret and restrict the management port with a firewall."
            if api_key
            else "Could not read the wvpn API key from /etc/wvpn/wvpn.json on the server. "
                 "Check the server's wvpn config and restrict the management port with a firewall."
        ),
        "defaultClientConfig": client_config,
        "note": "Open the WireGuard UDP port and the management API port in your firewall.",
    }


# -- step: OpenVPN -----------------------------------------------------------
def _install_openvpn(ssh: SSHSession, job: ProvisioningJob) -> Dict[str, Any]:
    p = job.params
    if p.role != "foreign":
        raise ProvisioningError("OpenVPN installation is only supported on foreign servers.")

    job.log("Packaging OpenVPN installer bundle ...", "info")
    bundle = _make_bundle(OPENVPN_BUNDLE_DIR)
    try:
        job.log(f"Uploading OpenVPN installer bundle ({Path(bundle).name}) ...", "info")
        size = ssh.put_file(bundle, REMOTE_OVPN_BUNDLE)
        job.log(f"Bundle uploaded ({size} bytes).", "info")
    finally:
        try:
            os.unlink(bundle)
        except OSError:
            pass

    job.log("Uploading OpenVPN installer script ...", "info")
    ssh.put_text(_read_script("install-openvpn.sh"), REMOTE_OVPN_SCRIPT, mode=0o755)

    env_parts = [
        f"OVPN_BUNDLE={REMOTE_OVPN_BUNDLE}",
        f"OVPN_VPN_PORT={shlex.quote(str(p.ovpn_vpn_port))}",
        f"OVPN_PROTOCOL={shlex.quote(p.ovpn_protocol)}",
        f"OVPN_PORT={shlex.quote(str(p.ovpn_panel_port))}",
    ]
    if p.ovpn_default_limit_gb is not None:
        env_parts.append(f"OVPN_DEFAULT_LIMIT_GB={shlex.quote(str(p.ovpn_default_limit_gb))}")

    job.log("Running OpenVPN installer (this may take a few minutes) ...", "info")
    _, out = _run(job, ssh, f"{' '.join(env_parts)} bash {REMOTE_OVPN_SCRIPT}", timeout=2400)

    data = _parse_result_marker(out, "===SMITE_OVPN_RESULT===")
    if not data:
        raise ProvisioningError("OpenVPN installed but the result could not be parsed.")

    vpn_port = data.get("vpnPort", "")
    vpn_proto = data.get("vpnProto", "")
    panel_port = data.get("panelPort", "4000")
    return {
        "serverIp": data.get("serverIp", p.host),
        "vpnProto": vpn_proto,
        "vpnPort": vpn_port,
        "vpnEndpoint": f"{vpn_proto}://{p.host}:{vpn_port}" if vpn_port else "",
        "panelPort": panel_port,
        "panelUrl": data.get("panelUrl", ""),
        "adminPath": data.get("adminPath", ""),
        "adminPassword": data.get("adminPassword", ""),
        "adminPasswordReset": data.get("adminPasswordReset", "false") == "true",
        "adminPasswordNote": (
            "The server already had OpenVPN installed, so the admin panel password was "
            "reset to this new value (the old one no longer works)."
            if data.get("adminPasswordReset") == "true"
            else ""
        ),
        "apiKey": data.get("apiKey", ""),
        "apiBaseUrl": f"http://{p.host}:{panel_port}",
        "apiEndpoints": "GET /create?name=&dataLimitGB=&expiresInDays=, /info, /update, /disable, /enable, /remove, /list (header X-API-Key)",
        "apiKeyNote": (
            "Send this key with every management API request (header X-API-Key or ?apiKey=). "
            "Keep it secret and restrict the panel port with a firewall."
            if data.get("apiKey")
            else "Could not read the API key from /etc/ovpn/ovpn.json on the server. "
                 "Check the server and restrict the panel port with a firewall."
        ),
        "note": "Open the OpenVPN port and the panel/API port in your firewall. "
        "OpenVPN .ovpn configs are ~3KB (too large for a QR); use the .ovpn download in the panel.",
    }


# -- step: WARP (wginstaller-proxy) ------------------------------------------
def _install_warp(ssh: SSHSession, job: ProvisioningJob) -> Dict[str, Any]:
    p = job.params
    if p.role != "foreign":
        raise ProvisioningError("WARP installation is only supported on foreign servers.")

    job.log("Packaging WARP (wginstaller-proxy) installer bundle ...", "info")
    bundle = _make_bundle(WARP_BUNDLE_DIR)
    try:
        job.log(f"Uploading WARP installer bundle ({Path(bundle).name}) ...", "info")
        size = ssh.put_file(bundle, REMOTE_WARP_BUNDLE)
        job.log(f"Bundle uploaded ({size} bytes).", "info")
    finally:
        try:
            os.unlink(bundle)
        except OSError:
            pass

    job.log("Uploading WARP installer script ...", "info")
    ssh.put_text(_read_script("install-warp.sh"), REMOTE_WARP_SCRIPT, mode=0o755)

    mode = "warp" if p.warp_mode == "warp" else "proxy"
    env_parts = [
        f"WARP_BUNDLE={REMOTE_WARP_BUNDLE}",
        f"WVPN_PORT={shlex.quote(str(p.warp_panel_port))}",
        f"WARP_MODE={shlex.quote(mode)}",
    ]
    if mode == "warp":
        job.log(
            "WARP mode: Cloudflare WARP will be installed on the server and the client "
            "egress IP will be a Cloudflare WARP IP.",
            "info",
        )
    else:
        proxy_configured = bool(p.warp_proxy_ip.strip() and p.warp_proxy_port.strip())
        if not proxy_configured:
            raise ProvisioningError(
                "Proxy mode requires a proxy IP and port. Provide them or choose WARP mode."
            )
        env_parts.append(f"PROXY_IP={shlex.quote(p.warp_proxy_ip.strip())}")
        env_parts.append(f"PROXY_PORT={shlex.quote(p.warp_proxy_port.strip())}")
        env_parts.append(f"PROXY_TYPE={shlex.quote(p.warp_proxy_type or 'socks5')}")
        if p.warp_proxy_user:
            env_parts.append(f"PROXY_USER={shlex.quote(p.warp_proxy_user)}")
        if p.warp_proxy_pass:
            env_parts.append(f"PROXY_PASS={shlex.quote(p.warp_proxy_pass)}")
        job.log("Proxy mode: the client egress IP will be the upstream proxy IP.", "info")

    job.log("Running WARP installer (this may take a few minutes) ...", "info")
    _, out = _run(job, ssh, f"{' '.join(env_parts)} bash {REMOTE_WARP_SCRIPT}", timeout=2400)

    data = _parse_result_marker(out, "===SMITE_WARP_RESULT===")
    if not data:
        raise ProvisioningError("WARP installed but the result could not be parsed.")

    wg_port = data.get("wgPort", "")
    api_port = data.get("apiPort", "4000")
    api_key = data.get("apiKey", "")
    mode = data.get("mode", p.warp_mode or "proxy")
    proxy_enabled = data.get("proxyEnabled", "false") == "true"
    proxy_status = data.get("proxyStatus", "disabled")
    proxy_endpoint = data.get("proxyEndpoint", "")
    if mode == "warp":
        proxy_note = (
            "WARP mode: client TCP traffic exits through Cloudflare WARP. redsocks service is "
            f"{proxy_status}."
            if proxy_status == "active"
            else "WARP mode configured but the redsocks egress service is not active; "
                 "check `systemctl status wvpn-redsocks` and `warp-cli status` on the server."
        )
    elif proxy_enabled:
        proxy_note = (
            "Proxy mode: client TCP traffic exits from the upstream proxy IP. redsocks service is "
            f"{proxy_status}."
            if proxy_status == "active"
            else "Upstream proxy is configured but the redsocks egress service is not active; "
                 "check `systemctl status wvpn-redsocks` and the proxy credentials on the server."
        )
    else:
        proxy_note = (
            "No upstream proxy configured — plain WireGuard (client egress IP = server IP)."
        )
    return {
        "mode": mode,
        "wgPort": wg_port,
        "serverPublicKey": data.get("serverPublicKey", ""),
        "serverEndpoint": f"{p.host}:{wg_port}" if wg_port else "",
        "apiPort": api_port,
        "apiBaseUrl": f"http://{p.host}:{api_port}",
        "apiEndpoints": "GET /create?publicKey=, /remove?publicKey=, /list, /check?publicKey=",
        "apiKey": api_key,
        "adminPath": data.get("adminPath", ""),
        "apiKeyNote": (
            "Send this key with every management API request (as required by wvpn). "
            "Keep it secret and restrict the management port with a firewall."
            if api_key
            else "Could not read the wvpn API key from /etc/wvpn/wvpn.json on the server. "
                 "Check the server's wvpn config and restrict the management port with a firewall."
        ),
        "proxyEnabled": proxy_enabled,
        "proxyType": data.get("proxyType", ""),
        "proxyEndpoint": proxy_endpoint if proxy_enabled else "",
        "proxyStatus": proxy_status,
        "proxyNote": proxy_note,
        "note": "Open the WireGuard UDP port and the management API port in your firewall.",
    }


def apply_proxy_update(
    host: str,
    ssh_port: int,
    username: str,
    password: str,
    mode: str,
    proxy_ip: str = "",
    proxy_port: str = "",
    proxy_type: str = "socks5",
    proxy_user: str = "",
    proxy_pass: str = "",
) -> Dict[str, Any]:
    """Change the egress proxy on an already-installed WARP/proxy server.

    Uploads update-proxy.sh, runs it (rewrites /etc/wvpn-proxy.env, re-applies
    redsocks + iptables, restarts wvpn-redsocks). Blocking — call via
    ``asyncio.to_thread``. Returns the parsed result dict.
    """
    log_lines: List[str] = []

    def _sink(line: str) -> None:
        log_lines.append(line)

    ssh = SSHSession(host, username, password, ssh_port)
    try:
        ssh.connect()
    except SSHError as exc:
        raise ProvisioningError(str(exc)) from exc
    try:
        ssh.put_text(_read_script("update-proxy.sh"), REMOTE_UPDATE_PROXY_SCRIPT, mode=0o755)
        env_parts = [f"WARP_MODE={shlex.quote('warp' if mode == 'warp' else 'proxy')}"]
        if mode != "warp":
            if not (proxy_ip.strip() and str(proxy_port).strip()):
                raise ProvisioningError("Proxy mode requires a proxy IP and port.")
            env_parts.append(f"PROXY_IP={shlex.quote(proxy_ip.strip())}")
            env_parts.append(f"PROXY_PORT={shlex.quote(str(proxy_port).strip())}")
            env_parts.append(f"PROXY_TYPE={shlex.quote(proxy_type or 'socks5')}")
            if proxy_user:
                env_parts.append(f"PROXY_USER={shlex.quote(proxy_user)}")
            if proxy_pass:
                env_parts.append(f"PROXY_PASS={shlex.quote(proxy_pass)}")
        code, out = ssh.run(
            f"{' '.join(env_parts)} bash {REMOTE_UPDATE_PROXY_SCRIPT}",
            timeout=1200,
            on_output=_sink,
        )
        if code != 0:
            raise ProvisioningError(f"update-proxy exited with code {code}")
        data = _parse_result_marker(out, "===SMITE_PROXY_UPDATE_RESULT===")
        if not data:
            raise ProvisioningError("Proxy updated but the result could not be parsed.")
        data["logs"] = log_lines[-50:]
        return data
    finally:
        ssh.close()


def _parse_result_marker(output: str, marker: str) -> Optional[Dict[str, Any]]:
    idx = output.rfind(marker)
    if idx == -1:
        return None
    tail = output[idx + len(marker):].strip()
    # The JSON payload is the first line after the marker.
    line = tail.splitlines()[0] if tail else ""
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None
