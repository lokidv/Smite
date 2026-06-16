"""Health, problems and self-healing API."""
import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Tunnel, Node, NodeProblem
from app.health_monitor import health_monitor

logger = logging.getLogger(__name__)
router = APIRouter()


def _tunnel_health_dict(t: Tunnel) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "core": t.core,
        "type": t.type,
        "status": t.status,
        "health": t.health or "unknown",
        "health_detail": t.health_detail,
        "health_checked_at": t.health_checked_at.isoformat() if t.health_checked_at else None,
        "node_id": t.node_id,
        "iran_node_id": t.iran_node_id,
        "foreign_node_id": t.foreign_node_id,
    }


def _problem_dict(p: NodeProblem, node_name: Optional[str] = None, tunnel_name: Optional[str] = None) -> dict:
    return {
        "id": p.id,
        "node_id": p.node_id,
        "node_name": node_name,
        "tunnel_id": p.tunnel_id,
        "tunnel_name": tunnel_name,
        "kind": p.kind,
        "severity": p.severity,
        "message": p.message,
        "detail": p.detail,
        "status": p.status,
        "auto_heal_action": p.auto_heal_action,
        "auto_heal_result": p.auto_heal_result,
        "occurrences": p.occurrences,
        "first_seen": p.first_seen.isoformat() if p.first_seen else None,
        "last_seen": p.last_seen.isoformat() if p.last_seen else None,
        "resolved_at": p.resolved_at.isoformat() if p.resolved_at else None,
    }


@router.get("/tunnels")
async def list_tunnel_health(db: AsyncSession = Depends(get_db)):
    """Live, monitor-derived health for every tunnel (drives the Tunnels badge)."""
    rows = (await db.execute(select(Tunnel))).scalars().all()
    return [_tunnel_health_dict(t) for t in rows]


@router.get("/summary")
async def health_summary(db: AsyncSession = Depends(get_db)):
    """Aggregate health counts + last monitor run info."""
    rows = (await db.execute(select(Tunnel))).scalars().all()
    counts: dict = {}
    for t in rows:
        h = t.health or "unknown"
        counts[h] = counts.get(h, 0) + 1
    open_problems = (await db.execute(
        select(NodeProblem).where(NodeProblem.status == "open")
    )).scalars().all()
    return {
        "health_counts": counts,
        "open_problems": len(open_problems),
        "last_run_at": health_monitor.last_run_at.isoformat() if health_monitor.last_run_at else None,
        "last_summary": health_monitor.last_summary,
    }


@router.get("/config")
async def get_health_config():
    return await health_monitor.get_config()


@router.put("/config")
async def set_health_config(updates: dict):
    try:
        cfg = await health_monitor.set_config(updates or {})
        return {"status": "success", "config": cfg}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/problems")
async def list_problems(status: str = "open", db: AsyncSession = Depends(get_db)):
    q = select(NodeProblem)
    if status and status != "all":
        q = q.where(NodeProblem.status == status)
    q = q.order_by(NodeProblem.last_seen.desc())
    rows = (await db.execute(q)).scalars().all()
    nodes = {n.id: n.name for n in (await db.execute(select(Node))).scalars().all()}
    tunnels = {t.id: t.name for t in (await db.execute(select(Tunnel))).scalars().all()}
    return [_problem_dict(p, nodes.get(p.node_id), tunnels.get(p.tunnel_id)) for p in rows]


@router.get("/nodes/{node_id}/problems")
async def list_node_problems(node_id: str, status: str = "open", db: AsyncSession = Depends(get_db)):
    q = select(NodeProblem).where(NodeProblem.node_id == node_id)
    if status and status != "all":
        q = q.where(NodeProblem.status == status)
    q = q.order_by(NodeProblem.last_seen.desc())
    rows = (await db.execute(q)).scalars().all()
    tunnels = {t.id: t.name for t in (await db.execute(select(Tunnel))).scalars().all()}
    return [_problem_dict(p, None, tunnels.get(p.tunnel_id)) for p in rows]


@router.post("/problems/{problem_id}/resolve")
async def resolve_problem(problem_id: str, db: AsyncSession = Depends(get_db)):
    p = (await db.execute(select(NodeProblem).where(NodeProblem.id == problem_id))).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Problem not found")
    p.status = "resolved"
    p.resolved_at = datetime.utcnow()
    await db.commit()
    return {"status": "success"}


@router.post("/heal/{tunnel_id}")
async def heal_tunnel(tunnel_id: str, db: AsyncSession = Depends(get_db)):
    """Manually self-heal one tunnel (full stop+start on both nodes)."""
    t = (await db.execute(select(Tunnel).where(Tunnel.id == tunnel_id))).scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    ok = await health_monitor._heal_tunnel(tunnel_id)
    if not ok:
        raise HTTPException(status_code=502, detail="Heal failed (check node connectivity)")
    return {"status": "success"}


@router.post("/reconcile")
async def reconcile_now():
    """Run a full monitor + reconcile + heal pass immediately."""
    try:
        summary = await health_monitor.run_once()
        return {"status": "success", "summary": summary}
    except Exception as e:
        logger.error(f"Manual reconcile failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/nodes/{node_id}/reconcile")
async def reconcile_node(node_id: str):
    """Run a full reconcile pass now (node-scoped problems will refresh)."""
    try:
        summary = await health_monitor.run_once()
        return {"status": "success", "summary": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
