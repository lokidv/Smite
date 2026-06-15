"""Panel + node self-update orchestration via the foreign-node relay.

The Iran panel has no GitHub access, so a foreign node acts as the relay:

  1. GET  releases        -> ask a foreign node to query api.github.com
  2. POST update/start    -> for every unique (arch, python) variant needed,
                             the relay downloads the bundle from GitHub and the
                             panel pulls it over the existing comm channel
  3. fan-out              -> the panel pushes the matching bundle to every node
                             (/update/upload + /update/apply) and polls each
                             node's /version until the new version shows up
  4. self-update          -> finally the panel extracts its own bundle and runs
                             install-native.sh --yes in a detached systemd unit
                             (the installer restarts smite-panel)

State is persisted to ./data/update/last_update.json so the report survives
the panel's own restart; GET /update/status reconciles the "applying" panel
state with the actually-running version after the restart.
"""
import asyncio
import json
import logging
import os
import shutil
import subprocess
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Node
from app.node_client import NodeClient, _node_auth_headers

logger = logging.getLogger(__name__)

DEFAULT_REPO = os.environ.get("SMITE_UPDATE_REPO", "lokidv/Smite")
UPDATE_DIR = Path(os.environ.get("SMITE_UPDATE_DIR", "./data/update"))
STATE_FILE = UPDATE_DIR / "last_update.json"
PANEL_UPDATE_LOG = "/var/log/smite-panel-update.log"
GITHUB_API = "https://api.github.com"


def _github_headers() -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "smite-panel-updater",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers

# Generous timeouts: bundles are 100-300 MB and may cross the FRP relay.
RELAY_DOWNLOAD_TIMEOUT = httpx.Timeout(connect=20.0, read=900.0, write=900.0, pool=20.0)
NODE_APPLY_TIMEOUT = httpx.Timeout(connect=20.0, read=120.0, write=120.0, pool=20.0)
VERSION_POLL_SECONDS = 240
VERSION_POLL_INTERVAL = 6
# How long after launching its own installer the panel may keep reporting the
# old version before the run is declared failed (install + restart time).
PANEL_APPLY_GRACE_SECONDS = 420


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


def panel_runtime() -> Dict[str, Any]:
    """Arch / python info of the panel host (to pick its own bundle variant)."""
    import platform
    import sys

    machine = platform.machine().lower()
    arch = "arm64" if machine in ("aarch64", "arm64") else "amd64"
    return {
        "arch": arch,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "install": "docker" if Path("/.dockerenv").exists() else "native",
    }


def pick_asset(assets: List[Dict[str, Any]], runtime: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Pick the offline bundle asset matching a host's arch + python version."""
    arch = runtime.get("arch") or "amd64"
    python = (runtime.get("python") or "").strip()
    pytag = "py" + python.replace(".", "") if python else ""
    prefix = f"smite-offline-{arch}-"

    candidates = [
        a for a in assets
        if (a.get("name") or "").startswith(prefix) and (a.get("name") or "").endswith(".tar.gz")
    ]
    if not candidates:
        return None
    if pytag:
        for asset in candidates:
            if f"-{pytag}.tar.gz" in asset["name"]:
                return asset
        return None  # wheels are python-specific; a wrong variant would fail to install
    return candidates[0]


async def get_current_panel_version() -> str:
    try:
        from app.routers.status import get_version
        result = await get_version()
        return str(result.get("version", "unknown"))
    except Exception:
        return "unknown"


def _find_bundle_root(extract_dir: Path, installer: str) -> Path:
    candidates = [extract_dir] + [p for p in extract_dir.iterdir() if p.is_dir()]
    for candidate in candidates:
        if (candidate / "scripts" / installer).exists():
            return candidate
    raise FileNotFoundError(f"scripts/{installer} not found in update bundle")


class UpdateManager:
    """Singleton orchestrating a panel + all-nodes update run."""

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._client = NodeClient()
        self.state: Dict[str, Any] = {"status": "idle"}
        self._load_state()

    # ---- state persistence ----

    def _load_state(self):
        try:
            if STATE_FILE.exists():
                self.state = json.loads(STATE_FILE.read_text())
        except Exception:
            self.state = {"status": "idle"}

    def _persist(self):
        try:
            UPDATE_DIR.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps(self.state, indent=2))
        except Exception as e:
            logger.warning(f"Could not persist update state: {e}")

    # ---- node HTTP helpers (custom timeouts; NodeClient's 30s is too short) ----

    async def _node_url(self, node: Node) -> Tuple[str, bool]:
        return await self._client._get_node_address(node)

    async def _node_request(
        self,
        node: Node,
        method: str,
        path: str,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[httpx.Timeout] = None,
        retries: int = 3,
    ) -> Dict[str, Any]:
        address, using_frp = await self._node_url(node)
        url = f"{address.rstrip('/')}{path}"
        timeout = timeout or httpx.Timeout(30.0)
        last_error: Optional[Exception] = None
        for attempt in range(retries):
            try:
                if attempt > 0:
                    await asyncio.sleep(2.0 if using_frp else 0.5)
                async with httpx.AsyncClient(
                    timeout=timeout,
                    verify=False,
                    limits=httpx.Limits(max_keepalive_connections=0 if using_frp else 5),
                ) as client:
                    response = await client.request(method, url, json=json_body, params=params, headers=_node_auth_headers())
                    response.raise_for_status()
                    return response.json()
            except httpx.HTTPStatusError as e:
                try:
                    detail = e.response.json().get("detail", str(e))
                except Exception:
                    detail = str(e)
                raise RuntimeError(f"HTTP {e.response.status_code}: {detail}")
            except httpx.RequestError as e:
                last_error = e
        raise RuntimeError(f"Network error: {last_error}")

    async def _pull_file_from_node(self, node: Node, download_id: str, dest: Path) -> int:
        """Stream a downloaded bundle from the relay node to panel disk."""
        address, using_frp = await self._node_url(node)
        url = f"{address.rstrip('/')}/api/agent/update/file"
        dest.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        async with httpx.AsyncClient(
            timeout=RELAY_DOWNLOAD_TIMEOUT,
            verify=False,
            limits=httpx.Limits(max_keepalive_connections=0 if using_frp else 5),
        ) as client:
            async with client.stream("GET", url, params={"download_id": download_id}) as response:
                response.raise_for_status()
                with open(dest, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=1024 * 256):
                        f.write(chunk)
                        size += len(chunk)
        if size == 0:
            raise RuntimeError("Relay returned an empty bundle")
        return size

    async def _push_file_to_node(self, node: Node, download_id: str, src: Path) -> Dict[str, Any]:
        """Stream a bundle from panel disk to a node's /update/upload."""
        address, using_frp = await self._node_url(node)
        url = f"{address.rstrip('/')}/api/agent/update/upload"

        async def file_chunks():
            with open(src, "rb") as f:
                while True:
                    chunk = f.read(1024 * 256)
                    if not chunk:
                        break
                    yield chunk

        async with httpx.AsyncClient(
            timeout=RELAY_DOWNLOAD_TIMEOUT,
            verify=False,
            limits=httpx.Limits(max_keepalive_connections=0 if using_frp else 5),
        ) as client:
            response = await client.post(
                url,
                params={"download_id": download_id},
                content=file_chunks(),
                headers={"Content-Type": "application/octet-stream", **_node_auth_headers()},
            )
            response.raise_for_status()
            return response.json()

    # ---- release listing ----

    async def _get_nodes(self) -> List[Node]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Node))
            return list(result.scalars().all())

    # ---- direct GitHub access (when the panel host itself has internet) ----

    async def _github_list_releases(self, repo: str, limit: int) -> List[Dict[str, Any]]:
        """Fetch releases straight from GitHub (no relay).

        Returns the same shape the foreign-node relay produces, so the rest of
        the flow does not care which source was used (asset ``url`` is the
        browser_download_url).
        """
        url = f"{GITHUB_API}/repos/{repo}/releases?per_page={max(1, min(limit, 30))}"
        async with httpx.AsyncClient(timeout=httpx.Timeout(25.0), follow_redirects=True) as client:
            resp = await client.get(url, headers=_github_headers())
            resp.raise_for_status()
            releases = resp.json()
        trimmed: List[Dict[str, Any]] = []
        for release in releases:
            trimmed.append({
                "tag": release.get("tag_name"),
                "name": release.get("name") or release.get("tag_name"),
                "published_at": release.get("published_at"),
                "prerelease": release.get("prerelease", False),
                "assets": [
                    {
                        "name": a.get("name"),
                        "size": a.get("size"),
                        "url": a.get("browser_download_url"),
                    }
                    for a in release.get("assets", [])
                ],
            })
        return trimmed

    async def _github_download(self, url: str, dest: Path) -> int:
        """Stream a release asset from GitHub straight to panel disk."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        async with httpx.AsyncClient(
            timeout=RELAY_DOWNLOAD_TIMEOUT, follow_redirects=True
        ) as client:
            async with client.stream("GET", url, headers=_github_headers()) as resp:
                resp.raise_for_status()
                with open(dest, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=1024 * 256):
                        f.write(chunk)
                        size += len(chunk)
        if size == 0:
            raise RuntimeError("GitHub returned an empty bundle")
        return size

    async def _find_relay(self, nodes: List[Node]) -> Optional[Node]:
        """First foreign node that can reach GitHub."""
        foreign = [n for n in nodes if n.node_metadata and n.node_metadata.get("role") == "foreign"]
        # Prefer active nodes
        foreign.sort(key=lambda n: 0 if n.status == "active" else 1)
        for node in foreign:
            try:
                await self._node_request(
                    node, "GET", "/api/agent/update/releases",
                    params={"limit": 1}, timeout=httpx.Timeout(25.0), retries=2,
                )
                return node
            except Exception as e:
                logger.warning(f"Relay candidate {node.name} unusable: {e}")
        return None

    async def list_releases(self, repo: str = "", limit: int = 10) -> Dict[str, Any]:
        repo = repo or DEFAULT_REPO
        nodes = await self._get_nodes()
        relay = await self._find_relay(nodes)

        # Preferred path (Iran panel): a foreign node relays GitHub for us.
        if relay:
            result = await self._node_request(
                relay, "GET", "/api/agent/update/releases",
                params={"repo": repo, "limit": limit},
                timeout=httpx.Timeout(30.0), retries=2,
            )
            return {
                "releases": result.get("releases", []),
                "relay_node": {"id": relay.id, "name": relay.name},
                "source": "relay",
                "current_version": await get_current_panel_version(),
            }

        # Fallback: no foreign-node relay, so try GitHub directly. This works
        # when the panel host itself has internet access (e.g. a foreign-hosted
        # panel, or an Iran box that can still reach github.com).
        try:
            releases = await self._github_list_releases(repo, limit)
        except Exception as e:
            raise RuntimeError(
                "Cannot fetch releases: no foreign node is registered to relay "
                "GitHub, and this panel server could not reach github.com directly. "
                "Either add a foreign node (it acts as the update relay for an Iran "
                "panel), or give this server internet access to GitHub. "
                f"(direct GitHub error: {e})"
            )
        return {
            "releases": releases,
            "relay_node": None,
            "source": "direct",
            "current_version": await get_current_panel_version(),
        }

    # ---- update run ----

    def is_running(self) -> bool:
        return bool(self._task and not self._task.done())

    async def get_status(self) -> Dict[str, Any]:
        state = dict(self.state)
        current = await get_current_panel_version()
        state["current_version"] = current

        # Reconcile after the panel's own restart. The orchestration task does
        # not survive the restart, so a state still marked "running" must be
        # finalized here - otherwise the UI stays on "update in progress"
        # forever and the start button never unlocks.
        if not self.is_running() and state.get("status") == "running":
            self._reconcile_interrupted(state, current)
        return state

    def _reconcile_interrupted(self, state: Dict[str, Any], current: str) -> None:
        """Finalize a run whose orchestration task is gone (panel restarted)."""
        target = (state.get("tag") or "").lstrip("v")
        panel_state = dict(state.get("panel") or {})
        changed = False

        if panel_state.get("status") == "applying":
            from_version = panel_state.get("from_version") or ""
            applied_at = panel_state.get("applied_at") or state.get("started_at") or ""
            grace_over = True
            try:
                started = datetime.fromisoformat(applied_at)
                grace_over = (datetime.utcnow() - started).total_seconds() > PANEL_APPLY_GRACE_SECONDS
            except Exception:
                pass

            if target and current == target:
                # The panel came back on the target version: success.
                panel_state["status"] = "updated"
                panel_state["to_version"] = current
                panel_state["message"] = ""
                changed = True
            elif current and from_version and current not in (from_version, "unknown"):
                # Version changed, just not to the expected string (e.g. the
                # release bundle reports a slightly different version). The
                # installer clearly ran; report success with a note instead of
                # blocking the update section forever.
                panel_state["status"] = "updated"
                panel_state["to_version"] = current
                panel_state["message"] = (
                    f"Panel now reports {current} (release tag was {target or '?'})."
                )
                changed = True
            elif grace_over:
                # Restarted, waited, version never changed: the install failed.
                panel_state["status"] = "failed"
                panel_state["message"] = (
                    f"Panel restarted but still reports {current} (expected {target}). "
                    f"Check {PANEL_UPDATE_LOG}."
                )
                changed = True
            else:
                # Still within the grace window: the detached installer may be
                # running right now. Keep the run open but tell the user.
                panel_state["message"] = (
                    "Panel restarted; waiting for the installer to finish "
                    f"(up to {PANEL_APPLY_GRACE_SECONDS // 60} minutes)..."
                )
                state["panel"] = panel_state
                return
        elif panel_state.get("status") in ("pending", "uploading"):
            # The run was interrupted before the panel step even started.
            panel_state["status"] = "failed"
            panel_state["message"] = "Interrupted by a panel restart"
            changed = True

        # Any node still mid-flight was interrupted as well.
        nodes = [dict(n) for n in state.get("nodes", [])]
        for entry in nodes:
            if entry.get("status") in ("pending", "uploading", "applying", "waiting"):
                entry["status"] = "failed"
                entry["message"] = "Interrupted by a panel restart"
                changed = True

        any_success = (
            panel_state.get("status") == "updated"
            or any(n.get("status") == "updated" for n in nodes)
        )
        state["panel"] = panel_state
        state["nodes"] = nodes
        state["status"] = "done" if any_success else "failed"
        state["finished_at"] = datetime.utcnow().isoformat()
        state["message"] = ""
        self.state = state
        self._persist()
        if changed:
            logger.info(
                f"Reconciled interrupted update run: panel={panel_state.get('status')} "
                f"overall={state['status']}"
            )

    async def start(
        self, tag: str, repo: str = "", targets: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Start an update run.

        ``targets`` selects what to update: "panel" and/or node IDs.
        None / empty list means everything (panel + all nodes).
        """
        if self.is_running():
            raise RuntimeError("An update is already running")
        repo = repo or DEFAULT_REPO
        targets = [t for t in (targets or []) if t]
        panel_selected = (not targets) or ("panel" in targets)
        self.state = {
            "status": "running",
            "tag": tag,
            "repo": repo,
            "targets": targets or None,
            "started_at": datetime.utcnow().isoformat(),
            "message": "",
            "panel": {
                "status": "pending" if panel_selected else "skipped",
                "message": "" if panel_selected else "Not selected",
            },
            "nodes": [],
        }
        self._persist()
        self._task = asyncio.create_task(self._run(tag, repo, targets))
        return {"status": "started", "tag": tag, "targets": targets or None}

    def _node_entry(self, node_id: str) -> Dict[str, Any]:
        for entry in self.state.get("nodes", []):
            if entry.get("node_id") == node_id:
                return entry
        entry = {"node_id": node_id}
        self.state.setdefault("nodes", []).append(entry)
        return entry

    def _set_node(self, node_id: str, **kwargs):
        entry = self._node_entry(node_id)
        entry.update(kwargs)
        self._persist()

    async def _run(self, tag: str, repo: str, targets: Optional[List[str]] = None):
        try:
            await self._run_inner(tag, repo, targets)
        except Exception as e:
            logger.error(f"Update run failed: {e}", exc_info=True)
            self.state["status"] = "failed"
            self.state["message"] = str(e)
            self.state["finished_at"] = datetime.utcnow().isoformat()
            self._persist()

    async def _run_inner(self, tag: str, repo: str, targets: Optional[List[str]] = None):
        target_version = tag.lstrip("v")
        all_nodes = await self._get_nodes()

        # Selection: None/empty targets = everything; otherwise "panel" and/or node IDs.
        targets = [t for t in (targets or []) if t]
        select_all = not targets
        panel_selected = select_all or ("panel" in targets)
        selected_ids = None if select_all else {t for t in targets if t != "panel"}
        nodes = [n for n in all_nodes if selected_ids is None or n.id in selected_ids]

        if not panel_selected and not nodes:
            raise RuntimeError("No valid update targets selected")

        for node in nodes:
            role = (node.node_metadata or {}).get("role", "unknown")
            self._set_node(node.id, name=node.name, role=role, status="pending", message="")

        # 1. Pick the release source: a foreign-node relay (Iran panel) or, if
        #    none is available, GitHub directly (panel host has internet).
        relay = await self._find_relay(all_nodes)
        if relay:
            self.state["relay_node"] = {"id": relay.id, "name": relay.name}
            self.state["source"] = "relay"
            self._persist()
            releases_resp = await self._node_request(
                relay, "GET", "/api/agent/update/releases",
                params={"repo": repo, "limit": 30}, timeout=httpx.Timeout(30.0), retries=2,
            )
            releases_list = releases_resp.get("releases", [])
        else:
            try:
                releases_list = await self._github_list_releases(repo, 30)
            except Exception as e:
                raise RuntimeError(
                    "No foreign node is registered to relay GitHub, and this panel "
                    "server could not reach github.com directly. Add a foreign node "
                    "(update relay for an Iran panel) or give this server internet "
                    f"access to GitHub. (direct GitHub error: {e})"
                )
            self.state["relay_node"] = None
            self.state["source"] = "direct"
            self.state["message"] = "Fetching the release directly from GitHub..."
            self._persist()

        release = next((r for r in releases_list if r.get("tag") == tag), None)
        if not release:
            raise RuntimeError(f"Release {tag} not found in {repo}")
        assets = release.get("assets", [])
        if not assets:
            raise RuntimeError(f"Release {tag} has no assets (build may still be running)")

        # 2. Collect runtimes (panel + nodes) and figure out needed variants
        runtimes: Dict[str, Dict[str, Any]] = {}
        for node in nodes:
            try:
                info = await self._node_request(
                    node, "GET", "/api/agent/version", timeout=httpx.Timeout(15.0), retries=2,
                )
                runtimes[node.id] = info
                self._set_node(node.id, from_version=info.get("version", "unknown"))
            except Exception as e:
                self._set_node(node.id, status="failed", message=f"Unreachable: {e}")

        my_runtime = panel_runtime()
        if panel_selected:
            self.state["panel"]["from_version"] = await get_current_panel_version()
        self._persist()

        # 3. Download every needed bundle variant to the panel via the relay
        needed: Dict[str, Dict[str, Any]] = {}  # download_id -> asset
        unsupported: Dict[str, str] = {}  # node_id -> reason

        def variant_for(runtime: Dict[str, Any]) -> Optional[str]:
            if runtime.get("install") == "docker":
                return None
            asset = pick_asset(assets, runtime)
            if not asset:
                return None
            download_id = asset["name"][: -len(".tar.gz")]
            needed[download_id] = asset
            return download_id

        node_variant: Dict[str, str] = {}
        for node in nodes:
            runtime = runtimes.get(node.id)
            if not runtime:
                continue
            if runtime.get("install") == "docker":
                unsupported[node.id] = "Docker install: update the container image instead"
                continue
            variant = variant_for(runtime)
            if not variant:
                unsupported[node.id] = (
                    f"No matching bundle for arch={runtime.get('arch')} python={runtime.get('python')}"
                )
                continue
            node_variant[node.id] = variant

        panel_variant: Optional[str] = None
        if not panel_selected:
            pass  # panel already marked "skipped" (not selected) in start()
        elif my_runtime.get("install") == "docker":
            self.state["panel"].update(
                status="skipped", message="Docker install: update the container image instead"
            )
        else:
            panel_variant = variant_for(my_runtime)
            if not panel_variant:
                self.state["panel"].update(
                    status="failed",
                    message=f"No matching bundle for arch={my_runtime.get('arch')} python={my_runtime.get('python')}",
                )
        self._persist()

        for node_id, reason in unsupported.items():
            self._set_node(node_id, status="failed", message=reason)

        UPDATE_DIR.mkdir(parents=True, exist_ok=True)
        local_files: Dict[str, Path] = {}
        src_label = relay.name if relay else "GitHub (direct)"
        for download_id, asset in needed.items():
            dest = UPDATE_DIR / f"{download_id}.tar.gz"
            expected_size = asset.get("size") or 0
            if dest.exists() and expected_size and dest.stat().st_size == expected_size:
                local_files[download_id] = dest  # already cached from a previous run
                continue
            self.state["message"] = f"Downloading {download_id} via {src_label}..."
            self._persist()
            try:
                if relay:
                    await self._node_request(
                        relay, "POST", "/api/agent/update/download",
                        json_body={"download_id": download_id, "url": asset["url"]},
                        timeout=RELAY_DOWNLOAD_TIMEOUT, retries=1,
                    )
                    size = await self._pull_file_from_node(relay, download_id, dest)
                else:
                    size = await self._github_download(asset["url"], dest)
                logger.info(f"Bundle {download_id} obtained via {src_label} ({size} bytes)")
                local_files[download_id] = dest
            except Exception as e:
                # Every node needing this variant fails
                for node_id, variant in node_variant.items():
                    if variant == download_id:
                        self._set_node(node_id, status="failed", message=f"Bundle download failed: {e}")
                if panel_variant == download_id:
                    self.state["panel"].update(status="failed", message=f"Bundle download failed: {e}")
                    panel_variant = None
                self._persist()

        # 4. Fan out to nodes (iran + foreign uniformly: push + apply + poll)
        for node in nodes:
            variant = node_variant.get(node.id)
            if not variant or variant not in local_files:
                continue
            entry = self._node_entry(node.id)
            if entry.get("status") == "failed":
                continue
            try:
                self._set_node(node.id, status="uploading", message="")
                await self._push_file_to_node(node, variant, local_files[variant])

                self._set_node(node.id, status="applying")
                await self._node_request(
                    node, "POST", "/api/agent/update/apply",
                    json_body={"download_id": variant}, timeout=NODE_APPLY_TIMEOUT, retries=1,
                )

                self._set_node(node.id, status="waiting", message="Waiting for node to restart...")
                new_version = await self._poll_node_version(node, target_version)
                if new_version == target_version:
                    self._set_node(node.id, status="updated", to_version=new_version, message="")
                else:
                    self._set_node(
                        node.id, status="failed", to_version=new_version,
                        message=(
                            f"Node came back with version {new_version or 'unknown'} "
                            f"(expected {target_version}). Check /var/log/smite-node-update.log on the node."
                        ),
                    )
            except Exception as e:
                self._set_node(node.id, status="failed", message=str(e))

        # 5. Panel self-update last (it will restart this process)
        if panel_variant and panel_variant in local_files:
            try:
                self.state["panel"]["status"] = "applying"
                self.state["panel"]["applied_at"] = datetime.utcnow().isoformat()
                self.state["message"] = "Updating panel (the panel will restart)..."
                self._persist()
                self._apply_panel_update(local_files[panel_variant], panel_variant)
                # If we are still alive a bit later, the report stays "applying";
                # get_status() reconciles after the restart.
            except Exception as e:
                self.state["panel"].update(status="failed", message=str(e))
                self._persist()

        # Final status: done if anything succeeded, failed if everything failed
        node_entries = self.state.get("nodes", [])
        panel_status = self.state["panel"].get("status")
        if panel_status == "applying":
            # leave status=running; get_status() flips it to done after the restart
            self.state["message"] = "Panel is restarting to finish its own update..."
        else:
            any_success = any(n.get("status") == "updated" for n in node_entries)
            self.state["status"] = "done" if (any_success or panel_status == "updated") else "failed"
            self.state["finished_at"] = datetime.utcnow().isoformat()
            self.state["message"] = ""
        self._persist()

    async def _poll_node_version(self, node: Node, target_version: str) -> str:
        """Poll a node's /version until it reports the target (or timeout)."""
        deadline = asyncio.get_event_loop().time() + VERSION_POLL_SECONDS
        last_seen = ""
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(VERSION_POLL_INTERVAL)
            try:
                info = await self._node_request(
                    node, "GET", "/api/agent/version", timeout=httpx.Timeout(10.0), retries=1,
                )
                last_seen = str(info.get("version", ""))
                if last_seen == target_version:
                    return last_seen
            except Exception:
                continue  # node restarting
        return last_seen

    def _apply_panel_update(self, bundle: Path, download_id: str):
        """Extract the panel bundle and run the installer in a detached unit.

        Extraction happens OUTSIDE /opt/smite (in /tmp) because the installer
        replaces /opt/smite/panel while running - extracting under the panel's
        data dir would let the installer delete its own running script.

        We use a panel-private work dir (NOT the node updater's /tmp/smite-update)
        so that, when the panel and an iran node run on the same host, the node
        updater's cleanup `rm -rf` cannot race-delete the panel's extracted files.
        """
        work_dir = Path("/tmp/smite-panel-update")
        work_dir.mkdir(parents=True, exist_ok=True)
        extract_dir = work_dir / f"{download_id}-extract"
        if extract_dir.exists():
            shutil.rmtree(extract_dir, ignore_errors=True)
        extract_dir.mkdir(parents=True, exist_ok=True)

        with tarfile.open(bundle, "r:gz") as tar:
            _safe_extractall(tar, extract_dir)
        bundle_root = _find_bundle_root(extract_dir, "install-native.sh")

        runner = work_dir / f"run-panel-{download_id}.sh"
        runner.write_text(
            "#!/bin/bash\n"
            f"exec >> {PANEL_UPDATE_LOG} 2>&1\n"
            "echo \"=== panel update started $(date) ===\"\n"
            f"cd '{bundle_root.resolve()}'\n"
            "SMITE_NONINTERACTIVE=1 bash scripts/install-native.sh\n"
            "rc=$?\n"
            "echo \"=== panel update finished $(date) exit=$rc ===\"\n"
            f"cd / && rm -rf '{extract_dir.resolve()}' || true\n"
            f"[ $rc -eq 0 ] && rm -f '{UPDATE_DIR.resolve()}'/*.tar.gz || true\n"
            "exit $rc\n"
        )
        runner.chmod(0o755)

        # systemd-run escapes the smite-panel cgroup so the installer survives
        # the `systemctl restart smite-panel` it performs.
        if shutil.which("systemd-run"):
            cmd = [
                "systemd-run",
                f"--unit=smite-panel-update-{int(datetime.utcnow().timestamp())}",
                "--collect",
                "/bin/bash",
                str(runner.resolve()),
            ]
        else:
            cmd = ["setsid", "/bin/bash", str(runner.resolve())]

        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.info(f"Panel update launched: {' '.join(cmd[:2])}")


update_manager = UpdateManager()
