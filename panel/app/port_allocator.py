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
    "awg_ws": (23333, 24332),
    "backhaul": (3080, 4079),
    "chisel": (20000, 29999),
    "trusttunnel": (6100, 6899),
}
_UDP2RAW_RAW_WINDOW = (4096, 5095)

# Multi-port hopping claims a contiguous UDP range with a single REDIRECT rule.
# Every tunnel used to get the same hard-coded "20000:40000" — 20001 ports for
# one tunnel — so a second mport_hop tunnel on a node installed an identical
# REDIRECT that fought with the first, and the range swallowed every other UDP
# service in it. Hand each tunnel its own slice of the pool instead.
_HOP_POOL = (20000, 40000)
_HOP_SLICE = 512


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
    if core in ("rathole", "awg_ws"):
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


async def _used_control_ports(
    db, iran_node_id: Optional[str], foreign_node_id: Optional[str], exclude_id: str
) -> Set[int]:
    """Control ports already claimed by other active tunnels sharing either end.

    For a reverse tunnel the listener binds on the FOREIGN node — see
    ``Tunnel.foreign_node_id`` ("foreign node (server side)"), and the adapters
    which want ``remote_addr``/``server_url`` pointing at the foreign server.
    This used to filter on the iran node alone, so two tunnels from *different*
    iran nodes to the *same* foreign node never saw each other and were handed
    the same control port, which both then tried to bind on that one foreign
    node. That is exactly the reported failure: adding a second/backup iran node
    against an already-tunnelled foreign node drops the link, and two iran nodes
    on one foreign node keep fighting over the socket.

    Matching on either end is a superset of what is strictly needed. It cannot
    hand out a colliding port on either side, and being slightly conservative
    costs nothing: the probe windows are ~1000 ports wide.
    """
    ends = {n for n in (iran_node_id, foreign_node_id) if n}
    used: Set[int] = set()
    if not ends:
        return used
    result = await db.execute(select(Tunnel).where(Tunnel.status == "active"))
    for t in result.scalars().all():
        if t.id == exclude_id or t.core not in _CONTROL_WINDOWS:
            continue
        if not ends & {n for n in (_iran_node_of(t), t.foreign_node_id) if n}:
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


def _hop_range_start(value) -> Optional[int]:
    """First port of a 'lo:hi' / 'lo-hi' range string."""
    if not value:
        return None
    head = str(value).replace("-", ":").split(":")[0].strip()
    return int(head) if head.isdigit() else None


def _preferred_hop_start(tunnel: Tunnel) -> int:
    cur = _hop_range_start((tunnel.spec or {}).get("port_range"))
    if cur:
        return cur
    lo, hi = _HOP_POOL
    slots = max(1, (hi - lo + 1) // _HOP_SLICE)
    return lo + (_hash(tunnel.id) % slots) * _HOP_SLICE


async def _used_hop_starts(db, ends: Set[str], exclude_id: str) -> Set[int]:
    """Slice starts already claimed by other active mport_hop tunnels on these nodes."""
    used: Set[int] = set()
    if not ends:
        return used
    result = await db.execute(select(Tunnel).where(Tunnel.status == "active"))
    for t in result.scalars().all():
        if t.id == exclude_id or t.core != "mport_hop":
            continue
        if not ends & {n for n in (_iran_node_of(t), t.foreign_node_id) if n}:
            continue
        s = _hop_range_start((t.spec or {}).get("port_range"))
        if s:
            used.add(s)
    return used


async def assign_hop_range(db, tunnel: Tunnel, iran_node=None, foreign_node=None) -> bool:
    """Give an mport_hop tunnel its own port slice; persist it into the spec.

    Idempotent: an existing ``port_range`` is kept, so tunnels created before
    this existed keep the range their clients are already using.
    """
    if tunnel.core != "mport_hop":
        return False
    spec = dict(tunnel.spec or {})
    if spec.get("port_range"):
        return False

    ends = {n for n in (
        iran_node.id if iran_node is not None else _iran_node_of(tunnel),
        foreign_node.id if foreign_node is not None else tunnel.foreign_node_id,
        tunnel.node_id,
    ) if n}
    used = await _used_hop_starts(db, ends, tunnel.id)

    lo, hi = _HOP_POOL
    slots = max(1, (hi - lo + 1) // _HOP_SLICE)
    start = _preferred_hop_start(tunnel)
    if start in used:
        for i in range(slots):
            cand = lo + i * _HOP_SLICE
            if cand not in used:
                start = cand
                break
    end = min(start + _HOP_SLICE - 1, hi)
    spec["port_range"] = f"{start}:{end}"
    tunnel.spec = spec
    flag_modified(tunnel, "spec")
    logger.info(
        f"[port-alloc] tunnel {tunnel.id} (mport_hop) port_range={spec['port_range']} "
        f"({_HOP_SLICE} ports, used_starts={sorted(used)}) nodes={sorted(ends)}"
    )
    return True


async def _ports_claimed_in_db(db, node_id: str, exclude_id: str) -> Set[int]:
    """UDP ports other active tunnels on this node already say they use."""
    used: Set[int] = set()
    result = await db.execute(select(Tunnel).where(Tunnel.status == "active"))
    for t in result.scalars().all():
        if t.id == exclude_id:
            continue
        if node_id not in {n for n in (_iran_node_of(t), t.foreign_node_id, t.node_id) if n}:
            continue
        spec = t.spec or {}
        for key in ("listen_port", "target_port"):
            v = spec.get(key)
            if v is not None and str(v).isdigit():
                used.add(int(v))
        for v in (spec.get("ports") or []):
            if str(v).isdigit():
                used.add(int(v))
    return used


async def pick_free_listen_port(client, db, node_id: str, preferred: int, exclude_id: str,
                                probe: int = 300, current: Optional[int] = None) -> tuple:
    """Return (port, note) — `preferred` if free on this node, else the nearest free one.

    Free means: no other active tunnel in the DB claims it on this node, AND
    nothing is actually bound to it there right now. The second check is what
    the DB cannot do — a port is usually held by another tunnel's *carrier*
    (rathole for awg_ws, udp2raw for fec_faketcp, WireGuard itself) rather than
    recorded as that tunnel's port. That is exactly how zapret and mport_hop
    ended up trying to bind the same 8863 a rathole already owned.

    `note` is empty when `preferred` was used, otherwise a sentence saying what
    was picked and why, meant to be surfaced to the operator.

    `current` is the port the tunnel already listens on (spec.listen_port). It is
    kept whenever nothing else claims it, even when `preferred` has meanwhile
    become free: clients are configured with it. A relay holding it counts as
    the tunnel's own. Without this, re-applying a running tunnel saw its own
    relay on e.g. 8864, moved it to 8865, and broke every client.
    """
    claimed = await _ports_claimed_in_db(db, node_id, exclude_id)
    live = set()
    owners = {}
    try:
        res = await client.send_to_node(node_id, "/api/agent/ports/used", {})
        if isinstance(res, dict) and res.get("status") == "success":
            for p, who in (res.get("udp") or {}).items():
                live.add(int(p))
                owners[int(p)] = who
    except Exception as e:  # noqa: BLE001
        # Cannot ask the node (older build / unreachable): fall back to DB-only.
        logger.info(f"[port-alloc] ports/used unavailable on node {node_id}: {e}")

    try:
        current = int(current) if current not in (None, "") else None
    except (TypeError, ValueError):
        current = None
    if current and current not in claimed:
        holder = (owners.get(current) or {}).get("proc")
        if current not in live or holder == "smite-udp-relay":
            return current, ""

    used = claimed | live
    if preferred not in used:
        return preferred, ""

    holder = owners.get(preferred) or {}
    who = f" (held by {holder.get('proc')} pid {holder.get('pid')})" if holder.get("proc") else ""
    for cand in range(preferred + 1, min(preferred + probe, 65535)):
        if cand not in used:
            note = (
                f"UDP {preferred} is already in use on this node{who}; "
                f"this tunnel listens on {cand} instead. Point clients at port {cand}."
            )
            logger.info(f"[port-alloc] node {node_id}: {note}")
            return cand, note
    return preferred, f"UDP {preferred} is in use on this node{who} and no free port was found nearby."


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
        foreign_id = foreign_node.id if foreign_node is not None else tunnel.foreign_node_id
        # The listener lives on the foreign node, so allocate as soon as either
        # end is known rather than requiring the iran side.
        if iran_id or foreign_id:
            preferred = _preferred_control_port(tunnel)
            used = await _used_control_ports(db, iran_id, foreign_id, tunnel.id)
            port = _pick(int(preferred), used, _CONTROL_WINDOWS[core])
            spec["control_port"] = port
            changed = True
            logger.info(
                f"[port-alloc] tunnel {tunnel.id} ({core}) control_port={port} "
                f"(preferred={preferred}, used={sorted(used)}) "
                f"iran={iran_id} foreign={foreign_id}"
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
