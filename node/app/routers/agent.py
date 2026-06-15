"""Agent API endpoints"""
import re
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, field_validator
from typing import Dict, Any
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

# tunnel_id is interpolated into config file paths and process-kill patterns, so
# it must not contain path separators or shell/glob metacharacters.
_TUNNEL_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _valid_tunnel_id(v: str) -> str:
    if not isinstance(v, str) or not _TUNNEL_ID_RE.match(v):
        raise ValueError("invalid tunnel_id (allowed: letters, digits, '_' and '-')")
    return v


class TunnelApply(BaseModel):
    tunnel_id: str
    core: str
    type: str
    spec: Dict[str, Any]

    @field_validator("tunnel_id")
    @classmethod
    def _check_tunnel_id(cls, v):
        return _valid_tunnel_id(v)


class TunnelRemove(BaseModel):
    tunnel_id: str

    @field_validator("tunnel_id")
    @classmethod
    def _check_tunnel_id(cls, v):
        return _valid_tunnel_id(v)


@router.post("/tunnels/apply")
async def apply_tunnel(data: TunnelApply, request: Request):
    """Apply tunnel configuration"""
    logger = logging.getLogger(__name__)
    adapter_manager = request.app.state.adapter_manager
    
    logger.info(f"Applying tunnel {data.tunnel_id}: core={data.core}, type={data.type}")
    try:
        await adapter_manager.apply_tunnel(
            tunnel_id=data.tunnel_id,
            tunnel_core=data.core,
            spec=data.spec
        )
        logger.info(f"Tunnel {data.tunnel_id} applied successfully")
        return {"status": "success", "message": "Tunnel applied"}
    except Exception as e:
        logger.error(f"Failed to apply tunnel {data.tunnel_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tunnels/remove")
async def remove_tunnel(data: TunnelRemove, request: Request):
    """Remove tunnel"""
    adapter_manager = request.app.state.adapter_manager
    
    try:
        await adapter_manager.remove_tunnel(data.tunnel_id)
        return {"status": "success", "message": "Tunnel removed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tunnels/status")
async def get_tunnel_status(tunnel_id: str, request: Request):
    """Get tunnel status"""
    adapter_manager = request.app.state.adapter_manager
    
    try:
        status = await adapter_manager.get_tunnel_status(tunnel_id)
        return {"status": "success", "data": status}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_status(request: Request):
    """Get node status"""
    adapter_manager = request.app.state.adapter_manager
    
    return {
        "status": "ok",
        "active_tunnels": len(adapter_manager.active_tunnels),
        "tunnels": list(adapter_manager.active_tunnels.keys())
    }


def get_runtime_info() -> Dict[str, Any]:
    """Version + environment info (used by /version and the update flow)."""
    import os
    import platform
    import sys
    from pathlib import Path

    version = os.getenv("SMITE_VERSION", "").strip()
    if not version:
        candidates = [
            Path(__file__).resolve().parents[2] / "VERSION",  # /opt/smite-node or /app
            Path("/opt/smite-node/VERSION"),
            Path("/app/VERSION"),
        ]
        for candidate in candidates:
            try:
                if candidate.exists():
                    value = candidate.read_text().strip()
                    if value and value not in ("next", "latest", "offline"):
                        version = value
                        break
            except Exception:
                pass

    machine = platform.machine().lower()
    arch = "arm64" if machine in ("aarch64", "arm64") else "amd64"
    install_type = "docker" if Path("/.dockerenv").exists() else "native"

    os_release = ""
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                os_release = line.split("=", 1)[1].strip().strip('"')
                break
    except Exception:
        pass

    return {
        "version": (version or "unknown").lstrip("v"),
        "arch": arch,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "os": os_release,
        "install": install_type,
    }


@router.get("/version")
async def get_version():
    """Get node agent version and runtime environment info."""
    return get_runtime_info()


# ---- Benchmark (tunnel quality test) ----

class BenchmarkSinkStart(BaseModel):
    sink_id: str
    port: int
    protocol: str = "tcp"
    duration_sec: int = 120


class BenchmarkSinkStop(BaseModel):
    sink_id: str


class BenchmarkProbe(BaseModel):
    host: str = "127.0.0.1"
    port: int
    protocol: str = "tcp"
    ping_count: int = 10
    throughput_seconds: float = 3.0


@router.post("/benchmark/sink/start")
async def benchmark_sink_start(data: BenchmarkSinkStart):
    """Start an echo/count sink used as the local target of a test tunnel."""
    from app.benchmark import sink_manager
    try:
        sink_manager.start_sink(data.sink_id, data.port, data.protocol, data.duration_sec)
        return {"status": "success", "message": f"Sink started on 127.0.0.1:{data.port}/{data.protocol}"}
    except Exception as e:
        logger.error(f"Failed to start benchmark sink: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/benchmark/sink/stop")
async def benchmark_sink_stop(data: BenchmarkSinkStop):
    """Stop a benchmark sink."""
    from app.benchmark import sink_manager
    try:
        sink_manager.stop_sink(data.sink_id)
        return {"status": "success", "message": "Sink stopped"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/benchmark/probe")
async def benchmark_probe(data: BenchmarkProbe):
    """Run a latency/throughput/loss probe through an applied test tunnel."""
    import asyncio
    from app.benchmark import run_probe
    try:
        metrics = await asyncio.to_thread(
            run_probe,
            host=data.host,
            port=data.port,
            protocol=data.protocol,
            ping_count=data.ping_count,
            throughput_seconds=data.throughput_seconds,
        )
        return {"status": "success", "metrics": metrics}
    except Exception as e:
        logger.error(f"Benchmark probe failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ---- SNI-spoof self-test + auto-tune ----

class SniSpoofTest(BaseModel):
    tunnel_id: str
    spec: Dict[str, Any]
    url: str = ""


class SniSpoofAutotune(BaseModel):
    tunnel_id: str
    spec: Dict[str, Any]
    url: str = ""
    combos: Any = None
    probes: int = 2


@router.post("/snispoof/test")
async def snispoof_test(data: SniSpoofTest, request: Request):
    """Probe a snispoof tunnel as-is and return pass/fail + the client outbound."""
    import asyncio
    from app import snispoof_test as st
    adapter_manager = request.app.state.adapter_manager
    try:
        result = await asyncio.to_thread(
            st.test_current, adapter_manager, data.tunnel_id, data.spec,
            data.url or st.DEFAULT_URL,
        )
        return {"status": "success", **result}
    except Exception as e:
        logger.error(f"snispoof test failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/snispoof/autotune")
async def snispoof_autotune(data: SniSpoofAutotune, request: Request):
    """Try every desync combo on the live tunnel, rank them, leave it on the best."""
    import asyncio
    from app import snispoof_test as st
    adapter_manager = request.app.state.adapter_manager
    try:
        result = await asyncio.to_thread(
            st.autotune, adapter_manager, data.tunnel_id, data.spec,
            data.combos, data.url or st.DEFAULT_URL, data.probes,
        )
        return {"status": "success", **result}
    except Exception as e:
        logger.error(f"snispoof autotune failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class WarpTest(BaseModel):
    tunnel_id: str
    spec: Dict[str, Any]


@router.post("/warp/test")
async def warp_test(data: WarpTest, request: Request):
    """Fetch the Cloudflare trace through the WARP SOCKS proxy and report egress IP."""
    import asyncio
    adapter_manager = request.app.state.adapter_manager
    adapter = adapter_manager.adapters.get("warp")
    if not adapter:
        raise HTTPException(status_code=400, detail="warp adapter not available")
    try:
        result = await asyncio.to_thread(adapter.test, data.tunnel_id, data.spec)
        return {"status": "success", **result}
    except Exception as e:
        logger.error(f"warp test failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class Obfs4Cert(BaseModel):
    tunnel_id: str


@router.post("/obfs4/cert")
async def obfs4_cert(data: Obfs4Cert, request: Request):
    """Return the obfs4 cert generated by a started obfs4 server on this node.

    The panel applies the foreign (server) side first, then calls this to learn
    the cert, then applies the iran (client) side with it.
    """
    adapter_manager = request.app.state.adapter_manager
    adapter = adapter_manager.adapters.get("obfs4")
    if not adapter:
        raise HTTPException(status_code=400, detail="obfs4 adapter not available")
    try:
        result = adapter.get_cert(data.tunnel_id)
        return {"status": "success", **result}
    except Exception as e:
        logger.error(f"obfs4 cert read failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ---- Self-update (panel-orchestrated) ----

class UpdateDownload(BaseModel):
    download_id: str
    url: str


class UpdateApply(BaseModel):
    download_id: str


@router.get("/update/releases")
async def update_releases(repo: str = "", limit: int = 10):
    """List GitHub releases (works only on nodes with internet access)."""
    from app import update as update_mod
    try:
        releases = await update_mod.fetch_releases(repo=repo, limit=limit)
        return {"status": "success", "releases": releases, "runtime": get_runtime_info()}
    except Exception as e:
        logger.error(f"Failed to list releases: {e}")
        raise HTTPException(status_code=502, detail=f"GitHub unreachable: {e}")


@router.post("/update/download")
async def update_download(data: UpdateDownload):
    """Download a release asset to local disk (relay step, needs internet)."""
    from app import update as update_mod
    try:
        result = await update_mod.download_asset(data.download_id, data.url)
        return {"status": "success", **result}
    except Exception as e:
        logger.error(f"Failed to download update asset: {e}")
        raise HTTPException(status_code=502, detail=f"Download failed: {e}")


@router.get("/update/file")
async def update_file(download_id: str):
    """Stream a previously downloaded bundle back to the panel."""
    from fastapi.responses import FileResponse
    from app import update as update_mod
    path = update_mod.file_path(download_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Bundle not found")
    return FileResponse(path, media_type="application/gzip", filename=path.name)


@router.post("/update/upload")
async def update_upload(download_id: str, request: Request):
    """Receive a bundle pushed by the panel (for nodes without GitHub access)."""
    import hashlib
    from app import update as update_mod
    update_mod.UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    target = update_mod.file_path(download_id)
    sha256 = hashlib.sha256()
    size = 0
    try:
        with open(target, "wb") as f:
            async for chunk in request.stream():
                f.write(chunk)
                sha256.update(chunk)
                size += len(chunk)
    except Exception as e:
        try:
            target.unlink(missing_ok=True)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")
    if size == 0:
        raise HTTPException(status_code=400, detail="Empty upload")
    logger.info(f"Update bundle {download_id} received: {size} bytes")
    return {"status": "success", "download_id": download_id, "size": size, "sha256": sha256.hexdigest()}


@router.post("/update/apply")
async def update_apply(data: UpdateApply):
    """Extract the bundle and run the non-interactive installer (detached)."""
    import asyncio
    from app import update as update_mod
    try:
        result = await asyncio.to_thread(update_mod.apply_update, data.download_id)
        return {"status": "success", **result}
    except Exception as e:
        logger.error(f"Failed to apply update: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

