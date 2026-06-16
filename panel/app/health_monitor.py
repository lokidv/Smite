"""Tunnel health monitor, reconciler and self-healer.

This is the "brain" that makes the panel professional and self-healing:

1. Monitor  - polls every node's /api/agent/health and derives the REAL state of
   each tunnel (process alive + control-channel up on every required end), not
   the optimistic "active" the configured status used to show.
2. Reconcile - guarantees one iran node can serve many foreign nodes with zero
   interference: every node must run ONLY the tunnels the panel assigns to it.
   Orphan / mis-routed / duplicate clients are removed; missing ones re-applied.
   Destructive actions only happen when the node answered (never on a timeout).
3. Self-heal - automatically re-applies disconnected/stopped tunnels using
   consecutive-failure thresholds, per-tunnel cooldowns and a per-cycle cap so it
   never storms.
4. Problems  - records every issue (and what it did about it) as NodeProblem rows
   so the UI can show a per-node "Problems" panel, and auto-resolves them when the
   condition clears. Also raises proactive diagnostics (offline assigned node,
   control-port collision risk, stale FRP state).
"""
import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, Any, List, Set, Optional

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.database import AsyncSessionLocal
from app.models import Node, Tunnel, Settings, NodeProblem
from app.node_client import NodeClient

logger = logging.getLogger(__name__)

REVERSE_CORES = {
    "rathole", "backhaul", "chisel", "frp", "udp2raw",
    "trusttunnel", "hysteria2", "tuic", "obfs4",
}

# Problem kinds the monitor owns (so it may auto-resolve them when they clear).
MANAGED_KINDS = {
    "orphan", "conflict", "disconnected", "stopped",
    "node_offline", "port_conflict", "frp_stale",
}

DEFAULT_CONFIG = {
    "monitor_enabled": True,
    "auto_heal_enabled": True,
    "interval_seconds": 45,
    "unhealthy_threshold": 2,       # consecutive bad cycles before auto-heal
    "heal_cooldown_seconds": 180,   # min seconds between heals of one tunnel
    "max_heals_per_cycle": 5,
    "max_removes_per_cycle": 25,
    "creation_grace_seconds": 120,  # leave brand-new tunnels alone
}


class HealthMonitor:
    def __init__(self):
        self.task: Optional[asyncio.Task] = None
        self._bad_counts: Dict[str, int] = {}      # tunnel_id -> consecutive unhealthy cycles
        self._last_heal: Dict[str, float] = {}      # tunnel_id -> ts of last heal
        self.last_run_at: Optional[datetime] = None
        self.last_summary: Dict[str, Any] = {}

    # ---- config ----
    async def get_config(self) -> Dict[str, Any]:
        cfg = dict(DEFAULT_CONFIG)
        try:
            async with AsyncSessionLocal() as s:
                r = await s.execute(select(Settings).where(Settings.key == "health"))
                row = r.scalar_one_or_none()
                if row and row.value:
                    cfg.update({k: v for k, v in row.value.items() if k in DEFAULT_CONFIG})
        except Exception as e:
            logger.debug(f"health config load failed: {e}")
        return cfg

    async def set_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        cfg = await self.get_config()
        for k, v in (updates or {}).items():
            if k in DEFAULT_CONFIG:
                cfg[k] = v
        async with AsyncSessionLocal() as s:
            r = await s.execute(select(Settings).where(Settings.key == "health"))
            row = r.scalar_one_or_none()
            if row:
                row.value = cfg
                flag_modified(row, "value")
            else:
                s.add(Settings(key="health", value=cfg))
            await s.commit()
        return cfg

    # ---- lifecycle ----
    async def start(self):
        await self.stop()
        self.task = asyncio.create_task(self._loop())
        logger.info("Health monitor started")

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

    async def _loop(self):
        try:
            while True:
                cfg = await self.get_config()
                interval = max(15, int(cfg.get("interval_seconds", 45)))
                if cfg.get("monitor_enabled", True):
                    try:
                        await self.run_once(cfg)
                    except Exception as e:
                        logger.error(f"Health monitor cycle error: {e}", exc_info=True)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("Health monitor loop cancelled")
            raise

    # ---- helpers ----
    @staticmethod
    def _required_ends(t: Tunnel) -> List[str]:
        if t.core in REVERSE_CORES:
            iran = t.iran_node_id or t.node_id
            foreign = t.foreign_node_id
            return [e for e in (iran, foreign) if e]
        return [t.node_id] if t.node_id else []

    @classmethod
    def _desired_tids_for_node(cls, node_id: str, tunnels: List[Tunnel]) -> Set[str]:
        out: Set[str] = set()
        for t in tunnels:
            if node_id in cls._required_ends(t):
                out.add(t.id)
        return out

    @staticmethod
    def _control_port_of(t: Tunnel) -> Optional[int]:
        try:
            from app.port_allocator import _preferred_control_port
            if t.core in ("rathole", "backhaul", "chisel", "trusttunnel"):
                return _preferred_control_port(t)
        except Exception:
            pass
        return None

    # ---- main pass ----
    async def run_once(self, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        cfg = cfg or await self.get_config()
        now = time.time()
        client = NodeClient()

        async with AsyncSessionLocal() as session:
            nodes = (await session.execute(select(Node))).scalars().all()
            tunnels = (await session.execute(
                select(Tunnel).where(Tunnel.status == "active")
            )).scalars().all()

        nodes_by_id = {n.id: n for n in nodes}
        tunnels_by_id = {t.id: t for t in tunnels}
        young_ids = self._young_ids(tunnels, cfg)

        # 1) Fetch health from every node concurrently.
        node_health: Dict[str, Dict[str, Any]] = {}
        results = await asyncio.gather(
            *[client.get_node_health(n.id) for n in nodes], return_exceptions=True
        )
        for n, res in zip(nodes, results):
            if isinstance(res, Exception):
                node_health[n.id] = {"reachable": False, "message": str(res), "running": [], "tunnels": {}}
            else:
                res.setdefault("running", [])
                res.setdefault("tunnels", {})
                node_health[n.id] = res
        node_reachable = {nid: bool(h.get("reachable")) for nid, h in node_health.items()}

        current_problem_keys: Set[tuple] = set()
        summary = {"checked": len(tunnels), "removed": 0, "healed": 0, "conflicts": 0,
                   "offline_nodes": sum(1 for v in node_reachable.values() if not v)}

        async with AsyncSessionLocal() as session:
            # 2) Reconcile: remove tunnels a node runs but is not assigned.
            removed_total = 0
            conflict_tids: Set[str] = set()
            for n in nodes:
                h = node_health.get(n.id, {})
                if not h.get("reachable"):
                    continue
                running = set(h.get("running") or [])
                desired = self._desired_tids_for_node(n.id, tunnels)
                orphans = running - desired
                for tid in orphans:
                    # Don't disturb a brand-new tunnel still being provisioned on
                    # its correct node (it would be in `desired` there anyway).
                    if tid in tunnels_by_id and tid in young_ids:
                        continue
                    if removed_total >= int(cfg.get("max_removes_per_cycle", 25)):
                        break
                    known = tunnels_by_id.get(tid)
                    is_conflict = known is not None  # exists but assigned elsewhere
                    if is_conflict:
                        conflict_tids.add(tid)
                        summary["conflicts"] += 1
                    resp = await client.send_to_node(
                        n.id, "/api/agent/tunnels/remove", {"tunnel_id": tid}
                    )
                    ok = isinstance(resp, dict) and resp.get("status") == "success"
                    removed_total += 1 if ok else 0
                    kind = "conflict" if is_conflict else "orphan"
                    msg = (
                        f"Tunnel {tid} was running on node '{n.name}' but is not assigned to it"
                        + (" (duplicate/mis-routed client)." if is_conflict else " (stale/deleted).")
                    )
                    key = (n.id, tid, kind)
                    current_problem_keys.add(key)
                    await self._record_problem(
                        session, node_id=n.id, tunnel_id=tid, kind=kind,
                        severity="critical" if is_conflict else "warning",
                        message=msg, detail={"node": n.name},
                        action="remove", result="removed" if ok else f"remove_failed: {resp.get('message') if isinstance(resp, dict) else resp}",
                    )
            summary["removed"] = removed_total

            # 3) Compute real health for each tunnel + heal.
            heals_done = 0
            auto_heal = bool(cfg.get("auto_heal_enabled", True))
            threshold = max(1, int(cfg.get("unhealthy_threshold", 2)))
            cooldown = int(cfg.get("heal_cooldown_seconds", 180))
            for t in tunnels:
                health, detail, per_end = self._compute_health(t, node_health, node_reachable)
                if t.id in conflict_tids:
                    health = "conflict"
                    detail = "running on a node it is not assigned to"

                # Persist health on the tunnel row.
                db_t = (await session.execute(select(Tunnel).where(Tunnel.id == t.id))).scalar_one_or_none()
                if db_t:
                    db_t.health = health
                    db_t.health_detail = detail
                    db_t.health_checked_at = datetime.utcnow()

                # Problems for offline-assigned-node.
                for e in self._required_ends(t):
                    if not node_reachable.get(e, False):
                        nname = nodes_by_id.get(e).name if nodes_by_id.get(e) else e
                        key = (e, t.id, "node_offline")
                        current_problem_keys.add(key)
                        await self._record_problem(
                            session, node_id=e, tunnel_id=t.id, kind="node_offline",
                            severity="critical",
                            message=f"Assigned node '{nname}' is unreachable for tunnel '{t.name}'.",
                            detail={"connection": per_end},
                        )

                # Decide unhealthy + self-heal.
                unhealthy = health in ("disconnected", "stopped", "degraded")
                if unhealthy:
                    self._bad_counts[t.id] = self._bad_counts.get(t.id, 0) + 1
                    primary_node = (t.iran_node_id or t.node_id) if t.core in REVERSE_CORES else t.node_id
                    key = (primary_node, t.id, health if health in MANAGED_KINDS else "disconnected")
                    current_problem_keys.add(key)
                    await self._record_problem(
                        session, node_id=primary_node, tunnel_id=t.id,
                        kind=health if health in MANAGED_KINDS else "disconnected",
                        severity="warning",
                        message=f"Tunnel '{t.name}' is {health}: {detail}",
                        detail={"connection": per_end},
                    )
                    can_heal = (
                        auto_heal
                        and t.id not in young_ids
                        and self._bad_counts[t.id] >= threshold
                        and (now - self._last_heal.get(t.id, 0)) >= cooldown
                        and heals_done < int(cfg.get("max_heals_per_cycle", 5))
                    )
                    if can_heal:
                        ok = await self._heal_tunnel(t.id)
                        self._last_heal[t.id] = now
                        heals_done += 1
                        await self._record_problem(
                            session, node_id=primary_node, tunnel_id=t.id,
                            kind=health if health in MANAGED_KINDS else "disconnected",
                            severity="warning",
                            message=f"Tunnel '{t.name}' is {health}: {detail}",
                            detail={"connection": per_end},
                            action="reapply", result="reapplied" if ok else "reapply_failed",
                        )
                        if ok:
                            self._bad_counts[t.id] = 0
                else:
                    self._bad_counts.pop(t.id, None)

            summary["healed"] = heals_done

            # 4) Proactive diagnostics: control-port collisions on an iran node.
            await self._diagnose_port_collisions(session, tunnels, current_problem_keys)

            # 5) Auto-resolve managed problems that no longer occur.
            await self._auto_resolve(session, current_problem_keys)

            await session.commit()

        self.last_run_at = datetime.utcnow()
        self.last_summary = summary
        logger.info(
            f"[health] checked={summary['checked']} removed={summary['removed']} "
            f"healed={summary['healed']} conflicts={summary['conflicts']} "
            f"offline_nodes={summary['offline_nodes']}"
        )
        return summary

    def _young_ids(self, tunnels: List[Tunnel], cfg: Dict[str, Any]) -> Set[str]:
        grace = int(cfg.get("creation_grace_seconds", 120))
        cutoff = datetime.utcnow().timestamp() - grace
        out = set()
        for t in tunnels:
            try:
                if t.created_at and t.created_at.timestamp() > cutoff:
                    out.add(t.id)
            except Exception:
                pass
        return out

    def _compute_health(self, t: Tunnel, node_health: Dict[str, Any], node_reachable: Dict[str, bool]):
        ends = self._required_ends(t)
        if not ends:
            return "unknown", "no nodes assigned", {}
        per_end: Dict[str, str] = {}
        for e in ends:
            nh = node_health.get(e, {})
            if not node_reachable.get(e, False):
                per_end[e] = "offline"
                continue
            th = (nh.get("tunnels") or {}).get(t.id)
            running = t.id in (nh.get("running") or [])
            if th:
                per_end[e] = th.get("connection_state", "unknown")
            elif nh.get("legacy"):
                per_end[e] = "running_unknown" if running else "stopped"
            else:
                per_end[e] = "running_unknown" if running else "stopped"
        vals = list(per_end.values())
        if any(v == "offline" for v in vals):
            health = "node_offline"
        elif vals and all(v == "connected" for v in vals):
            health = "healthy"
        elif vals and all(v == "stopped" for v in vals):
            health = "stopped"
        elif any(v == "connected" for v in vals) and any(v in ("disconnected", "stopped", "connecting") for v in vals):
            health = "degraded"
        elif any(v == "disconnected" for v in vals):
            health = "disconnected"
        elif any(v == "connecting" for v in vals):
            health = "connecting"
        elif any(v == "running_unknown" for v in vals):
            health = "unknown"
        else:
            health = "unknown"
        detail = ", ".join(f"{('iran' if (t.iran_node_id or t.node_id)==e else 'foreign')}={v}" for e, v in per_end.items())
        return health, detail, per_end

    async def _heal_tunnel(self, tunnel_id: str) -> bool:
        try:
            from app.tunnel_reapply_manager import tunnel_reapply_manager
            applied, failed = await tunnel_reapply_manager.reapply_tunnels([tunnel_id])
            logger.info(f"[health] self-heal reapply {tunnel_id}: applied={applied} failed={failed}")
            return applied > 0
        except Exception as e:
            logger.error(f"[health] self-heal of {tunnel_id} failed: {e}", exc_info=True)
            return False

    async def _diagnose_port_collisions(self, session, tunnels: List[Tunnel], current_keys: Set[tuple]):
        by_node_port: Dict[tuple, List[Tunnel]] = {}
        for t in tunnels:
            if t.core not in ("rathole", "backhaul", "chisel", "trusttunnel"):
                continue
            iran = t.iran_node_id or t.node_id
            port = self._control_port_of(t)
            if not iran or not port:
                continue
            by_node_port.setdefault((iran, port), []).append(t)
        for (iran, port), group in by_node_port.items():
            if len(group) > 1:
                names = ", ".join(g.name for g in group)
                for g in group:
                    key = (iran, g.id, "port_conflict")
                    current_keys.add(key)
                    await self._record_problem(
                        session, node_id=iran, tunnel_id=g.id, kind="port_conflict",
                        severity="critical",
                        message=f"Control port {port} is shared by {len(group)} tunnels on the same iran node ({names}). They will fight; recreate one to reassign its port.",
                        detail={"port": port, "tunnels": [g.id for g in group]},
                    )

    async def _record_problem(self, session, node_id, tunnel_id, kind, severity, message,
                              detail=None, action=None, result=None):
        """Upsert an open problem deduped by (node_id, tunnel_id, kind)."""
        try:
            q = select(NodeProblem).where(
                NodeProblem.kind == kind,
                NodeProblem.status == "open",
            )
            rows = (await session.execute(q)).scalars().all()
            existing = next(
                (p for p in rows if p.node_id == node_id and p.tunnel_id == tunnel_id), None
            )
            now = datetime.utcnow()
            if existing:
                existing.last_seen = now
                existing.occurrences = (existing.occurrences or 1) + 1
                existing.message = message
                existing.severity = severity
                if detail is not None:
                    existing.detail = detail
                if action:
                    existing.auto_heal_action = action
                    existing.auto_heal_result = result
            else:
                session.add(NodeProblem(
                    node_id=node_id, tunnel_id=tunnel_id, kind=kind, severity=severity,
                    message=message, detail=detail, status="open",
                    auto_heal_action=action, auto_heal_result=result,
                    occurrences=1, first_seen=now, last_seen=now,
                ))
        except Exception as e:
            logger.debug(f"record_problem failed: {e}")

    async def _auto_resolve(self, session, current_keys: Set[tuple]):
        try:
            rows = (await session.execute(
                select(NodeProblem).where(NodeProblem.status == "open")
            )).scalars().all()
            now = datetime.utcnow()
            for p in rows:
                if p.kind in MANAGED_KINDS and (p.node_id, p.tunnel_id, p.kind) not in current_keys:
                    p.status = "auto_resolved"
                    p.resolved_at = now
        except Exception as e:
            logger.debug(f"auto_resolve failed: {e}")


health_monitor = HealthMonitor()
