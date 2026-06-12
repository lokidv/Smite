"""Remote provisioning orchestration.

A provisioning request becomes an in-memory :class:`ProvisioningJob` that runs
in a background thread (paramiko is blocking). Each selected step (Smite node,
3x-ui, WireGuard) runs independently so one failing does not abort the others.
Live log lines and structured results are exposed for the UI to poll.
"""
from __future__ import annotations

import asyncio
import json
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
    xui_version: str = "v2.9.4"
    xui_port: Optional[int] = None
    xui_username: Optional[str] = None
    xui_password: Optional[str] = None
    bundle_path: Optional[str] = None
    xui_tarball_path: Optional[str] = None
    ca_pem: str = ""


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

        if p.install_node:
            _step(job, "node", "Install Smite node", lambda: _install_node(ssh, job, arch))
        if p.install_xui:
            _step(job, "xui", "Install 3x-ui panel", lambda: _install_xui(ssh, job))
        if p.install_wireguard:
            _step(job, "wireguard", "Install WireGuard", lambda: _install_wireguard(ssh, job))
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


def _read_script(name: str) -> str:
    path = SCRIPTS_DIR / name
    return path.read_text(encoding="utf-8")


# -- step: node --------------------------------------------------------------
def _install_node(ssh: SSHSession, job: ProvisioningJob, arch: str) -> Dict[str, Any]:
    p = job.params
    if not p.ca_pem.strip():
        raise ProvisioningError("Panel CA certificate is empty; cannot enroll node.")
    if not p.panel_host:
        raise ProvisioningError("Panel host is required to register the node.")

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

    use_bundle = bool(p.bundle_path)
    if p.role == "iran" and not use_bundle:
        raise ProvisioningError(
            "Iran node install requires an uploaded Smite offline bundle (panel has no internet)."
        )

    if use_bundle:
        job.log(f"Uploading offline bundle ({Path(p.bundle_path).name}) ...", "info")
        size = ssh.put_file(p.bundle_path, REMOTE_BUNDLE)
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
        # Foreign target with internet: push the installer; it fetches node
        # source / Docker image from GitHub on the target itself.
        job.log("Uploading node installer script ...", "info")
        ssh.put_text(_read_script("smite-node.sh"), REMOTE_SMITE_NODE, mode=0o755)
        job.log("Running Docker node installer (fetches from GitHub on the target) ...", "info")
        _run(job, ssh, f"{env} bash {REMOTE_SMITE_NODE}", timeout=2400)
        method = "docker (github)"

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

    return {
        "wgPort": wg_port,
        "serverPublicKey": data.get("serverPublicKey", ""),
        "serverEndpoint": f"{p.host}:{wg_port}" if wg_port else "",
        "apiPort": api_port,
        "apiBaseUrl": f"http://{p.host}:{api_port}",
        "apiEndpoints": "GET /create?publicKey=, /remove?publicKey=, /list, /check?publicKey=",
        "apiKey": "",
        "apiKeyNote": "wvpn management API has no API key (open on the management port). "
        "Restrict access with a firewall.",
        "defaultClientConfig": client_config,
        "note": "Open the WireGuard UDP port and the management API port in your firewall.",
    }


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
