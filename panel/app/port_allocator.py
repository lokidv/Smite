"""Collision-free port allocation for reverse-tunnel control/data ports.

Historically the control port for reverse tunnels was derived as
``base + md5(tunnel_id) % N`` and, for rathole, fell back to a single default
(``23333``) whenever the spec carried no explicit address. Two rathole servers
binding the same control port on one iran node fight over the socket and the
tunnels keep dropping ("socket bind error" / repeated disconnects). When one
iran node serves several foreign nodes this is almost guaranteed.

This module assigns a deterministic-but-unique port per node: it keeps the
historical preferred port when it is free, otherwise it probes for the next free
port among the active tunnels that share the same node. The chosen value is
persisted into ``tunnel.spec`` (``control_port`` / ``raw_port``) so every later
apply/reapply/restore path reuses the same stable, conflict-free port.
"""
import hashlib
import logging
from typing import Optional, Set

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.models import Tunnel

logger = logging.getLogger(__name__)

# Per-core preferred port windows (lo, hi inclusive) used for probing.
_CONTROL_WINDOWS = {
    "rathole": (23333, 24332),
    "backhaul": (3080, 4079),
    "chisel": (20000, 29999),
    "trusttunnel": (6100, 6899),
}
_UDP2RAW_RAW_WINDOW = (4096, 5095)


def _hash(tunnel_id: str) -> int:
    return int(hashlib.md5(tunnel_id.encode()).hexdigest()[:8], 16)


def _parse_port(addr) -> Optional[int]:
    """Extract the trailing :port from an address, tolerating ws:// prefixes."""
    if not addr or not isinstance(addr, str):
        return None
    s = addr
    for pre in ("ws://", "wss://", "http://", "https://"):
        if s.startswith(pre):
            s = s[len(pre):]
            break
    if ":" in s:
        tail = s.rsplit(":", 1)[1].split("/")[0]
        if tail.isdigit():
            return int(tail)
    return None


def _preferred_control_port(tunnel: Tunnel) -> int:
    """The historical (pre-allocation) control port a tunnel would use on iran."""
    spec = tunnel.spec or {}
    cp = spec.get("control_port")
    if cp and str(cp).isdigit():
        return int(cp)
    h = _hash(tunnel.id)
    core = tunnel.core
    if core == "rathole":
        return (
            _parse_port(spec.get("remote_addr"))
            or _parse_port(spec.get("bind_addr"))
            or (23333 + (h % 1000))
        )
    if core == "backhaul":
        v = spec.get("public_port") or spec.get("listen_port")
        if v and str(v).isdigit():
            return int(v)
        return 3080 + (h % 1000)
    if core == "chisel":
        lp = spec.get("listen_port") or spec.get("remote_port")
        if lp and str(lp).isdigit():
            return int(lp) + 10000 + (h % 1000)
        return 20000 + (h % 1000)
    if core == "trusttunnel":
        return 6100 + (h % 800)
    return 0


def _preferred_raw_port(tunnel: Tunnel) -> int:
    spec = tunnel.spec or {}
    rp = spec.get("raw_port")
    if rp and str(rp).isdigit():
        return int(rp)
    return 4096 + (_hash(tunnel.id) % 1000)


def _iran_node_of(t: Tunnel) -> Optional[str]:
    return t.iran_node_id or t.node_id or None


async def _used_control_ports(db, iran_node_id: str, exclude_id: str) -> Set[int]:
    """Control ports already claimed by other active tunnels on this iran node."""
    used: Set[int] = set()
    result = await db.execute(select(Tunnel).where(Tunnel.status == "active"))
    for t in result.scalars().all():
        if t.id == exclude_id or t.core not in _CONTROL_WINDOWS:
            continue
        if _iran_node_of(t) != iran_node_id:
            continue
        p = _preferred_control_port(t)
        if p:
            used.add(int(p))
    return used


async def _used_raw_ports(db, foreign_node_id: str, exclude_id: str) -> Set[int]:
    used: Set[int] = set()
    result = await db.execute(select(Tunnel).where(Tunnel.status == "active"))
    for t in result.scalars().all():
        if t.id == exclude_id or t.core != "udp2raw":
            continue
        if t.foreign_node_id != foreign_node_id:
            continue
        p = _preferred_raw_port(t)
        if p:
            used.add(int(p))
    return used


def _pick(preferred: int, used: Set[int], window) -> int:
    lo, hi = window
    if preferred and preferred not in used:
        return preferred
    for p in range(lo, hi + 1):
        if p not in used:
            return p
    # Window exhausted (very unlikely): keep preferred to avoid raising.
    return preferred or lo


async def assign_reverse_ports(db, tunnel: Tunnel, iran_node=None, foreign_node=None) -> bool:
    """Assign collision-free control/raw ports and persist them into tunnel.spec.

    Idempotent: once ``control_port``/``raw_port`` is present in the spec it is
    kept as-is (so existing tunnels keep their working ports). Returns True when
    the spec was modified.
    """
    spec = dict(tunnel.spec or {})
    core = tunnel.core
    changed = False

    if core in _CONTROL_WINDOWS and not spec.get("control_port"):
        iran_id = iran_node.id if iran_node is not None else _iran_node_of(tunnel)
        if iran_id:
            preferred = _preferred_control_port(tunnel)
            used = await _used_control_ports(db, iran_id, tunnel.id)
            port = _pick(int(preferred), used, _CONTROL_WINDOWS[core])
            spec["control_port"] = port
            changed = True
            logger.info(
                f"[port-alloc] tunnel {tunnel.id} ({core}) control_port={port} "
                f"(preferred={preferred}, used={sorted(used)}) on iran {iran_id}"
            )

    if core == "udp2raw" and not spec.get("raw_port"):
        fid = foreign_node.id if foreign_node is not None else tunnel.foreign_node_id
        if fid:
            preferred = _preferred_raw_port(tunnel)
            used = await _used_raw_ports(db, fid, tunnel.id)
            port = _pick(int(preferred), used, _UDP2RAW_RAW_WINDOW)
            spec["raw_port"] = port
            changed = True
            logger.info(
                f"[port-alloc] tunnel {tunnel.id} (udp2raw) raw_port={port} "
                f"(preferred={preferred}, used={sorted(used)}) on foreign {fid}"
            )

    if changed:
        tunnel.spec = spec
        flag_modified(tunnel, "spec")
    return changed
