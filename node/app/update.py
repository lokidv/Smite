"""Self-update helpers for the node agent.

The foreign node (free internet) acts as the GitHub relay:
  - fetch_releases / download_asset talk to api.github.com directly.
The iran nodes (no GitHub) receive the bundle bytes pushed by the panel
(upload endpoint) and both kinds of nodes apply it the same way:
extract + run the bundled non-interactive installer in a *separate* systemd
transient unit (systemd-run), because `systemctl restart smite-node` from
inside our own cgroup would kill the installer mid-run.
"""
import hashlib
import logging
import os
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

UPDATE_DIR = Path(os.environ.get("SMITE_UPDATE_DIR", "/tmp/smite-update"))
GITHUB_API = "https://api.github.com"
DEFAULT_REPO = os.environ.get("SMITE_UPDATE_REPO", "lokidv/Smite")
UPDATE_LOG = "/var/log/smite-node-update.log"


def _safe_extractall(tar: tarfile.TarFile, dest: Path) -> None:
    """Extract a tarball, rejecting members/links that escape dest.

    Bundles are extracted and then a bundled installer is run as root, so an
    unchecked extractall is an arbitrary-file-write -> RCE vector.
    """
    dest_r = dest.resolve()
    base = str(dest_r) + os.sep
    for member in tar.getmembers():
        target = (dest_r / member.name).resolve()
        if target != dest_r and not str(target).startswith(base):
            raise RuntimeError(f"Refusing unsafe path in update bundle: {member.name!r}")
        if member.issym() or member.islnk():
            link_target = (target.parent / member.linkname).resolve()
            if link_target != dest_r and not str(link_target).startswith(base):
                raise RuntimeError(f"Refusing unsafe link in update bundle: {member.name!r}")
    tar.extractall(dest_r)


def _headers() -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "smite-node-updater",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def fetch_releases(repo: str = "", limit: int = 10) -> List[Dict[str, Any]]:
    """List GitHub releases (foreign node only - needs internet)."""
    repo = repo or DEFAULT_REPO
    url = f"{GITHUB_API}/repos/{repo}/releases?per_page={max(1, min(limit, 30))}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0), follow_redirects=True) as client:
        response = await client.get(url, headers=_headers())
        response.raise_for_status()
        releases = response.json()

    trimmed = []
    for release in releases:
        trimmed.append({
            "tag": release.get("tag_name"),
            "name": release.get("name") or release.get("tag_name"),
            "published_at": release.get("published_at"),
            "prerelease": release.get("prerelease", False),
            "assets": [
                {
                    "name": asset.get("name"),
                    "size": asset.get("size"),
                    "url": asset.get("browser_download_url"),
                }
                for asset in release.get("assets", [])
            ],
        })
    return trimmed


def file_path(download_id: str) -> Path:
    safe_id = "".join(c for c in download_id if c.isalnum() or c in "-_.")
    return UPDATE_DIR / f"{safe_id}.tar.gz"


_ALLOWED_DOWNLOAD_HOSTS = ("github.com", "objects.githubusercontent.com")


def _assert_allowed_download_url(url: str) -> None:
    """Only allow GitHub release-asset URLs (prevents SSRF to internal hosts)."""
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    ok = parsed.scheme == "https" and (
        host in _ALLOWED_DOWNLOAD_HOSTS or host.endswith(".githubusercontent.com")
    )
    if not ok:
        raise ValueError(f"Refusing to download from a non-GitHub URL: {host or url!r}")


async def download_asset(download_id: str, url: str) -> Dict[str, Any]:
    """Download a release asset to local disk (foreign node only)."""
    _assert_allowed_download_url(url)
    UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    target = file_path(download_id)
    sha256 = hashlib.sha256()
    size = 0

    timeout = httpx.Timeout(connect=20.0, read=120.0, write=120.0, pool=20.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        async with client.stream("GET", url, headers=_headers()) as response:
            response.raise_for_status()
            with open(target, "wb") as f:
                async for chunk in response.aiter_bytes(chunk_size=1024 * 256):
                    f.write(chunk)
                    sha256.update(chunk)
                    size += len(chunk)

    logger.info(f"Update bundle {download_id} downloaded: {size} bytes")
    return {"download_id": download_id, "size": size, "sha256": sha256.hexdigest()}


def _find_bundle_root(extract_dir: Path) -> Path:
    """Locate the directory inside the extracted bundle that holds scripts/."""
    candidates = [extract_dir] + [p for p in extract_dir.iterdir() if p.is_dir()]
    for candidate in candidates:
        if (candidate / "scripts" / "install-node-native.sh").exists():
            return candidate
    raise FileNotFoundError("scripts/install-node-native.sh not found in update bundle")


def apply_update(download_id: str) -> Dict[str, Any]:
    """Extract the downloaded bundle and run the installer detached.

    Returns immediately; the installer restarts the smite-node service, so the
    caller should poll /api/agent/version afterwards to confirm the update.
    """
    if Path("/.dockerenv").exists():
        raise RuntimeError("Docker installs cannot self-update; pull the new image instead")

    bundle = file_path(download_id)
    if not bundle.exists() or bundle.stat().st_size == 0:
        raise FileNotFoundError(f"Update bundle not found: {bundle}")

    extract_dir = UPDATE_DIR / f"{bundle.stem.replace('.tar', '')}-extract"
    if extract_dir.exists():
        shutil.rmtree(extract_dir, ignore_errors=True)
    extract_dir.mkdir(parents=True, exist_ok=True)

    with tarfile.open(bundle, "r:gz") as tar:
        _safe_extractall(tar, extract_dir)

    bundle_root = _find_bundle_root(extract_dir)

    runner = UPDATE_DIR / f"run-{download_id}.sh"
    runner.write_text(
        "#!/bin/bash\n"
        f"exec >> {UPDATE_LOG} 2>&1\n"
        "echo \"=== node update started $(date) ===\"\n"
        f"cd '{bundle_root}'\n"
        "SMITE_NONINTERACTIVE=1 bash scripts/install-node-native.sh\n"
        "rc=$?\n"
        "echo \"=== node update finished $(date) exit=$rc ===\"\n"
        f"rm -rf '{extract_dir}' '{bundle}' || true\n"
        "exit $rc\n"
    )
    runner.chmod(0o755)

    # systemd-run escapes our service cgroup so the installer survives the
    # `systemctl restart smite-node` it performs.
    if shutil.which("systemd-run"):
        cmd = [
            "systemd-run",
            f"--unit=smite-node-update-{download_id}",
            "--collect",
            "/bin/bash",
            str(runner),
        ]
    else:
        cmd = ["setsid", "/bin/bash", str(runner)]

    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    logger.info(f"Update {download_id} launched via: {' '.join(cmd[:2])}")
    return {"status": "started", "log": UPDATE_LOG}
