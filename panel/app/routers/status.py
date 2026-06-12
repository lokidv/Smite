"""Status API endpoints"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import psutil

from app.database import get_db
from app.models import Tunnel, Node


router = APIRouter()

VERSION = "0.1.0"


@router.get("/version")
async def get_version():
    """Get panel version from the installed VERSION file, environment/Docker label, or git tag.

    Order matters: the VERSION file written by the installer reflects what is
    actually installed and must win over git metadata, which may describe an
    unrelated repo checkout on the same host (this previously made the panel
    report the wrong version after a self-update).
    """
    import os
    import subprocess
    from pathlib import Path

    app_root = Path(__file__).resolve().parents[2]  # .../panel (or /app in Docker)

    # 1. VERSION file: /app (Docker image) or the app root (native install,
    #    e.g. /opt/smite/panel/VERSION written by install-native.sh).
    version_candidates = [
        Path("/app/VERSION"),
        app_root / "VERSION",
        Path("/opt/smite/VERSION"),
    ]
    for version_file in version_candidates:
        try:
            if version_file.exists():
                version = version_file.read_text().strip()
                if version and version not in ["next", "latest", "offline"]:
                    return {"version": version.lstrip("v")}
        except:
            pass

    # 2. Dev checkout: derive the version from the panel's own git repo.
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=str(app_root)
        )
        if result.returncode == 0:
            git_version = result.stdout.strip()
            if git_version and not git_version.startswith("fatal"):
                version = git_version.split("-")[0].lstrip("v")
                if version and version not in ["next", "latest", "main", "master"]:
                    return {"version": version}
    except:
        pass

    smite_version = os.getenv("SMITE_VERSION", "")
    if smite_version in ["next", "latest"]:
        try:
            import json
            cgroup_path = Path("/proc/self/cgroup")
            if cgroup_path.exists():
                with open(cgroup_path) as f:
                    for line in f:
                        if "docker" in line or "containerd" in line:
                            container_id = line.split("/")[-1].strip()
                            result = subprocess.run(
                                ["docker", "inspect", container_id],
                                capture_output=True,
                                text=True,
                                timeout=2
                            )
                            if result.returncode == 0:
                                data = json.loads(result.stdout)
                                if data and len(data) > 0:
                                    labels = data[0].get("Config", {}).get("Labels", {})
                                    version = labels.get("smite.version") or labels.get("org.opencontainers.image.version", "")
                                    if version and version not in ["next", "latest"]:
                                        return {"version": version.lstrip("v")}
                            break
        except:
            pass
        
        return {"version": smite_version}
    
    if smite_version:
        version = smite_version.lstrip("v")
    else:
        version = VERSION
    
    return {"version": version}


@router.get("")
async def get_status(db: AsyncSession = Depends(get_db)):
    """Get system status"""
    cpu_percent = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    
    tunnel_result = await db.execute(select(func.count(Tunnel.id)))
    total_tunnels = tunnel_result.scalar() or 0
    
    active_tunnels_result = await db.execute(
        select(func.count(Tunnel.id)).where(Tunnel.status == "active")
    )
    active_tunnels = active_tunnels_result.scalar() or 0
    
    node_result = await db.execute(select(func.count(Node.id)))
    total_nodes = node_result.scalar() or 0
    
    active_nodes_result = await db.execute(
        select(func.count(Node.id)).where(Node.status == "active")
    )
    active_nodes = active_nodes_result.scalar() or 0
    
    return {
        "system": {
            "cpu_percent": cpu_percent,
            "memory_percent": memory.percent,
            "memory_total_gb": memory.total / (1024**3),
            "memory_used_gb": memory.used / (1024**3),
        },
        "tunnels": {
            "total": total_tunnels,
            "active": active_tunnels,
        },
        "nodes": {
            "total": total_nodes,
            "active": active_nodes,
        }
    }

