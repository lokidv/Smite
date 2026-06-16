"""Tunnels API endpoints"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from datetime import datetime
from pydantic import BaseModel
import logging
import time

from app.database import get_db
from app.models import Tunnel, Node
from app.node_client import NodeClient


router = APIRouter()
logger = logging.getLogger(__name__)


class RestartRequest(BaseModel):
    tunnel_ids: List[str]


class AutoRestartRequest(BaseModel):
    minutes: int


@router.post("/restart")
async def restart_tunnels(req: RestartRequest):
    """Restart (re-apply) several tunnels on demand. Returns how many succeeded."""
    from app.tunnel_reapply_manager import tunnel_reapply_manager
    applied, failed = await tunnel_reapply_manager.reapply_tunnels(req.tunnel_ids)
    return {"status": "done", "applied": applied, "failed": failed}


@router.post("/{tunnel_id}/restart")
async def restart_tunnel(tunnel_id: str):
    """Restart (re-apply) a single tunnel on demand."""
    from app.tunnel_reapply_manager import tunnel_reapply_manager
    applied, failed = await tunnel_reapply_manager.reapply_tunnels([tunnel_id])
    if applied == 0:
        raise HTTPException(
            status_code=502,
            detail="Restart failed (node unreachable or tunnel inactive). Check the node connection.",
        )
    return {"status": "restarted", "applied": applied, "failed": failed}


@router.put("/{tunnel_id}/auto-restart")
async def set_auto_restart(tunnel_id: str, req: AutoRestartRequest, db: AsyncSession = Depends(get_db)):
    """Set a per-tunnel scheduled restart in minutes (0 disables)."""
    from sqlalchemy.orm.attributes import flag_modified
    result = await db.execute(select(Tunnel).where(Tunnel.id == tunnel_id))
    tunnel = result.scalar_one_or_none()
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    minutes = max(0, int(req.minutes))
    spec = dict(tunnel.spec or {})
    spec["auto_restart_minutes"] = minutes
    tunnel.spec = spec
    flag_modified(tunnel, "spec")
    await db.commit()
    return {"status": "ok", "auto_restart_minutes": minutes}


def prepare_frp_spec_for_node(spec: dict, node: Node, request: Request) -> dict:
    """Prepare FRP spec for node by determining correct server_addr from node metadata"""
    spec_for_node = spec.copy()
    bind_port = spec_for_node.get("bind_port", 7000)
    token = spec_for_node.get("token")
    
    panel_address = node.node_metadata.get("panel_address", "")
    panel_host = None
    
    if panel_address:
        if "://" in panel_address:
            panel_address = panel_address.split("://", 1)[1]
        if ":" in panel_address:
            panel_host = panel_address.split(":")[0]
        else:
            panel_host = panel_address
    
    if not panel_host or panel_host in ["localhost", "127.0.0.1", "::1", "0.0.0.0"]:
        panel_host = spec_for_node.get("panel_host")
        if panel_host:
            if "://" in panel_host:
                panel_host = panel_host.split("://", 1)[1]
            if ":" in panel_host:
                panel_host = panel_host.split(":")[0]
    
    if not panel_host or panel_host in ["localhost", "127.0.0.1", "::1", "0.0.0.0"]:
        forwarded_host = request.headers.get("X-Forwarded-Host")
        if forwarded_host:
            panel_host = forwarded_host.split(":")[0] if ":" in forwarded_host else forwarded_host
    
    if not panel_host or panel_host in ["localhost", "127.0.0.1", "::1", "0.0.0.0"]:
        request_host = request.url.hostname if request.url else None
        if request_host and request_host not in ["localhost", "127.0.0.1", "::1", "0.0.0.0", ""]:
            panel_host = request_host
    
    if not panel_host or panel_host in ["localhost", "127.0.0.1", "::1", "0.0.0.0"]:
        import os
        panel_public_ip = os.getenv("PANEL_PUBLIC_IP") or os.getenv("PANEL_IP")
        if panel_public_ip and panel_public_ip not in ["localhost", "127.0.0.1", "::1", "0.0.0.0", ""]:
            panel_host = panel_public_ip
    
    if not panel_host or panel_host in ["localhost", "127.0.0.1", "::1", "0.0.0.0", ""]:
        error_details = {
            "node_id": node.id,
            "node_name": node.name,
            "node_metadata_panel_address": panel_address,
            "node_metadata_keys": list(node.node_metadata.keys()),
            "request_hostname": request.url.hostname if request.url else None,
            "x_forwarded_host": request.headers.get("X-Forwarded-Host"),
            "env_panel_public_ip": os.getenv("PANEL_PUBLIC_IP"),
            "env_panel_ip": os.getenv("PANEL_IP"),
        }
        error_msg = f"Cannot determine panel address for FRP tunnel. Details: {error_details}. Please ensure node has correct PANEL_ADDRESS configured (node should register with panel_address in metadata) or set PANEL_PUBLIC_IP environment variable on panel."
        logger.error(error_msg)
        raise ValueError(error_msg)
    
    from app.utils import is_valid_ipv6_address
    if is_valid_ipv6_address(panel_host):
        server_addr = f"[{panel_host}]"
    else:
        server_addr = panel_host
    
    spec_for_node["server_addr"] = server_addr
    spec_for_node["server_port"] = int(bind_port)
    if token:
        spec_for_node["token"] = token
    
    logger.info(f"FRP spec prepared: server_addr={server_addr}, server_port={bind_port}, token={'set' if token else 'none'}, panel_host={panel_host} (from node panel_address: {panel_address})")
    return spec_for_node


class TunnelCreate(BaseModel):
    name: str
    core: str
    type: str
    node_id: str | None = None
    foreign_node_id: str | None = None  # For reverse tunnels: foreign node (server side)
    iran_node_id: str | None = None  # For reverse tunnels: iran node (client side)
    spec: dict


class TunnelUpdate(BaseModel):
    name: str | None = None
    spec: dict | None = None
    core: str | None = None
    type: str | None = None


class TunnelResponse(BaseModel):
    id: str
    name: str
    core: str
    type: str
    node_id: str
    foreign_node_id: str | None = None
    iran_node_id: str | None = None
    spec: dict
    status: str
    error_message: str | None = None
    revision: int
    used_mb: float = 0.0
    quota_mb: float = 0.0
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


def parse_ports_from_spec(spec: dict) -> list:
    """Parse ports from spec - supports both comma-separated string and list formats"""
    ports = spec.get("ports", [])
    if isinstance(ports, str):
        # Comma-separated string: "8080,8081,8082"
        ports = [int(p.strip()) for p in ports.split(",") if p.strip().isdigit()]
    elif isinstance(ports, list) and ports:
        # List of numbers or strings
        ports = [int(p) if isinstance(p, (int, str)) and str(p).isdigit() else p for p in ports]
    return ports if ports else []


def normalize_zapret_spec(spec: dict) -> dict:
    """Apply zapret defaults so the node always receives a complete spec."""
    s = dict(spec or {})
    s.setdefault("filter_tcp", "443")
    s.setdefault("filter_l7", "tls")
    s.setdefault("desync_mode", s.get("type") or "fake")
    s.setdefault("desync_fooling", "badseq,ts")
    s.setdefault("max_pkt", 10)
    s.setdefault("direction", "both")
    return s


def normalize_snispoof_spec(spec: dict) -> dict:
    """Apply snispoof (xray front proxy + zapret) defaults.

    Auto-generates a stable inbound UUID the first time so the local VLESS
    inbound credentials never change across re-applies.
    """
    import uuid as uuid_mod
    s = dict(spec or {})
    s.setdefault("listen_addr", "127.0.0.1")
    if not s.get("inbound_uuid"):
        s["inbound_uuid"] = str(uuid_mod.uuid4())
    s.setdefault("front_port", 443)
    s.setdefault("ws_path", "/")
    # zapret desync sub-settings (decoy SNI stays editable)
    s.setdefault("desync_mode", "fake")
    s.setdefault("fake_tls_sni", "hcaptcha.com")
    s.setdefault("desync_fooling", "badseq,ts")
    s.setdefault("max_pkt", 10)
    return s


def normalize_warp_spec(spec: dict) -> dict:
    """Apply WARP-MASQUE egress (usque SOCKS5) defaults.

    Single-node core: runs `usque socks` on one node (normally the foreign
    server) so a co-located proxy can egress through Cloudflare WARP over MASQUE,
    hiding the server's real IP. Bound to 127.0.0.1 by default (local-only).
    """
    s = dict(spec or {})
    s.setdefault("listen_addr", "127.0.0.1")
    s.setdefault("listen_port", 1080)
    # Empty SNI -> usque default (consumer-masque...); a custom domain can dodge SNI blocks.
    s.setdefault("sni", "")
    return s


def normalize_hysteria2_spec(spec: dict) -> dict:
    """Apply Hysteria2 carrier defaults + auto-generate secrets.

    Hysteria2 is a dual-node QUIC carrier: the iran node forwards public TCP/UDP
    ports to a service on the foreign node (e.g. its local WireGuard UDP port or
    a V2Ray TCP port) through an obfuscated QUIC session. We generate a strong
    shared auth password and a Salamander obfs password once, so the values stay
    stable across re-applies. Set obfs_password to "off" to disable obfuscation.
    """
    from app.utils import generate_token
    s = dict(spec or {})
    s.setdefault("type", "udp")  # WireGuard carrier is the headline use-case
    s.setdefault("target_host", "127.0.0.1")
    s.setdefault("control_port", 443)  # QUIC port on the foreign node (looks like HTTP/3)
    s.setdefault("sni", "www.bing.com")
    if not s.get("auth") and not s.get("password") and not s.get("token"):
        s["auth"] = generate_token(24)
    if s.get("obfs_password") is None:
        s["obfs_password"] = generate_token(16)  # Salamander on by default
    return s


def build_hysteria2_specs(spec: dict, tunnel_id: str, ttype: str, iran_ip: str, foreign_ip: str):
    """Build (iran_spec, foreign_spec, resolved) for a Hysteria2 carrier.

    Topology (same inversion as udp2raw): FOREIGN = hysteria SERVER (QUIC
    listener that dials the local target service), IRAN = hysteria CLIENT (the
    public TCP/UDP forward listeners users connect to). server_spec -> iran,
    client_spec -> foreign, matching every other reverse core's send sites.

    ``resolved`` carries the secrets/ports the caller should persist on the
    tunnel so re-applies reuse the same auth/obfs/ports.
    """
    import hashlib
    from app.utils import generate_token, format_address_port

    s = dict(spec or {})
    ttype = (ttype or s.get("type") or "udp").lower()
    if ttype not in ("tcp", "udp", "both"):
        ttype = "udp"

    auth = s.get("auth") or s.get("password") or s.get("token") or generate_token(24)
    obfs = s.get("obfs_password")
    if obfs is None:
        obfs = generate_token(16)
    elif str(obfs).strip().lower() in ("off", "none", "false", "0", ""):
        obfs = ""
    sni = (s.get("sni") or "www.bing.com").strip() or "www.bing.com"

    port_hash = int(hashlib.md5(tunnel_id.encode()).hexdigest()[:8], 16)
    control_port = int(s.get("control_port") or 443)
    target_host = s.get("target_host", "127.0.0.1")

    ports = parse_ports_from_spec(s)
    if not ports:
        single = s.get("listen_port") or s.get("public_port")
        if single and str(single).isdigit():
            ports = [int(single)]

    explicit_target = s.get("target_port")
    forwards = []
    for p in ports:
        try:
            pub = int(p)
        except (TypeError, ValueError):
            continue
        if explicit_target and len(ports) == 1:
            try:
                tgt = int(explicit_target)
            except (TypeError, ValueError):
                tgt = pub
        else:
            tgt = pub
        forwards.append({"listen": f"0.0.0.0:{pub}", "remote": f"{target_host}:{tgt}", "protocol": ttype})

    iran_spec = dict(s)
    iran_spec.update({
        "mode": "client",
        "type": ttype,
        "server_addr": format_address_port(foreign_ip, control_port),
        "sni": sni,
        "auth": auth,
        "obfs_password": obfs,
        "forwards": forwards,
    })

    foreign_spec = dict(s)
    foreign_spec.update({
        "mode": "server",
        "type": ttype,
        "listen_port": control_port,
        "control_port": control_port,
        "sni": sni,
        "auth": auth,
        "obfs_password": obfs,
    })

    resolved = {
        "auth": auth,
        "obfs_password": obfs,
        "sni": sni,
        "control_port": control_port,
        "target_host": target_host,
        "type": ttype,
        "ports": ports,
    }
    return iran_spec, foreign_spec, resolved


def normalize_tuic_spec(spec: dict) -> dict:
    """Apply TUIC carrier defaults + auto-generate secrets.

    TUIC is a second QUIC carrier (sibling of Hysteria2) for WireGuard UDP and
    V2Ray TCP. It authenticates with a uuid + password pair that we generate once
    and keep stable across re-applies, so the operator can flip a tunnel between
    Hysteria2 and TUIC for protocol diversity without re-provisioning anything.
    """
    import uuid as uuid_mod
    from app.utils import generate_token
    s = dict(spec or {})
    s.setdefault("type", "udp")  # WireGuard carrier is the headline use-case
    s.setdefault("target_host", "127.0.0.1")
    s.setdefault("control_port", 443)  # QUIC port on the foreign node (looks like HTTP/3)
    s.setdefault("sni", "www.bing.com")
    s.setdefault("udp_relay_mode", "native")
    s.setdefault("congestion_control", "bbr")
    if not s.get("uuid"):
        s["uuid"] = str(uuid_mod.uuid4())
    if not s.get("password") and not s.get("auth") and not s.get("token"):
        s["password"] = generate_token(24)
    return s


def build_tuic_specs(spec: dict, tunnel_id: str, ttype: str, iran_ip: str, foreign_ip: str):
    """Build (iran_spec, foreign_spec, resolved) for a TUIC carrier.

    Same inversion as udp2raw/hysteria2: FOREIGN = tuic-server (QUIC listener that
    dials the local target), IRAN = tuic-client (the public TCP/UDP forward
    listeners users connect to). server_spec -> iran, client_spec -> foreign,
    matching every other reverse core's send sites. ``resolved`` carries the
    uuid/password/ports to persist so re-applies reuse them.
    """
    import uuid as uuid_mod
    from app.utils import generate_token, format_address_port

    s = dict(spec or {})
    ttype = (ttype or s.get("type") or "udp").lower()
    if ttype not in ("tcp", "udp", "both"):
        ttype = "udp"

    uuid_val = s.get("uuid") or str(uuid_mod.uuid4())
    password = s.get("password") or s.get("auth") or s.get("token") or generate_token(24)
    sni = (s.get("sni") or "www.bing.com").strip() or "www.bing.com"
    udp_relay_mode = (s.get("udp_relay_mode") or "native").lower()
    if udp_relay_mode not in ("native", "quic"):
        udp_relay_mode = "native"
    congestion = (s.get("congestion_control") or "bbr").lower()

    control_port = int(s.get("control_port") or 443)
    target_host = s.get("target_host", "127.0.0.1")

    ports = parse_ports_from_spec(s)
    if not ports:
        single = s.get("listen_port") or s.get("public_port")
        if single and str(single).isdigit():
            ports = [int(single)]

    explicit_target = s.get("target_port")
    forwards = []
    for p in ports:
        try:
            pub = int(p)
        except (TypeError, ValueError):
            continue
        if explicit_target and len(ports) == 1:
            try:
                tgt = int(explicit_target)
            except (TypeError, ValueError):
                tgt = pub
        else:
            tgt = pub
        forwards.append({"listen": f"0.0.0.0:{pub}", "remote": f"{target_host}:{tgt}", "protocol": ttype})

    iran_spec = dict(s)
    iran_spec.update({
        "mode": "client",
        "type": ttype,
        "server_addr": format_address_port(foreign_ip, control_port),
        "sni": sni,
        "uuid": uuid_val,
        "password": password,
        "udp_relay_mode": udp_relay_mode,
        "congestion_control": congestion,
        "forwards": forwards,
    })

    foreign_spec = dict(s)
    foreign_spec.update({
        "mode": "server",
        "type": ttype,
        "listen_port": control_port,
        "control_port": control_port,
        "sni": sni,
        "uuid": uuid_val,
        "password": password,
    })

    resolved = {
        "uuid": uuid_val,
        "password": password,
        "sni": sni,
        "control_port": control_port,
        "target_host": target_host,
        "type": ttype,
        "udp_relay_mode": udp_relay_mode,
        "congestion_control": congestion,
        "ports": ports,
    }
    return iran_spec, foreign_spec, resolved


def build_obfs4_specs(spec: dict, tunnel_id: str, iran_ip: str, foreign_ip: str):
    """Build (iran_spec, foreign_spec, resolved) for an obfs4 TCP carrier.

    Same inversion as the QUIC carriers: FOREIGN = obfs4 server (gost proxy over
    obfs4 that dials the local target), IRAN = obfs4 client (public TCP forward
    listeners). obfs4 is TCP-only, so it carries any TCP-based V2Ray transport
    (raw/WS/gRPC/XHTTP) on a single forwarded port.

    The client needs the server's ``cert``, which only exists after the server
    starts; we leave it empty here and the create/apply flow fills it in after
    applying the foreign side and fetching the cert from the node.
    """
    from app.utils import format_address_port

    s = dict(spec or {})
    control_port = int(s.get("control_port") or 443)
    target_host = s.get("target_host", "127.0.0.1")
    iat_mode = str(s.get("iat_mode", "0"))
    if iat_mode not in ("0", "1", "2"):
        iat_mode = "0"

    ports = parse_ports_from_spec(s)
    if not ports:
        single = s.get("listen_port") or s.get("public_port")
        if single and str(single).isdigit():
            ports = [int(single)]

    explicit_target = s.get("target_port")
    forwards = []
    for p in ports:
        try:
            pub = int(p)
        except (TypeError, ValueError):
            continue
        if explicit_target and len(ports) == 1:
            try:
                tgt = int(explicit_target)
            except (TypeError, ValueError):
                tgt = pub
        else:
            tgt = pub
        forwards.append({"listen": f"0.0.0.0:{pub}", "remote": f"{target_host}:{tgt}"})

    iran_spec = dict(s)
    iran_spec.update({
        "mode": "client",
        "type": "tcp",
        "server_addr": format_address_port(foreign_ip, control_port),
        "control_port": control_port,
        "iat_mode": iat_mode,
        "forwards": forwards,
        "cert": s.get("cert", ""),  # filled in after the server starts
    })

    foreign_spec = dict(s)
    foreign_spec.update({
        "mode": "server",
        "type": "tcp",
        "listen_port": control_port,
        "control_port": control_port,
        "iat_mode": iat_mode,
    })

    resolved = {
        "control_port": control_port,
        "target_host": target_host,
        "type": "tcp",
        "iat_mode": iat_mode,
        "ports": ports,
    }
    return iran_spec, foreign_spec, resolved


# Single-node cores: run on exactly one node (no iran/foreign pair).
SINGLE_NODE_CORES = {"zapret", "snispoof", "warp"}

SINGLE_NODE_NORMALIZERS = {
    "zapret": normalize_zapret_spec,
    "snispoof": normalize_snispoof_spec,
    "warp": normalize_warp_spec,
}


# Cores that support in-place core/type change (dual-node reverse cores).
# zapret (single-node DPI bypass) and gost (panel-side forwarder) are excluded
# because their semantics/topology differ from the reverse cores.
CHANGEABLE_CORES = {"rathole", "backhaul", "chisel", "frp", "udp2raw", "trusttunnel", "hysteria2", "tuic"}

# Valid tunnel types per changeable core (first entry = default).
CORE_TYPE_OPTIONS = {
    "rathole": ["tcp", "ws", "tls"],
    "backhaul": ["tcp", "udp", "ws", "wsmux", "tcpmux"],
    "chisel": ["chisel"],
    "frp": ["tcp", "udp"],
    "udp2raw": ["faketcp", "icmp", "udp"],
    "trusttunnel": ["tcp", "udp", "both"],
    "hysteria2": ["udp", "tcp", "both"],
    "tuic": ["udp", "tcp", "both"],
}


def extract_exposed_ports(core: str, spec: dict) -> list:
    """Normalize a tunnel's exposed (public iran-side) ports + forward targets.

    Returns [{"port": int, "target_host": str, "target_port": int}, ...] so the
    same external ports can be rebuilt on a different core. Handles the
    per-core port shapes: int lists (rathole/chisel/trusttunnel),
    "443=127.0.0.1:8443" strings (backhaul), {"local","remote"} dicts (frp)
    and listen_port/target_port pairs (udp2raw).
    """
    spec = spec or {}
    default_host = spec.get("target_host") or "127.0.0.1"
    entries = []

    def add(port, t_host=None, t_port=None):
        try:
            p = int(port)
        except (TypeError, ValueError):
            return
        try:
            tp = int(t_port) if t_port is not None else p
        except (TypeError, ValueError):
            tp = p
        host = str(t_host).strip() if t_host else default_host
        entries.append({"port": p, "target_host": host or default_host, "target_port": tp})

    ports = spec.get("ports") or []
    if isinstance(ports, str):
        ports = [p.strip() for p in ports.split(",") if p.strip()]

    if core == "udp2raw":
        listen_port = spec.get("listen_port") or spec.get("public_port")
        if not listen_port and ports:
            first = ports[0]
            listen_port = first.get("local") if isinstance(first, dict) else first
        if listen_port:
            add(listen_port, spec.get("target_host"), spec.get("target_port"))
    elif ports:
        for p in ports:
            if isinstance(p, dict):
                # frp form {"local": foreign-local, "remote": iran-public}
                exposed = p.get("remote") or p.get("listen_port") or p.get("public_port") or p.get("local")
                add(exposed, p.get("target_host"), p.get("local") or p.get("target_port"))
            elif isinstance(p, str) and "=" in p:
                # backhaul form "443=127.0.0.1:8443"
                left, right = p.split("=", 1)
                t_host, t_port = None, None
                right = right.strip()
                if ":" in right:
                    t_host, t_port = right.rsplit(":", 1)
                elif right.isdigit():
                    t_port = right
                add(left.strip(), t_host, t_port)
            else:
                add(p)
    else:
        single = (
            spec.get("listen_port")
            or spec.get("public_port")
            or spec.get("remote_port")
            or spec.get("local_port")
        )
        if single:
            add(single, spec.get("target_host"), spec.get("target_port"))

    seen = set()
    unique = []
    for e in entries:
        if e["port"] not in seen:
            seen.add(e["port"])
            unique.append(e)
    return unique


def build_spec_for_core(new_core: str, new_type: str, exposed: list, tunnel_id: str) -> dict:
    """Build a fresh base spec for new_core/new_type reusing the exposed ports.

    Only the exposed ports and their forward targets are carried over; secrets
    (token/key/password) and internal control ports are re-derived by the
    create/apply spec builders (or generated here when the apply path requires
    them to pre-exist, e.g. rathole token / chisel auth).
    """
    import hashlib
    from app.utils import generate_token

    port_hash = int(hashlib.md5(tunnel_id.encode()).hexdigest()[:8], 16)
    primary = exposed[0]
    ports_int = [e["port"] for e in exposed]
    target_host = primary.get("target_host") or "127.0.0.1"

    if new_core == "backhaul":
        return {
            "transport": new_type,
            "type": new_type,
            "control_port": 3080 + (port_hash % 1000),
            "target_host": target_host,
            "ports": [
                f"{e['port']}={e.get('target_host') or '127.0.0.1'}:{e.get('target_port') or e['port']}"
                for e in exposed
            ],
        }
    if new_core == "frp":
        return {
            "type": new_type,
            "ports": [
                {"local": int(e.get("target_port") or e["port"]), "remote": e["port"]}
                for e in exposed
            ],
        }
    if new_core == "rathole":
        return {
            "transport": new_type,
            "type": new_type,
            "token": generate_token(),
            "remote_addr": f"0.0.0.0:{23333 + (port_hash % 1000)}",
            "remote_port": primary["port"],
            "ports": ports_int,
        }
    if new_core == "chisel":
        return {
            "auth": generate_token(),
            "listen_port": primary["port"],
            "ports": ports_int,
        }
    if new_core == "udp2raw":
        return {
            "raw_mode": new_type,
            "listen_port": primary["port"],
            "target_host": target_host,
            "target_port": int(primary.get("target_port") or primary["port"]),
            "ports": [primary["port"]],
        }
    if new_core == "trusttunnel":
        return {
            "transport": new_type,
            "target_host": target_host,
            "ports": ports_int,
        }
    if new_core == "hysteria2":
        return {
            "type": new_type,
            "target_host": target_host,
            "target_port": int(primary.get("target_port") or primary["port"]),
            "control_port": 443,
            "ports": ports_int,
        }
    if new_core == "tuic":
        return {
            "type": new_type,
            "target_host": target_host,
            "target_port": int(primary.get("target_port") or primary["port"]),
            "control_port": 443,
            "ports": ports_int,
        }
    raise HTTPException(status_code=400, detail=f"Unsupported core for change: {new_core}")


def stop_panel_managers_for_core(tunnel: Tunnel, request: Request):
    """Defensively stop any panel-side legacy manager process for the tunnel's core."""
    manager_attr = {
        "gost": "gost_forwarder",
        "rathole": "rathole_server_manager",
        "backhaul": "backhaul_manager",
        "chisel": "chisel_server_manager",
        "frp": "frp_server_manager",
    }.get(tunnel.core)
    if not manager_attr:
        return
    manager = getattr(request.app.state, manager_attr, None)
    if not manager:
        return
    try:
        if tunnel.core == "gost":
            manager.stop_forward(tunnel.id)
        else:
            manager.stop_server(tunnel.id)
    except Exception as e:
        logger.warning(f"Failed to stop {manager_attr} for tunnel {tunnel.id}: {e}")


async def remove_tunnel_from_all_nodes(tunnel: Tunnel, db: AsyncSession):
    """Send /api/agent/tunnels/remove to every node associated with the tunnel."""
    client = NodeClient()
    node_ids = {tunnel.node_id, tunnel.iran_node_id, tunnel.foreign_node_id}
    for node_id in node_ids:
        if not node_id:
            continue
        result = await db.execute(select(Node).where(Node.id == node_id))
        node = result.scalar_one_or_none()
        if not node:
            continue
        try:
            await client.send_to_node(
                node_id=node.id,
                endpoint="/api/agent/tunnels/remove",
                data={"tunnel_id": tunnel.id},
            )
        except Exception as e:
            logger.warning(f"Failed to remove tunnel {tunnel.id} from node {node.id}: {e}")


async def change_tunnel_core_type(
    tunnel: Tunnel,
    new_core: str | None,
    new_type: str | None,
    request: Request,
    db: AsyncSession,
) -> Tunnel:
    """Change a tunnel's core and/or type in place, preserving exposed ports.

    Validation problems raise HTTPException(400); apply failures are recorded
    on the tunnel row (status='error' + error_message) without raising so bulk
    callers can report per-tunnel results.
    """
    from sqlalchemy.orm.attributes import flag_modified

    old_core = (tunnel.core or "").lower()
    new_core = (new_core or old_core).lower()
    if old_core not in CHANGEABLE_CORES:
        raise HTTPException(status_code=400, detail=f"Tunnels with core '{old_core}' do not support in-place change")
    if new_core not in CHANGEABLE_CORES:
        raise HTTPException(status_code=400, detail=f"Core '{new_core}' does not support in-place change")

    valid_types = CORE_TYPE_OPTIONS[new_core]
    if new_type:
        new_type = new_type.lower()
        if new_type not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=f"Type '{new_type}' is not valid for core '{new_core}' (valid: {', '.join(valid_types)})",
            )
    else:
        current_type = (tunnel.type or "").lower()
        new_type = current_type if current_type in valid_types else valid_types[0]

    if new_core == old_core and new_type == (tunnel.type or "").lower():
        return tunnel

    if new_core == old_core:
        # Type-only change: keep the existing spec (secrets, advanced options)
        # and just retarget the transport/type fields.
        new_spec = dict(tunnel.spec or {})
        if new_core in ("backhaul", "rathole", "trusttunnel"):
            new_spec["transport"] = new_type
        if new_core in ("backhaul", "rathole", "frp"):
            new_spec["type"] = new_type
        if new_core == "udp2raw":
            new_spec["raw_mode"] = new_type
    else:
        exposed = extract_exposed_ports(old_core, tunnel.spec)
        if not exposed:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot determine exposed ports of tunnel '{tunnel.name}' to preserve them across the core change",
            )
        new_spec = build_spec_for_core(new_core, new_type, exposed, tunnel.id)
        # Tear down the old core everywhere before switching adapters.
        stop_panel_managers_for_core(tunnel, request)
        await remove_tunnel_from_all_nodes(tunnel, db)

    logger.info(
        f"Changing tunnel {tunnel.id} core/type: {old_core}/{tunnel.type} -> {new_core}/{new_type}, "
        f"spec ports preserved: {new_spec.get('ports') or new_spec.get('listen_port')}"
    )

    tunnel.core = new_core
    tunnel.type = new_type
    tunnel.spec = new_spec
    tunnel.revision += 1
    tunnel.updated_at = datetime.utcnow()
    flag_modified(tunnel, "spec")
    await db.commit()
    await db.refresh(tunnel)

    try:
        await apply_tunnel(tunnel.id, request, db)
    except HTTPException as e:
        logger.error(f"Failed to apply tunnel {tunnel.id} after core/type change: {e.detail}")
    except Exception as e:
        logger.error(f"Failed to apply tunnel {tunnel.id} after core/type change: {e}", exc_info=True)
        tunnel.status = "error"
        tunnel.error_message = f"Apply error after core/type change: {e}"
        await db.commit()

    await db.refresh(tunnel)
    return tunnel


async def resolve_single_node(db_tunnel: Tunnel, db: AsyncSession):
    """Resolve the single node a single-node tunnel runs on (any of node/iran/foreign)."""
    candidates = [
        db_tunnel.node_id,
        getattr(db_tunnel, "iran_node_id", None),
        getattr(db_tunnel, "foreign_node_id", None),
    ]
    for nid in candidates:
        if nid:
            result = await db.execute(select(Node).where(Node.id == nid))
            node = result.scalar_one_or_none()
            if node:
                return node
    return None


async def apply_singlenode_tunnel(db_tunnel: Tunnel, db: AsyncSession) -> Tunnel:
    """Push a single-node tunnel (zapret, snispoof) to its node.

    These are not reverse tunnels: they run on one host (nfqws + NFQUEUE rules,
    optionally an xray front proxy), so they bypass the dual-node orchestration.
    """
    core = db_tunnel.core
    node = await resolve_single_node(db_tunnel, db)
    if not node:
        db_tunnel.status = "error"
        db_tunnel.error_message = f"{core} requires a node. Select the server that runs the proxy / outbound TLS."
        await db.commit()
        await db.refresh(db_tunnel)
        return db_tunnel

    normalizer = SINGLE_NODE_NORMALIZERS.get(core, lambda s: dict(s or {}))
    spec_for_node = normalizer(db_tunnel.spec)

    # Persist normalized fields (e.g. the auto-generated snispoof inbound_uuid)
    # so re-applies and the UI always see the same values.
    if spec_for_node != (db_tunnel.spec or {}):
        from sqlalchemy.orm.attributes import flag_modified
        db_tunnel.spec = spec_for_node
        flag_modified(db_tunnel, "spec")

    if not node.node_metadata.get("api_address"):
        node.node_metadata["api_address"] = (
            f"http://{node.node_metadata.get('ip_address', node.fingerprint)}:{node.node_metadata.get('api_port', 8888)}"
        )
        await db.commit()

    client = NodeClient()
    try:
        response = await client.send_to_node(
            node_id=node.id,
            endpoint="/api/agent/tunnels/apply",
            data={
                "tunnel_id": db_tunnel.id,
                "core": db_tunnel.core,
                "type": db_tunnel.type,
                "spec": spec_for_node,
            },
        )
    except Exception as e:
        logger.error(f"{core} tunnel {db_tunnel.id}: failed to reach node {node.id}: {e}", exc_info=True)
        db_tunnel.status = "error"
        db_tunnel.error_message = f"Node error: {e}"
        await db.commit()
        await db.refresh(db_tunnel)
        return db_tunnel

    if response.get("status") == "success":
        db_tunnel.status = "active"
        db_tunnel.error_message = None
        logger.info(f"{core} tunnel {db_tunnel.id} applied on node {node.id}")
    else:
        db_tunnel.status = "error"
        db_tunnel.error_message = f"Node error: {response.get('message', 'Unknown error from node')}"
        logger.error(f"{core} tunnel {db_tunnel.id}: node returned error: {db_tunnel.error_message}")

    await db.commit()
    await db.refresh(db_tunnel)
    return db_tunnel


# Backwards-compatible alias (zapret was the first single-node core).
apply_zapret_tunnel = apply_singlenode_tunnel


async def apply_obfs4_tunnel(db_tunnel: Tunnel, foreign_node, iran_node, db: AsyncSession, client) -> Tunnel:
    """Apply an obfs4 dual-node carrier with the required two-phase cert exchange.

    obfs4's cert is generated by the server at startup, so unlike the other
    reverse cores we must: (1) apply the FOREIGN server, (2) read its cert from
    the node, (3) apply the IRAN client with that cert. The cert is persisted in
    the tunnel spec so re-applies and resets reuse the same (stable) state-dir.
    """
    from sqlalchemy.orm.attributes import flag_modified

    ttype = (db_tunnel.type or "tcp").lower()
    ports = parse_ports_from_spec(db_tunnel.spec)
    if not ports:
        single = (db_tunnel.spec or {}).get("listen_port") or (db_tunnel.spec or {}).get("public_port")
        if single and str(single).isdigit():
            ports = [int(single)]
    if not ports:
        db_tunnel.status = "error"
        db_tunnel.error_message = "obfs4 requires ports (public ports on the iran node)"
        await db.commit(); await db.refresh(db_tunnel)
        return db_tunnel

    foreign_ip = foreign_node.node_metadata.get("ip_address")
    iran_ip = iran_node.node_metadata.get("ip_address")
    if not foreign_ip:
        db_tunnel.status = "error"
        db_tunnel.error_message = "Foreign node has no IP address"
        await db.commit(); await db.refresh(db_tunnel)
        return db_tunnel

    db_tunnel.spec["ports"] = ports
    iran_spec, foreign_spec, resolved = build_obfs4_specs(
        db_tunnel.spec, db_tunnel.id, iran_ip or "", foreign_ip
    )

    for node in (foreign_node, iran_node):
        if not node.node_metadata.get("api_address"):
            node.node_metadata["api_address"] = (
                f"http://{node.node_metadata.get('ip_address', node.fingerprint)}:{node.node_metadata.get('api_port', 8888)}"
            )
            await db.commit()

    # Phase 1: foreign obfs4 server (generates the cert).
    foreign_resp = await client.send_to_node(
        node_id=foreign_node.id,
        endpoint="/api/agent/tunnels/apply",
        data={"tunnel_id": db_tunnel.id, "core": "obfs4", "type": ttype, "spec": foreign_spec},
    )
    if foreign_resp.get("status") == "error":
        db_tunnel.status = "error"
        db_tunnel.error_message = f"Foreign node error: {foreign_resp.get('message', 'unknown')}"
        await db.commit(); await db.refresh(db_tunnel)
        return db_tunnel

    # Phase 2: read the cert back from the foreign node (retry briefly).
    cert = (db_tunnel.spec or {}).get("cert") or ""
    import asyncio as _asyncio
    for _ in range(8):
        cert_resp = await client.send_to_node(
            node_id=foreign_node.id,
            endpoint="/api/agent/obfs4/cert",
            data={"tunnel_id": db_tunnel.id},
        )
        if cert_resp.get("status") == "success" and cert_resp.get("ok") and cert_resp.get("cert"):
            cert = cert_resp["cert"]
            break
        await _asyncio.sleep(0.5)
    if not cert:
        db_tunnel.status = "error"
        db_tunnel.error_message = "obfs4: could not obtain server cert from foreign node"
        await db.commit(); await db.refresh(db_tunnel)
        return db_tunnel

    iran_spec["cert"] = cert

    # Phase 3: iran obfs4 client (public TCP listeners) using the cert.
    iran_resp = await client.send_to_node(
        node_id=iran_node.id,
        endpoint="/api/agent/tunnels/apply",
        data={"tunnel_id": db_tunnel.id, "core": "obfs4", "type": ttype, "spec": iran_spec},
    )
    if iran_resp.get("status") == "error":
        db_tunnel.status = "error"
        db_tunnel.error_message = f"Iran node error: {iran_resp.get('message', 'unknown')}"
        try:
            await client.send_to_node(
                node_id=foreign_node.id, endpoint="/api/agent/tunnels/remove",
                data={"tunnel_id": db_tunnel.id},
            )
        except Exception:
            pass
        await db.commit(); await db.refresh(db_tunnel)
        return db_tunnel

    db_tunnel.spec["cert"] = cert
    for k in ("control_port", "target_host", "iat_mode", "ports"):
        db_tunnel.spec[k] = resolved[k]
    flag_modified(db_tunnel, "spec")
    db_tunnel.status = "active"
    db_tunnel.error_message = None
    await db.commit(); await db.refresh(db_tunnel)
    logger.info(f"obfs4 tunnel {db_tunnel.id} applied (foreign server + iran client)")
    return db_tunnel


@router.post("", response_model=TunnelResponse)
async def create_tunnel(tunnel: TunnelCreate, request: Request, db: AsyncSession = Depends(get_db)):
    """Create a new tunnel and auto-apply it"""
    from app.node_client import NodeClient
    
    logger.info(f"Creating tunnel: name={tunnel.name}, type={tunnel.type}, core={tunnel.core}, node_id={tunnel.node_id}")
    
    if tunnel.spec and tunnel.core == "backhaul":
        ports_received = tunnel.spec.get("ports", [])
        logger.info(f"Backhaul tunnel creation: received ports from frontend: {ports_received} (type: {type(ports_received)}, length: {len(ports_received) if isinstance(ports_received, list) else 'N/A'})")
    
    if tunnel.spec and tunnel.core != "backhaul":
        ports = parse_ports_from_spec(tunnel.spec)
        if ports:
            tunnel.spec["ports"] = ports
    
    is_reverse_tunnel = tunnel.core in {"rathole", "backhaul", "chisel", "frp", "udp2raw", "trusttunnel", "hysteria2", "tuic", "obfs4"}
    foreign_node = None
    iran_node = None
    
    if is_reverse_tunnel:
        foreign_node_id_val = tunnel.foreign_node_id if tunnel.foreign_node_id and (not isinstance(tunnel.foreign_node_id, str) or tunnel.foreign_node_id.strip()) else None
        if foreign_node_id_val:
            result = await db.execute(select(Node).where(Node.id == foreign_node_id_val))
            foreign_node = result.scalar_one_or_none()
            if not foreign_node:
                raise HTTPException(status_code=404, detail=f"Foreign node {foreign_node_id_val} not found")
            if foreign_node.node_metadata.get("role") != "foreign":
                raise HTTPException(status_code=400, detail=f"Node {foreign_node_id_val} is not a foreign node")
        
        iran_node_id_val = tunnel.iran_node_id if tunnel.iran_node_id and (not isinstance(tunnel.iran_node_id, str) or tunnel.iran_node_id.strip()) else None
        if iran_node_id_val:
            result = await db.execute(select(Node).where(Node.id == iran_node_id_val))
            iran_node = result.scalar_one_or_none()
            if not iran_node:
                raise HTTPException(status_code=404, detail=f"Iran node {iran_node_id_val} not found")
            if iran_node.node_metadata.get("role") != "iran":
                raise HTTPException(status_code=400, detail=f"Node {iran_node_id_val} is not an iran node")
        
        node_id_val = tunnel.node_id if tunnel.node_id and (not isinstance(tunnel.node_id, str) or tunnel.node_id.strip()) else None
        if node_id_val and not (foreign_node and iran_node):
            result = await db.execute(select(Node).where(Node.id == node_id_val))
            provided_node = result.scalar_one_or_none()
            if not provided_node:
                raise HTTPException(status_code=404, detail="Node not found")
            
            node_role = provided_node.node_metadata.get("role", "iran")
            if node_role == "foreign":
                foreign_node = provided_node
                result = await db.execute(select(Node))
                all_nodes = result.scalars().all()
                iran_nodes = [n for n in all_nodes if n.node_metadata and n.node_metadata.get("role") == "iran"]
                if iran_nodes:
                    iran_node = iran_nodes[0]
                else:
                    raise HTTPException(status_code=400, detail="No iran node found. Please specify iran_node_id or register an iran node.")
            else:
                iran_node = provided_node
                result = await db.execute(select(Node))
                all_nodes = result.scalars().all()
                foreign_nodes = [n for n in all_nodes if n.node_metadata and n.node_metadata.get("role") == "foreign"]
                if foreign_nodes:
                    foreign_node = foreign_nodes[0]
                else:
                    raise HTTPException(status_code=400, detail="No foreign node found. Please specify foreign_node_id or register a foreign node.")
        
        if not foreign_node or not iran_node:
            raise HTTPException(status_code=400, detail=f"Both foreign and iran nodes are required for {tunnel.core.title()} tunnels. Provide foreign_node_id and iran_node_id, or provide node_id and we'll find the matching node.")
        
        node = iran_node
    else:
        node = None
        if tunnel.node_id or tunnel.iran_node_id:
            node_id_to_check = tunnel.iran_node_id or tunnel.node_id
            result = await db.execute(select(Node).where(Node.id == node_id_to_check))
            node = result.scalar_one_or_none()
    
    tunnel_node_id = tunnel.iran_node_id or tunnel.node_id or ""
    
    foreign_node_id_to_store = foreign_node.id if foreign_node else None
    iran_node_id_to_store = iran_node.id if iran_node else None
    
    db_tunnel = Tunnel(
        name=tunnel.name,
        core=tunnel.core,
        type=tunnel.type,
        node_id=tunnel_node_id,
        foreign_node_id=foreign_node_id_to_store,
        iran_node_id=iran_node_id_to_store,
        spec=tunnel.spec,
        status="pending"
    )
    db.add(db_tunnel)
    await db.commit()
    await db.refresh(db_tunnel)
    
    try:
        if db_tunnel.core in SINGLE_NODE_CORES:
            return await apply_singlenode_tunnel(db_tunnel, db)

        needs_gost_forwarding = db_tunnel.type in ["tcp", "udp", "ws", "grpc", "tcpmux"] and db_tunnel.core == "gost" and not is_reverse_tunnel
        needs_rathole_server = False
        needs_backhaul_server = False
        needs_chisel_server = False
        needs_frp_server = False
        needs_node_apply = db_tunnel.core in {"rathole", "backhaul", "chisel", "frp"}
        
        logger.info(
            "Tunnel %s: gost=%s, rathole=%s, backhaul=%s, chisel=%s, frp=%s",
            db_tunnel.id,
            needs_gost_forwarding,
            needs_rathole_server,
            needs_backhaul_server,
            needs_chisel_server,
            needs_frp_server,
        )
        
        if is_reverse_tunnel and foreign_node and iran_node:
            client = NodeClient()

            # obfs4 needs a two-phase (server-first, fetch cert, then client)
            # apply, so it has its own helper instead of the symmetric sender.
            if db_tunnel.core == "obfs4":
                return await apply_obfs4_tunnel(db_tunnel, foreign_node, iran_node, db, client)

            server_spec = db_tunnel.spec.copy() if db_tunnel.spec else {}
            server_spec["mode"] = "server"
            
            if "ports" in db_tunnel.spec and "ports" not in server_spec:
                server_spec["ports"] = db_tunnel.spec.get("ports", [])
            
            client_spec = db_tunnel.spec.copy() if db_tunnel.spec else {}
            client_spec["mode"] = "client"
            
            if db_tunnel.core == "rathole":
                transport = server_spec.get("transport") or server_spec.get("type") or "tcp"
                token = server_spec.get("token")
                if not token:
                    from app.utils import generate_token
                    token = generate_token()
                    server_spec["token"] = token
                    db_tunnel.spec["token"] = token
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(db_tunnel, "spec")

                # WireGuard Stealth: rathole over native TLS with a fake SNI.
                # Generate the cert once and persist it so re-applies/benchmarks
                # keep using the same identity on both nodes.
                if (transport or "tcp").lower() == "tls":
                    from app.tls_utils import ensure_wg_stealth_materials
                    ensure_wg_stealth_materials(db_tunnel.spec, db_tunnel.spec.get("sni"))
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(db_tunnel, "spec")
                    for _k in ("tls_pkcs12_b64", "tls_pkcs12_password", "tls_ca_pem_b64", "sni", "service_type"):
                        if _k in db_tunnel.spec:
                            server_spec[_k] = db_tunnel.spec[_k]
                            client_spec[_k] = db_tunnel.spec[_k]
                
                ports = parse_ports_from_spec(db_tunnel.spec)
                if not ports:
                    proxy_port = server_spec.get("remote_port") or server_spec.get("listen_port")
                    if proxy_port:
                        ports = [int(proxy_port) if isinstance(proxy_port, (int, str)) and str(proxy_port).isdigit() else proxy_port]
                
                if not ports:
                    db_tunnel.status = "error"
                    db_tunnel.error_message = "Rathole requires ports"
                    await db.commit()
                    await db.refresh(db_tunnel)
                    return db_tunnel
                
                remote_addr = server_spec.get("remote_addr", "0.0.0.0:23333")
                from app.utils import parse_address_port
                _, control_port, _ = parse_address_port(remote_addr)
                if not control_port:
                    import hashlib
                    port_hash = int(hashlib.md5(db_tunnel.id.encode()).hexdigest()[:8], 16)
                    control_port = 23333 + (port_hash % 1000)
                server_spec["bind_addr"] = f"0.0.0.0:{control_port}"
                server_spec["ports"] = ports
                server_spec["transport"] = transport
                server_spec["type"] = transport
                if "websocket_tls" in server_spec:
                    server_spec["websocket_tls"] = server_spec["websocket_tls"]
                elif "tls" in server_spec:
                    server_spec["websocket_tls"] = server_spec["tls"]
                
                iran_node_ip = iran_node.node_metadata.get("ip_address")
                if not iran_node_ip:
                    db_tunnel.status = "error"
                    db_tunnel.error_message = "Iran node has no IP address"
                    await db.commit()
                    await db.refresh(db_tunnel)
                    return db_tunnel
                transport_lower = transport.lower()
                if transport_lower in ("websocket", "ws"):
                    use_tls = bool(server_spec.get("websocket_tls") or server_spec.get("tls"))
                    protocol = "wss://" if use_tls else "ws://"
                    client_spec["remote_addr"] = f"{protocol}{iran_node_ip}:{control_port}"
                else:
                    client_spec["remote_addr"] = f"{iran_node_ip}:{control_port}"
                client_spec["transport"] = transport
                client_spec["type"] = transport
                client_spec["token"] = token
                client_spec["ports"] = ports  # Pass ports to client
                if "websocket_tls" in server_spec:
                    client_spec["websocket_tls"] = server_spec["websocket_tls"]
                elif "tls" in server_spec:
                    client_spec["websocket_tls"] = server_spec["tls"]
                
            elif db_tunnel.core == "chisel":
                ports = parse_ports_from_spec(db_tunnel.spec)
                if not ports:
                    listen_port = server_spec.get("listen_port") or server_spec.get("remote_port")
                    if listen_port:
                        ports = [int(listen_port) if isinstance(listen_port, (int, str)) and str(listen_port).isdigit() else listen_port]
                
                if not ports:
                    db_tunnel.status = "error"
                    db_tunnel.error_message = "Chisel requires ports"
                    await db.commit()
                    await db.refresh(db_tunnel)
                    return db_tunnel
                
                iran_node_ip = iran_node.node_metadata.get("ip_address")
                if not iran_node_ip:
                    db_tunnel.status = "error"
                    db_tunnel.error_message = "Iran node has no IP address"
                    await db.commit()
                    await db.refresh(db_tunnel)
                    return db_tunnel
                import hashlib
                port_hash = int(hashlib.md5(db_tunnel.id.encode()).hexdigest()[:8], 16)
                first_port = int(ports[0]) if isinstance(ports[0], (int, str)) and str(ports[0]).isdigit() else ports[0]
                server_control_port = server_spec.get("control_port") or (int(first_port) + 10000 + (port_hash % 1000))
                server_spec["server_port"] = server_control_port
                server_spec["reverse_port"] = first_port
                auth = server_spec.get("auth")
                if not auth:
                    from app.utils import generate_token
                    auth = generate_token()
                    server_spec["auth"] = auth
                    db_tunnel.spec["auth"] = auth
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(db_tunnel, "spec")
                server_spec["auth"] = auth
                fingerprint = server_spec.get("fingerprint")
                if fingerprint:
                    server_spec["fingerprint"] = fingerprint
                
                client_spec["server_url"] = f"http://{iran_node_ip}:{server_control_port}"
                client_spec["ports"] = ports
                client_spec["auth"] = auth
                if fingerprint:
                    client_spec["fingerprint"] = fingerprint
                
            elif db_tunnel.core == "frp":
                from app.utils import frp_safe_bind_port
                bind_port = frp_safe_bind_port(db_tunnel.id, server_spec.get("bind_port"))
                token = server_spec.get("token")
                if not token:
                    from app.utils import generate_token
                    token = generate_token()
                    server_spec["token"] = token
                    db_tunnel.spec["token"] = token
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(db_tunnel, "spec")
                server_spec["bind_port"] = bind_port
                server_spec["token"] = token
                
                iran_node_ip = iran_node.node_metadata.get("ip_address")
                if not iran_node_ip:
                    db_tunnel.status = "error"
                    db_tunnel.error_message = "Iran node has no IP address"
                    await db.commit()
                    await db.refresh(db_tunnel)
                    return db_tunnel
                client_spec["server_addr"] = iran_node_ip
                client_spec["server_port"] = bind_port
                client_spec["token"] = token
                tunnel_type = db_tunnel.type.lower() if db_tunnel.type else "tcp"
                if tunnel_type not in ["tcp", "udp"]:
                    tunnel_type = "tcp"  # Default to tcp if invalid
                client_spec["type"] = tunnel_type
                local_ip = client_spec.get("local_ip") or iran_node_ip
                
                ports = parse_ports_from_spec(db_tunnel.spec)
                if ports:
                    client_spec["ports"] = [{"local": int(p), "remote": int(p)} for p in ports]
                else:
                    local_port = client_spec.get("local_port")
                    if not local_port:
                        local_port = db_tunnel.spec.get("listen_port") or db_tunnel.spec.get("remote_port") or bind_port
                    client_spec["local_ip"] = local_ip
                    client_spec["local_port"] = local_port
                    if "remote_port" not in client_spec:
                        client_spec["remote_port"] = db_tunnel.spec.get("remote_port") or db_tunnel.spec.get("listen_port") or bind_port
                
            elif db_tunnel.core == "backhaul":
                transport = server_spec.get("transport") or server_spec.get("type") or "tcp"
                import hashlib
                port_hash = int(hashlib.md5(db_tunnel.id.encode()).hexdigest()[:8], 16)
                control_port = server_spec.get("control_port") or server_spec.get("listen_port") or (3080 + (port_hash % 1000))
                target_host = server_spec.get("target_host", "127.0.0.1")
                token = server_spec.get("token")
                if not token:
                    from app.utils import generate_token
                    token = generate_token()
                    server_spec["token"] = token
                    db_tunnel.spec["token"] = token
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(db_tunnel, "spec")
                
                ports = server_spec.get("ports", [])
                if not ports:
                    ports = db_tunnel.spec.get("ports", [])
                logger.info(f"Backhaul tunnel {db_tunnel.id}: received ports from server_spec: {server_spec.get('ports')}, from db_tunnel.spec: {db_tunnel.spec.get('ports')}, final: {ports} (type: {type(ports)}, length: {len(ports) if isinstance(ports, list) else 'N/A'})")
                
                if not ports or (isinstance(ports, list) and len(ports) == 0):
                    public_port = server_spec.get("public_port") or server_spec.get("remote_port") or server_spec.get("listen_port")
                    target_port = server_spec.get("target_port") or public_port
                    if not public_port:
                        db_tunnel.status = "error"
                        db_tunnel.error_message = "Backhaul requires ports array or public_port/remote_port"
                        await db.commit()
                        await db.refresh(db_tunnel)
                        return db_tunnel
                    if target_port:
                        target_addr = f"{target_host}:{target_port}"
                        ports = [f"{public_port}={target_addr}"]
                    else:
                        ports = [str(public_port)]
                else:
                    if isinstance(ports, list) and ports:
                        processed_ports = []
                        for p in ports:
                            if not p:
                                continue
                            if isinstance(p, str):
                                if '=' in p:
                                    processed_ports.append(p)
                                elif p.isdigit():
                                    processed_ports.append(f"{p}={target_host}:{p}")
                                else:
                                    processed_ports.append(p)
                            elif isinstance(p, int):
                                processed_ports.append(f"{p}={target_host}:{p}")
                            elif isinstance(p, dict):
                                local = p.get("local") or p.get("listen_port") or p.get("public_port")
                                tgt_host = p.get("target_host") or target_host
                                tgt_port = p.get("target_port") or p.get("remote_port") or local
                                if local:
                                    processed_ports.append(f"{local}={tgt_host}:{tgt_port}")
                            else:
                                processed_ports.append(str(p))
                        ports = processed_ports
                
                logger.info(f"Backhaul tunnel {db_tunnel.id}: processed ports: {ports} (count: {len(ports)})")
                
                bind_ip = server_spec.get("bind_ip") or server_spec.get("listen_ip") or "0.0.0.0"
                server_spec["bind_addr"] = f"{bind_ip}:{control_port}"
                server_spec["transport"] = transport
                server_spec["type"] = transport
                server_spec["ports"] = ports
                server_spec["mode"] = "server"
                server_spec["token"] = token
                
                # CRITICAL: Update the database spec with processed ports so they're preserved
                if "ports" not in db_tunnel.spec:
                    db_tunnel.spec["ports"] = []
                db_tunnel.spec["ports"] = ports.copy() if isinstance(ports, list) else ports
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(db_tunnel, "spec")
                await db.commit()
                await db.refresh(db_tunnel)
                logger.info(f"Backhaul tunnel {db_tunnel.id}: saved ports to database: {db_tunnel.spec.get('ports')} (count: {len(db_tunnel.spec.get('ports', []))})")
                
                iran_node_ip = iran_node.node_metadata.get("ip_address")
                if not iran_node_ip:
                    db_tunnel.status = "error"
                    db_tunnel.error_message = "Iran node has no IP address"
                    await db.commit()
                    await db.refresh(db_tunnel)
                    return db_tunnel
                transport_lower = transport.lower()
                if transport_lower in ("ws", "wsmux"):
                    use_tls = bool(server_spec.get("tls_cert") or server_spec.get("server_options", {}).get("tls_cert"))
                    protocol = "wss://" if use_tls else "ws://"
                    client_spec["remote_addr"] = f"{protocol}{iran_node_ip}:{control_port}"
                else:
                    client_spec["remote_addr"] = f"{iran_node_ip}:{control_port}"
                client_spec["transport"] = transport
                client_spec["type"] = transport
                client_spec["mode"] = "client"  # Ensure mode is set
                if token:
                    client_spec["token"] = token
            
            elif db_tunnel.core == "udp2raw":
                # udp2raw role mapping differs from the other reverse cores:
                # the IRAN node runs the udp2raw CLIENT (public UDP entry point that
                # wraps traffic into raw faketcp/icmp/udp packets) and the FOREIGN
                # node runs the udp2raw SERVER (unwraps and forwards to the local
                # target service). server_spec goes to iran, client_spec to foreign.
                raw_mode = (db_tunnel.type or server_spec.get("raw_mode") or "faketcp").lower()
                if raw_mode not in {"faketcp", "icmp", "udp"}:
                    raw_mode = "faketcp"
                
                key = server_spec.get("key") or server_spec.get("token")
                if not key:
                    from app.utils import generate_token
                    key = generate_token()
                
                ports = parse_ports_from_spec(db_tunnel.spec)
                listen_port = server_spec.get("listen_port") or server_spec.get("public_port") or (ports[0] if ports else None)
                if not listen_port:
                    db_tunnel.status = "error"
                    db_tunnel.error_message = "udp2raw requires listen_port (public UDP port on the iran node)"
                    await db.commit()
                    await db.refresh(db_tunnel)
                    return db_tunnel
                
                import hashlib
                port_hash = int(hashlib.md5(db_tunnel.id.encode()).hexdigest()[:8], 16)
                raw_port = server_spec.get("raw_port") or (4096 + (port_hash % 1000))
                target_host = server_spec.get("target_host", "127.0.0.1")
                target_port = server_spec.get("target_port") or listen_port
                cipher_mode = server_spec.get("cipher_mode") or "aes128cbc"
                auth_mode = server_spec.get("auth_mode") or "md5"
                
                try:
                    listen_port = int(listen_port)
                    raw_port = int(raw_port)
                    target_port = int(target_port)
                except (TypeError, ValueError):
                    db_tunnel.status = "error"
                    db_tunnel.error_message = "udp2raw ports must be numeric"
                    await db.commit()
                    await db.refresh(db_tunnel)
                    return db_tunnel
                
                foreign_node_ip = foreign_node.node_metadata.get("ip_address")
                if not foreign_node_ip:
                    db_tunnel.status = "error"
                    db_tunnel.error_message = "Foreign node has no IP address"
                    await db.commit()
                    await db.refresh(db_tunnel)
                    return db_tunnel
                
                # Persist derived values so reapply/restore reuse the same key/ports
                db_tunnel.spec["key"] = key
                db_tunnel.spec["raw_mode"] = raw_mode
                db_tunnel.spec["listen_port"] = listen_port
                db_tunnel.spec["raw_port"] = raw_port
                db_tunnel.spec["target_host"] = target_host
                db_tunnel.spec["target_port"] = target_port
                db_tunnel.spec["cipher_mode"] = cipher_mode
                db_tunnel.spec["auth_mode"] = auth_mode
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(db_tunnel, "spec")
                
                from app.utils import format_address_port
                # Iran node: udp2raw client (public UDP entry point)
                server_spec["mode"] = "client"
                server_spec["raw_mode"] = raw_mode
                server_spec["listen_addr"] = f"0.0.0.0:{listen_port}"
                server_spec["remote_addr"] = format_address_port(foreign_node_ip, raw_port)
                server_spec["key"] = key
                server_spec["cipher_mode"] = cipher_mode
                server_spec["auth_mode"] = auth_mode
                
                # Foreign node: udp2raw server (raw listener -> local target service)
                client_spec["mode"] = "server"
                client_spec["raw_mode"] = raw_mode
                client_spec["listen_addr"] = f"0.0.0.0:{raw_port}"
                client_spec["forward_addr"] = format_address_port(target_host, target_port)
                client_spec["key"] = key
                client_spec["cipher_mode"] = cipher_mode
                client_spec["auth_mode"] = auth_mode

            elif db_tunnel.core == "trusttunnel":
                # TrustTunnel (rstun, QUIC). Iran node runs rstund (server, public
                # listener); foreign node runs rstunc (client, dials in and forwards
                # to its local egress target). server_spec -> iran, client_spec -> foreign.
                transport = (db_tunnel.type or server_spec.get("transport") or "tcp").lower()
                if transport not in {"tcp", "udp", "both"}:
                    transport = "tcp"

                password = server_spec.get("password") or server_spec.get("token")
                if not password:
                    from app.utils import generate_token
                    password = generate_token(24)

                ports = parse_ports_from_spec(db_tunnel.spec)
                if not ports:
                    single = server_spec.get("listen_port") or server_spec.get("public_port") or server_spec.get("remote_port")
                    if single and str(single).isdigit():
                        ports = [int(single)]
                if not ports:
                    db_tunnel.status = "error"
                    db_tunnel.error_message = "TrustTunnel requires ports (public ports on the iran node)"
                    await db.commit()
                    await db.refresh(db_tunnel)
                    return db_tunnel

                import hashlib
                port_hash = int(hashlib.md5(db_tunnel.id.encode()).hexdigest()[:8], 16)
                control_port = server_spec.get("control_port") or (6100 + (port_hash % 800))
                target_host = server_spec.get("target_host", "127.0.0.1")

                iran_node_ip = iran_node.node_metadata.get("ip_address")
                if not iran_node_ip:
                    db_tunnel.status = "error"
                    db_tunnel.error_message = "Iran node has no IP address"
                    await db.commit()
                    await db.refresh(db_tunnel)
                    return db_tunnel

                # Persist derived values so reapply/restore reuse the same password/ports
                db_tunnel.spec["password"] = password
                db_tunnel.spec["transport"] = transport
                db_tunnel.spec["control_port"] = control_port
                db_tunnel.spec["target_host"] = target_host
                db_tunnel.spec["ports"] = ports
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(db_tunnel, "spec")

                from app.utils import format_address_port
                # Iran node: rstund server
                server_spec["mode"] = "server"
                server_spec["transport"] = transport
                server_spec["password"] = password
                server_spec["control_port"] = control_port
                server_spec["target_host"] = target_host
                server_spec["ports"] = ports

                # Foreign node: rstunc client
                client_spec["mode"] = "client"
                client_spec["transport"] = transport
                client_spec["password"] = password
                client_spec["server_addr"] = format_address_port(iran_node_ip, control_port)
                client_spec["target_host"] = target_host
                client_spec["ports"] = ports

            elif db_tunnel.core == "hysteria2":
                # Hysteria2 QUIC carrier. FOREIGN node = hysteria SERVER (dials the
                # local target service, e.g. its WireGuard UDP port); IRAN node =
                # hysteria CLIENT (public TCP/UDP forward listeners users connect to).
                # server_spec -> iran, client_spec -> foreign.
                ttype = (db_tunnel.type or server_spec.get("type") or "udp").lower()
                ports = parse_ports_from_spec(db_tunnel.spec)
                if not ports:
                    single = server_spec.get("listen_port") or server_spec.get("public_port")
                    if single and str(single).isdigit():
                        ports = [int(single)]
                if not ports:
                    db_tunnel.status = "error"
                    db_tunnel.error_message = "Hysteria2 requires ports (public ports on the iran node)"
                    await db.commit()
                    await db.refresh(db_tunnel)
                    return db_tunnel

                foreign_node_ip = foreign_node.node_metadata.get("ip_address")
                if not foreign_node_ip:
                    db_tunnel.status = "error"
                    db_tunnel.error_message = "Foreign node has no IP address"
                    await db.commit()
                    await db.refresh(db_tunnel)
                    return db_tunnel
                iran_node_ip = iran_node.node_metadata.get("ip_address")

                db_tunnel.spec["ports"] = ports
                h2_iran, h2_foreign, resolved = build_hysteria2_specs(
                    db_tunnel.spec, db_tunnel.id, ttype, iran_node_ip or "", foreign_node_ip
                )
                for k in ("auth", "obfs_password", "sni", "control_port", "target_host", "type"):
                    db_tunnel.spec[k] = resolved[k]
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(db_tunnel, "spec")
                server_spec = h2_iran
                client_spec = h2_foreign

            elif db_tunnel.core == "tuic":
                # TUIC QUIC carrier (sibling of Hysteria2). FOREIGN = tuic-server,
                # IRAN = tuic-client (public TCP/UDP forward listeners).
                # server_spec -> iran, client_spec -> foreign.
                ttype = (db_tunnel.type or server_spec.get("type") or "udp").lower()
                ports = parse_ports_from_spec(db_tunnel.spec)
                if not ports:
                    single = server_spec.get("listen_port") or server_spec.get("public_port")
                    if single and str(single).isdigit():
                        ports = [int(single)]
                if not ports:
                    db_tunnel.status = "error"
                    db_tunnel.error_message = "TUIC requires ports (public ports on the iran node)"
                    await db.commit()
                    await db.refresh(db_tunnel)
                    return db_tunnel

                foreign_node_ip = foreign_node.node_metadata.get("ip_address")
                if not foreign_node_ip:
                    db_tunnel.status = "error"
                    db_tunnel.error_message = "Foreign node has no IP address"
                    await db.commit()
                    await db.refresh(db_tunnel)
                    return db_tunnel
                iran_node_ip = iran_node.node_metadata.get("ip_address")

                db_tunnel.spec["ports"] = ports
                tuic_iran, tuic_foreign, resolved = build_tuic_specs(
                    db_tunnel.spec, db_tunnel.id, ttype, iran_node_ip or "", foreign_node_ip
                )
                for k in ("uuid", "password", "sni", "control_port", "target_host", "type", "udp_relay_mode", "congestion_control"):
                    db_tunnel.spec[k] = resolved[k]
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(db_tunnel, "spec")
                server_spec = tuic_iran
                client_spec = tuic_foreign

            if not iran_node.node_metadata.get("api_address"):
                iran_node.node_metadata["api_address"] = f"http://{iran_node.node_metadata.get('ip_address', iran_node.fingerprint)}:{iran_node.node_metadata.get('api_port', 8888)}"
                await db.commit()
            
            logger.info(f"Applying server config to iran node {iran_node.id} for tunnel {db_tunnel.id}")
            server_response = await client.send_to_node(
                node_id=iran_node.id,
                endpoint="/api/agent/tunnels/apply",
                data={
                    "tunnel_id": db_tunnel.id,
                    "core": db_tunnel.core,
                    "type": db_tunnel.type,
                    "spec": server_spec
                }
            )
            
            if server_response.get("status") == "error":
                db_tunnel.status = "error"
                error_msg = server_response.get("message", "Unknown error from iran node")
                db_tunnel.error_message = f"Iran node error: {error_msg}"
                logger.error(f"Tunnel {db_tunnel.id}: Iran node error: {error_msg}")
                await db.commit()
                await db.refresh(db_tunnel)
                return db_tunnel
            
            if not foreign_node.node_metadata.get("api_address"):
                foreign_node.node_metadata["api_address"] = f"http://{foreign_node.node_metadata.get('ip_address', foreign_node.fingerprint)}:{foreign_node.node_metadata.get('api_port', 8888)}"
                await db.commit()
            
            logger.info(f"Applying client config to foreign node {foreign_node.id} for tunnel {db_tunnel.id}")
            client_response = await client.send_to_node(
                node_id=foreign_node.id,
                endpoint="/api/agent/tunnels/apply",
                data={
                    "tunnel_id": db_tunnel.id,
                    "core": db_tunnel.core,
                    "type": db_tunnel.type,
                    "spec": client_spec
                }
            )
            
            if client_response.get("status") == "error":
                db_tunnel.status = "error"
                error_msg = client_response.get("message", "Unknown error from foreign node")
                db_tunnel.error_message = f"Foreign node error: {error_msg}"
                logger.error(f"Tunnel {db_tunnel.id}: Foreign node error: {error_msg}")
                try:
                    await client.send_to_node(
                        node_id=iran_node.id,
                        endpoint="/api/agent/tunnels/remove",
                        data={"tunnel_id": db_tunnel.id}
                    )
                except:
                    pass
                await db.commit()
                await db.refresh(db_tunnel)
                return db_tunnel
            
            if server_response.get("status") == "success" and client_response.get("status") == "success":
                db_tunnel.status = "active"
                logger.info(f"Tunnel {db_tunnel.id} successfully applied to both nodes")
            else:
                db_tunnel.status = "error"
                db_tunnel.error_message = "Failed to apply tunnel to one or both nodes"
                logger.error(f"Tunnel {db_tunnel.id}: Failed to apply to nodes")
            
            await db.commit()
            await db.refresh(db_tunnel)
            return db_tunnel
        
        
        if needs_node_apply and not is_reverse_tunnel:
            remote_addr = db_tunnel.spec.get("remote_addr")
            token = db_tunnel.spec.get("token")
            proxy_port = db_tunnel.spec.get("remote_port") or db_tunnel.spec.get("listen_port")
            use_ipv6 = db_tunnel.spec.get("use_ipv6", False)
            
            if remote_addr:
                from app.utils import parse_address_port
                _, rathole_port, _ = parse_address_port(remote_addr)
                try:
                    if rathole_port and int(rathole_port) == 8000:
                        db_tunnel.status = "error"
                        db_tunnel.error_message = "Rathole server cannot use port 8000 (panel API port). Use a different port like 23333."
                        await db.commit()
                        await db.refresh(db_tunnel)
                        return db_tunnel
                except (ValueError, TypeError):
                    pass
            
            if remote_addr and token and proxy_port and hasattr(request.app.state, 'rathole_server_manager'):
                try:
                    logger.info(f"Starting Rathole server for tunnel {db_tunnel.id}: remote_addr={remote_addr}, token=***, proxy_port={proxy_port}, use_ipv6={use_ipv6}")
                    request.app.state.rathole_server_manager.start_server(
                        tunnel_id=db_tunnel.id,
                        remote_addr=remote_addr,
                        token=token,
                        proxy_port=int(proxy_port),
                        use_ipv6=bool(use_ipv6)
                    )
                    logger.info(f"Successfully started Rathole server for tunnel {db_tunnel.id}")
                    rathole_started = True
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"Failed to start Rathole server for tunnel {db_tunnel.id}: {error_msg}", exc_info=True)
                    db_tunnel.status = "error"
                    db_tunnel.error_message = f"Rathole server error: {error_msg}"
                    await db.commit()
                    await db.refresh(db_tunnel)
                    return db_tunnel
            else:
                missing = []
                if not remote_addr:
                    missing.append("remote_addr")
                if not token:
                    missing.append("token")
                if not proxy_port:
                    missing.append("proxy_port")
                if not hasattr(request.app.state, 'rathole_server_manager'):
                    missing.append("rathole_server_manager")
                logger.warning(f"Tunnel {db_tunnel.id}: Missing required fields for Rathole server: {missing}")
                if not remote_addr or not token or not proxy_port:
                    db_tunnel.status = "error"
                    db_tunnel.error_message = f"Missing required fields for Rathole: {missing}"
                    await db.commit()
                    await db.refresh(db_tunnel)
                    return db_tunnel
        
        if needs_chisel_server:
            listen_port = db_tunnel.spec.get("listen_port") or db_tunnel.spec.get("remote_port") or db_tunnel.spec.get("server_port")
            auth = db_tunnel.spec.get("auth")
            fingerprint = db_tunnel.spec.get("fingerprint")
            use_ipv6 = db_tunnel.spec.get("use_ipv6", False)
            
            if listen_port:
                from app.utils import parse_address_port
                try:
                    if int(listen_port) == 8000:
                        db_tunnel.status = "error"
                        db_tunnel.error_message = "Chisel server cannot use port 8000 (panel API port). Use a different port."
                        await db.commit()
                        await db.refresh(db_tunnel)
                        return db_tunnel
                except (ValueError, TypeError):
                    pass
            
            if listen_port and hasattr(request.app.state, 'chisel_server_manager'):
                try:
                    server_control_port = db_tunnel.spec.get("control_port")
                    if server_control_port:
                        server_control_port = int(server_control_port)
                    else:
                        server_control_port = int(listen_port) + 10000
                    logger.info(f"Starting Chisel server for tunnel {db_tunnel.id}: server_control_port={server_control_port}, reverse_port={listen_port}, auth={auth is not None}, fingerprint={fingerprint is not None}, use_ipv6={use_ipv6}")
                    request.app.state.chisel_server_manager.start_server(
                        tunnel_id=db_tunnel.id,
                        server_port=server_control_port,
                        auth=auth,
                        fingerprint=fingerprint,
                        use_ipv6=bool(use_ipv6)
                    )
                    time.sleep(1.0)
                    if not request.app.state.chisel_server_manager.is_running(db_tunnel.id):
                        raise RuntimeError("Chisel server process started but is not running")
                    chisel_started = True
                    logger.info(f"Successfully started Chisel server for tunnel {db_tunnel.id}")
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"Failed to start Chisel server for tunnel {db_tunnel.id}: {error_msg}", exc_info=True)
                    db_tunnel.status = "error"
                    db_tunnel.error_message = f"Chisel server error: {error_msg}"
                    await db.commit()
                    await db.refresh(db_tunnel)
                    return db_tunnel
            else:
                missing = []
                if not listen_port:
                    missing.append("listen_port")
                if not hasattr(request.app.state, 'chisel_server_manager'):
                    missing.append("chisel_server_manager")
                logger.warning(f"Tunnel {db_tunnel.id}: Missing required fields for Chisel server: {missing}")
                if not listen_port:
                    db_tunnel.status = "error"
                    db_tunnel.error_message = f"Missing required fields for Chisel: {missing}"
                    await db.commit()
                    await db.refresh(db_tunnel)
                    return db_tunnel
        
        if needs_frp_server:
            bind_port = db_tunnel.spec.get("bind_port", 7000)
            token = db_tunnel.spec.get("token")
            
            if bind_port:
                from app.utils import parse_address_port
                try:
                    if int(bind_port) == 8000:
                        db_tunnel.status = "error"
                        db_tunnel.error_message = "FRP server cannot use port 8000 (panel API port). Use a different port like 7000."
                        await db.commit()
                        await db.refresh(db_tunnel)
                        return db_tunnel
                except (ValueError, TypeError):
                    pass
            
            if bind_port and hasattr(request.app.state, 'frp_server_manager'):
                try:
                    logger.info(f"Starting FRP server for tunnel {db_tunnel.id}: bind_port={bind_port}, token={'set' if token else 'none'}")
                    request.app.state.frp_server_manager.start_server(
                        tunnel_id=db_tunnel.id,
                        bind_port=int(bind_port),
                        token=token
                    )
                    time.sleep(1.0)
                    if not request.app.state.frp_server_manager.is_running(db_tunnel.id):
                        raise RuntimeError("FRP server process started but is not running")
                    frp_started = True
                    logger.info(f"Successfully started FRP server for tunnel {db_tunnel.id}")
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"Failed to start FRP server for tunnel {db_tunnel.id}: {error_msg}", exc_info=True)
                    db_tunnel.status = "error"
                    db_tunnel.error_message = f"FRP server error: {error_msg}"
                    await db.commit()
                    await db.refresh(db_tunnel)
                    return db_tunnel
            else:
                missing = []
                if not bind_port:
                    missing.append("bind_port")
                if not hasattr(request.app.state, 'frp_server_manager'):
                    missing.append("frp_server_manager")
                logger.warning(f"Tunnel {db_tunnel.id}: Missing required fields for FRP server: {missing}")
                if not bind_port:
                    db_tunnel.status = "error"
                    db_tunnel.error_message = f"Missing required fields for FRP: {missing}"
                    await db.commit()
                    await db.refresh(db_tunnel)
                    return db_tunnel
        
        if needs_node_apply:
            if not node:
                raise HTTPException(status_code=400, detail=f"Node is required for {db_tunnel.core.title()} tunnels")
            
            client = NodeClient()
            if not node.node_metadata.get("api_address"):
                node.node_metadata["api_address"] = f"http://{node.node_metadata.get('ip_address', node.fingerprint)}:{node.node_metadata.get('api_port', 8888)}"
                await db.commit()
            
            spec_for_node = db_tunnel.spec.copy() if db_tunnel.spec else {}
            
            if needs_chisel_server:
                listen_port = spec_for_node.get("listen_port") or spec_for_node.get("remote_port") or spec_for_node.get("server_port")
                use_ipv6 = spec_for_node.get("use_ipv6", False)
                if listen_port:
                    server_control_port = spec_for_node.get("control_port")
                    if server_control_port:
                        server_control_port = int(server_control_port)
                    else:
                        server_control_port = int(listen_port) + 10000
                    reverse_port = int(listen_port)
                    
                    panel_host = spec_for_node.get("panel_host")
                    
                    if not panel_host:
                        panel_address = node.node_metadata.get("panel_address", "")
                        if panel_address:
                            if "://" in panel_address:
                                panel_address = panel_address.split("://", 1)[1]
                            if ":" in panel_address:
                                panel_host = panel_address.split(":")[0]
                            else:
                                panel_host = panel_address
                    
                    if not panel_host or panel_host in ["localhost", "127.0.0.1", "::1"]:
                        panel_host = request.url.hostname
                        if not panel_host or panel_host in ["localhost", "127.0.0.1", "::1"]:
                            forwarded_host = request.headers.get("X-Forwarded-Host")
                            if forwarded_host:
                                panel_host = forwarded_host.split(":")[0] if ":" in forwarded_host else forwarded_host
                    
                    if not panel_host or panel_host in ["localhost", "127.0.0.1", "::1"]:
                        logger.warning(f"Chisel tunnel {db_tunnel.id}: Could not determine panel host, using request hostname: {request.url.hostname}. Node may not be able to connect if this is localhost.")
                        panel_host = request.url.hostname or "localhost"
                    
                    from app.utils import is_valid_ipv6_address
                    if is_valid_ipv6_address(panel_host):
                        server_url = f"http://[{panel_host}]:{server_control_port}"
                    else:
                        server_url = f"http://{panel_host}:{server_control_port}"
                    spec_for_node["server_url"] = server_url
                    spec_for_node["reverse_port"] = reverse_port
                    spec_for_node["remote_port"] = int(listen_port)
                    logger.info(f"Chisel tunnel {db_tunnel.id}: server_url={server_url}, server_control_port={server_control_port}, reverse_port={reverse_port}, use_ipv6={use_ipv6}, panel_host={panel_host}")
            
            if needs_frp_server:
                logger.info(f"Preparing FRP spec for tunnel {db_tunnel.id}, original spec server_addr: {spec_for_node.get('server_addr', 'NOT SET')}")
                try:
                    spec_for_node = prepare_frp_spec_for_node(spec_for_node, node, request)
                    final_server_addr = spec_for_node.get('server_addr', 'NOT SET')
                    logger.info(f"FRP spec prepared for tunnel {db_tunnel.id}: server_addr={final_server_addr}, server_port={spec_for_node.get('server_port')}")
                    if final_server_addr in ["0.0.0.0", "NOT SET", ""]:
                        raise ValueError(f"FRP server_addr is invalid: {final_server_addr}")
                except Exception as e:
                    error_msg = f"Failed to prepare FRP spec: {str(e)}"
                    logger.error(f"Tunnel {db_tunnel.id}: {error_msg}", exc_info=True)
                    db_tunnel.status = "error"
                    db_tunnel.error_message = f"FRP configuration error: {error_msg}"
                    await db.commit()
                    await db.refresh(db_tunnel)
                    return db_tunnel
            
            logger.info(f"Applying tunnel {db_tunnel.id} to node {node.id}, spec keys: {list(spec_for_node.keys())}, server_addr: {spec_for_node.get('server_addr', 'NOT SET')}, full spec: {spec_for_node}")
            response = await client.send_to_node(
                node_id=node.id,
                endpoint="/api/agent/tunnels/apply",
                data={
                    "tunnel_id": db_tunnel.id,
                    "core": db_tunnel.core,
                    "type": db_tunnel.type,
                    "spec": spec_for_node
                }
            )
            
            if response.get("status") == "error":
                db_tunnel.status = "error"
                error_msg = response.get("message", "Unknown error from node")
                db_tunnel.error_message = f"Node error: {error_msg}"
                logger.error(f"Tunnel {db_tunnel.id}: {error_msg}")
                if needs_rathole_server and hasattr(request.app.state, 'rathole_server_manager'):
                    try:
                        request.app.state.rathole_server_manager.stop_server(db_tunnel.id)
                    except:
                        pass
                if needs_backhaul_server and hasattr(request.app.state, "backhaul_manager"):
                    try:
                        request.app.state.backhaul_manager.stop_server(db_tunnel.id)
                    except Exception:
                        pass
                if needs_chisel_server and hasattr(request.app.state, 'chisel_server_manager'):
                    try:
                        request.app.state.chisel_server_manager.stop_server(db_tunnel.id)
                    except Exception:
                        pass
                if needs_frp_server and hasattr(request.app.state, 'frp_server_manager'):
                    try:
                        request.app.state.frp_server_manager.stop_server(db_tunnel.id)
                    except Exception:
                        pass
                await db.commit()
                await db.refresh(db_tunnel)
                return db_tunnel
            
            if response.get("status") != "success":
                db_tunnel.status = "error"
                db_tunnel.error_message = "Failed to apply tunnel to node. Check node connection."
                logger.error(f"Tunnel {db_tunnel.id}: Failed to apply to node")
                if needs_rathole_server and hasattr(request.app.state, 'rathole_server_manager'):
                    try:
                        request.app.state.rathole_server_manager.stop_server(db_tunnel.id)
                    except:
                        pass
                if needs_backhaul_server and hasattr(request.app.state, "backhaul_manager"):
                    try:
                        request.app.state.backhaul_manager.stop_server(db_tunnel.id)
                    except Exception:
                        pass
                if needs_chisel_server and hasattr(request.app.state, 'chisel_server_manager'):
                    try:
                        request.app.state.chisel_server_manager.stop_server(db_tunnel.id)
                    except Exception:
                        pass
                if needs_frp_server and hasattr(request.app.state, 'frp_server_manager'):
                    try:
                        request.app.state.frp_server_manager.stop_server(db_tunnel.id)
                    except Exception:
                        pass
                await db.commit()
                await db.refresh(db_tunnel)
                return db_tunnel
        
        db_tunnel.status = "active"
        
        try:
            if needs_gost_forwarding:
                iran_node_id_val = tunnel.iran_node_id if tunnel.iran_node_id and (not isinstance(tunnel.iran_node_id, str) or tunnel.iran_node_id.strip()) else None
                foreign_node_id_val = tunnel.foreign_node_id if tunnel.foreign_node_id and (not isinstance(tunnel.foreign_node_id, str) or tunnel.foreign_node_id.strip()) else None
                
                if iran_node_id_val and foreign_node_id_val:
                    result = await db.execute(select(Node).where(Node.id == iran_node_id_val))
                    iran_node = result.scalar_one_or_none()
                    result = await db.execute(select(Node).where(Node.id == foreign_node_id_val))
                    foreign_node = result.scalar_one_or_none()
                    
                    if not iran_node:
                        db_tunnel.status = "error"
                        db_tunnel.error_message = "Iran node not found"
                        await db.commit()
                        await db.refresh(db_tunnel)
                        return db_tunnel
                    
                    if not foreign_node:
                        db_tunnel.status = "error"
                        db_tunnel.error_message = "Foreign server not found"
                        await db.commit()
                        await db.refresh(db_tunnel)
                        return db_tunnel
                    
                    foreign_ip = foreign_node.node_metadata.get("ip_address")
                    if not foreign_ip:
                        db_tunnel.status = "error"
                        db_tunnel.error_message = "Foreign server has no IP address"
                        await db.commit()
                        await db.refresh(db_tunnel)
                        return db_tunnel
                    
                    ports = parse_ports_from_spec(db_tunnel.spec)
                    if not ports:
                        listen_port = db_tunnel.spec.get("listen_port") or db_tunnel.spec.get("remote_port")
                        if listen_port:
                            ports = [int(listen_port) if isinstance(listen_port, (int, str)) and str(listen_port).isdigit() else listen_port]
                    
                    if not ports:
                        db_tunnel.status = "error"
                        db_tunnel.error_message = "GOST requires ports"
                        await db.commit()
                        await db.refresh(db_tunnel)
                        return db_tunnel
                    
                    use_ipv6 = db_tunnel.spec.get("use_ipv6", False)
                    remote_ip = db_tunnel.spec.get("remote_ip", foreign_ip)
                    
                    gost_spec = {
                        "ports": ports,
                        "remote_ip": remote_ip,
                        "type": db_tunnel.type,
                        "use_ipv6": use_ipv6
                    }
                    
                    client = NodeClient()
                    if not iran_node.node_metadata.get("api_address"):
                        iran_node.node_metadata["api_address"] = f"http://{iran_node.node_metadata.get('ip_address', iran_node.fingerprint)}:{iran_node.node_metadata.get('api_port', 8888)}"
                        await db.commit()
                    
                    logger.info(f"Applying GOST forwarding to Iran node {iran_node.id} for tunnel {db_tunnel.id}: {db_tunnel.type} with ports {ports} -> {remote_ip}")
                    response = await client.send_to_node(
                        node_id=iran_node.id,
                        endpoint="/api/agent/tunnels/apply",
                        data={
                            "tunnel_id": db_tunnel.id,
                            "core": "gost",
                            "type": db_tunnel.type,
                            "spec": gost_spec
                        }
                    )
                    
                    if response.get("status") != "success":
                        error_msg = response.get("message", "Unknown error from Iran node")
                        db_tunnel.status = "error"
                        db_tunnel.error_message = f"Iran node error: {error_msg}"
                        logger.error(f"Tunnel {db_tunnel.id}: Iran node error: {error_msg}")
                        await db.commit()
                        await db.refresh(db_tunnel)
                        return db_tunnel
                    
                    logger.info(f"Successfully applied GOST forwarding to Iran node for tunnel {db_tunnel.id}")
                else:
                    ports = parse_ports_from_spec(db_tunnel.spec)
                    if not ports:
                        listen_port = db_tunnel.spec.get("listen_port")
                        if listen_port:
                            ports = [int(listen_port) if isinstance(listen_port, (int, str)) and str(listen_port).isdigit() else listen_port]
                    
                    forward_to = db_tunnel.spec.get("forward_to")
                    remote_ip = db_tunnel.spec.get("remote_ip", "127.0.0.1")
                    use_ipv6 = db_tunnel.spec.get("use_ipv6", False)
                    
                    if not ports:
                        db_tunnel.status = "error"
                        db_tunnel.error_message = "GOST requires ports"
                        await db.commit()
                        await db.refresh(db_tunnel)
                        return db_tunnel
                    
                    if ports and hasattr(request.app.state, 'gost_forwarder'):
                        try:
                            for port in ports:
                                port_num = int(port) if isinstance(port, (int, str)) and str(port).isdigit() else port
                                if not forward_to:
                                    from app.utils import format_address_port
                                    forward_to_port = format_address_port(remote_ip, port_num)
                                else:
                                    forward_to_port = forward_to
                                
                                tunnel_id_for_port = f"{db_tunnel.id}_{port_num}" if len(ports) > 1 else db_tunnel.id
                                logger.info(f"Starting gost forwarding on panel for tunnel {db_tunnel.id}: {db_tunnel.type}://:{port_num} -> {forward_to_port}, use_ipv6={use_ipv6}")
                                request.app.state.gost_forwarder.start_forward(
                                    tunnel_id=tunnel_id_for_port,
                                    local_port=port_num,
                                    forward_to=forward_to_port,
                                    tunnel_type=db_tunnel.type,
                                    use_ipv6=bool(use_ipv6)
                                )
                            
                            time.sleep(2)
                            logger.info(f"Successfully started gost forwarding on panel for tunnel {db_tunnel.id} with {len(ports)} ports")
                        except Exception as e:
                            error_msg = str(e)
                            logger.error(f"Failed to start gost forwarding on panel for tunnel {db_tunnel.id}: {error_msg}", exc_info=True)
                            db_tunnel.status = "error"
                            db_tunnel.error_message = f"Gost forwarding error: {error_msg}"
                            await db.commit()
                            await db.refresh(db_tunnel)
                            return db_tunnel
                    else:
                        missing = []
                        if not ports:
                            missing.append("ports")
                        if not forward_to and not remote_ip:
                            missing.append("forward_to")
                        if not hasattr(request.app.state, 'gost_forwarder'):
                            missing.append("gost_forwarder")
                        logger.warning(f"Tunnel {db_tunnel.id}: Missing required fields: {missing}")
                        if not forward_to:
                            error_msg = "forward_to is required for gost tunnels"
                            db_tunnel.status = "error"
                            db_tunnel.error_message = error_msg
            
        except Exception as e:
            logger.error(f"Exception in forwarding setup for tunnel {db_tunnel.id}: {e}", exc_info=True)
        
        await db.commit()
        await db.refresh(db_tunnel)
    except Exception as e:
        logger.error(f"Exception in tunnel creation for {db_tunnel.id}: {e}", exc_info=True)
        error_msg = str(e)
        db_tunnel.status = "error"
        db_tunnel.error_message = f"Tunnel creation error: {error_msg}"
        try:
            if needs_rathole_server and hasattr(request.app.state, "rathole_server_manager"):
                request.app.state.rathole_server_manager.stop_server(db_tunnel.id)
        except Exception:
            pass
        try:
            if needs_backhaul_server and hasattr(request.app.state, "backhaul_manager"):
                request.app.state.backhaul_manager.stop_server(db_tunnel.id)
        except Exception:
            pass
        await db.commit()
        await db.refresh(db_tunnel)
    
    return db_tunnel


@router.get("", response_model=List[TunnelResponse])
async def list_tunnels(db: AsyncSession = Depends(get_db)):
    """List all tunnels"""
    result = await db.execute(select(Tunnel))
    tunnels = result.scalars().all()
    return tunnels


@router.get("/{tunnel_id}", response_model=TunnelResponse)
async def get_tunnel(tunnel_id: str, db: AsyncSession = Depends(get_db)):
    """Get tunnel by ID"""
    result = await db.execute(select(Tunnel).where(Tunnel.id == tunnel_id))
    tunnel = result.scalar_one_or_none()
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    return tunnel


@router.put("/{tunnel_id}", response_model=TunnelResponse)
async def update_tunnel(
    tunnel_id: str,
    tunnel_update: TunnelUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Update a tunnel and re-apply if spec changed"""
    from app.node_client import NodeClient
    
    result = await db.execute(select(Tunnel).where(Tunnel.id == tunnel_id))
    tunnel = result.scalar_one_or_none()
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    
    core_changed = tunnel_update.core is not None and tunnel_update.core.lower() != (tunnel.core or "").lower()
    type_changed = tunnel_update.type is not None and tunnel_update.type.lower() != (tunnel.type or "").lower()
    
    if core_changed or type_changed:
        if tunnel_update.name is not None:
            tunnel.name = tunnel_update.name
        if tunnel_update.spec is not None:
            # Apply user spec edits first so the change helper extracts the
            # latest exposed ports (core change rebuilds the spec from them).
            tunnel.spec = tunnel_update.spec
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(tunnel, "spec")
        await db.commit()
        await db.refresh(tunnel)
        tunnel = await change_tunnel_core_type(
            tunnel,
            tunnel_update.core or tunnel.core,
            tunnel_update.type,
            request,
            db,
        )
        return tunnel
    
    spec_changed = tunnel_update.spec is not None and tunnel_update.spec != tunnel.spec
    
    if tunnel_update.name is not None:
        tunnel.name = tunnel_update.name
    if tunnel_update.spec is not None:
        # For Backhaul, ensure ports are preserved in the correct format
        if tunnel.core == "backhaul" and tunnel_update.spec.get("ports"):
            # Ports should already be in the correct format from frontend, but ensure they're preserved
            ports = tunnel_update.spec.get("ports", [])
            logger.info(f"Backhaul tunnel update {tunnel_id}: preserving ports from update: {ports} (count: {len(ports) if isinstance(ports, list) else 'N/A'})")
        tunnel.spec = tunnel_update.spec
    
    tunnel.revision += 1
    tunnel.updated_at = datetime.utcnow()
    
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(tunnel, "spec")
    await db.commit()
    await db.refresh(tunnel)
    
    if spec_changed:
        try:
            if tunnel.core in SINGLE_NODE_CORES:
                # zapret/snispoof are single-node; re-push the updated spec via apply_tunnel.
                try:
                    await apply_tunnel(tunnel.id, request, db)
                except HTTPException as e:
                    logger.error(f"Failed to re-apply {tunnel.core} tunnel {tunnel.id}: {e.detail}")
                await db.refresh(tunnel)
                return tunnel

            if tunnel.core in ("udp2raw", "trusttunnel", "obfs4"):
                # udp2raw/trusttunnel/obfs4 run on both the iran and foreign nodes;
                # delegate to apply_tunnel which rebuilds and pushes the split specs
                # (obfs4 via its two-phase server-first + cert helper).
                try:
                    await apply_tunnel(tunnel.id, request, db)
                except HTTPException as e:
                    logger.error(f"Failed to re-apply {tunnel.core} tunnel {tunnel.id}: {e.detail}")
                await db.refresh(tunnel)
                return tunnel
            
            needs_gost_forwarding = tunnel.type in ["tcp", "udp", "ws", "grpc", "tcpmux"] and tunnel.core == "gost"
            needs_rathole_server = tunnel.core == "rathole"
            needs_backhaul_server = tunnel.core == "backhaul"
            needs_chisel_server = tunnel.core == "chisel"
            needs_frp_server = tunnel.core == "frp"
            needs_node_apply = tunnel.core in {"rathole", "backhaul", "chisel", "frp"}
            
            if needs_gost_forwarding:
                listen_port = tunnel.spec.get("listen_port")
                forward_to = tunnel.spec.get("forward_to")
                
                if not forward_to:
                    from app.utils import format_address_port
                    remote_ip = tunnel.spec.get("remote_ip", "127.0.0.1")
                    remote_port = tunnel.spec.get("remote_port", 8080)
                    forward_to = format_address_port(remote_ip, remote_port)
                
                panel_port = listen_port or tunnel.spec.get("remote_port")
                use_ipv6 = tunnel.spec.get("use_ipv6", False)
                
                if panel_port and forward_to and hasattr(request.app.state, 'gost_forwarder'):
                    try:
                        request.app.state.gost_forwarder.stop_forward(tunnel.id)
                        time.sleep(0.5)
                        logger.info(f"Restarting gost forwarding for tunnel {tunnel.id}: {tunnel.type}://:{panel_port} -> {forward_to}, use_ipv6={use_ipv6}")
                        request.app.state.gost_forwarder.start_forward(
                            tunnel_id=tunnel.id,
                            local_port=int(panel_port),
                            forward_to=forward_to,
                            tunnel_type=tunnel.type,
                            use_ipv6=bool(use_ipv6)
                        )
                        tunnel.status = "active"
                        tunnel.error_message = None
                        logger.info(f"Successfully restarted gost forwarding for tunnel {tunnel.id}")
                    except Exception as e:
                        error_msg = str(e)
                        logger.error(f"Failed to restart gost forwarding for tunnel {tunnel.id}: {error_msg}", exc_info=True)
                        tunnel.status = "error"
                        tunnel.error_message = f"Gost forwarding error: {error_msg}"
                else:
                    if not forward_to:
                        tunnel.status = "error"
                        tunnel.error_message = "forward_to is required for gost tunnels"
            
            elif needs_rathole_server:
                if hasattr(request.app.state, 'rathole_server_manager'):
                    remote_addr = tunnel.spec.get("remote_addr")
                    token = tunnel.spec.get("token")
                    proxy_port = tunnel.spec.get("remote_port") or tunnel.spec.get("listen_port")
                    
                    if remote_addr and token and proxy_port:
                        try:
                            request.app.state.rathole_server_manager.stop_server(tunnel.id)
                            request.app.state.rathole_server_manager.start_server(
                                tunnel_id=tunnel.id,
                                remote_addr=remote_addr,
                                token=token,
                                proxy_port=int(proxy_port)
                            )
                            tunnel.status = "active"
                            tunnel.error_message = None
                        except Exception as e:
                            logger.error(f"Failed to restart Rathole server: {e}")
                            tunnel.status = "error"
                            tunnel.error_message = f"Rathole server error: {str(e)}"
            elif needs_backhaul_server:
                manager = getattr(request.app.state, "backhaul_manager", None)
                if manager:
                    try:
                        manager.stop_server(tunnel.id)
                    except Exception:
                        pass
                    try:
                        manager.start_server(tunnel.id, tunnel.spec or {})
                        time.sleep(1.0)
                        if not manager.is_running(tunnel.id):
                            raise RuntimeError("Backhaul process not running")
                        tunnel.status = "active"
                        tunnel.error_message = None
                    except Exception as exc:
                        logger.error("Failed to restart Backhaul server for tunnel %s: %s", tunnel.id, exc, exc_info=True)
                        tunnel.status = "error"
                        tunnel.error_message = f"Backhaul server error: {exc}"
            elif needs_chisel_server:
                if hasattr(request.app.state, 'chisel_server_manager'):
                    server_port = tunnel.spec.get("control_port") or (int(tunnel.spec.get("listen_port", 0)) + 10000)
                    auth = tunnel.spec.get("auth") or tunnel.spec.get("token")
                    fingerprint = tunnel.spec.get("fingerprint")
                    use_ipv6 = tunnel.spec.get("use_ipv6", False)
                    
                    if server_port and auth and fingerprint:
                        try:
                            request.app.state.chisel_server_manager.stop_server(tunnel.id)
                            request.app.state.chisel_server_manager.start_server(
                                tunnel_id=tunnel.id,
                                server_port=int(server_port),
                                auth=auth,
                                fingerprint=fingerprint,
                                use_ipv6=bool(use_ipv6)
                            )
                            tunnel.status = "active"
                            tunnel.error_message = None
                        except Exception as e:
                            logger.error(f"Failed to restart Chisel server: {e}")
                            tunnel.status = "error"
                            tunnel.error_message = f"Chisel server error: {str(e)}"
            elif needs_frp_server:
                if hasattr(request.app.state, 'frp_server_manager'):
                    bind_port = tunnel.spec.get("bind_port", 7000)
                    token = tunnel.spec.get("token")
                    
                    if bind_port:
                        try:
                            request.app.state.frp_server_manager.stop_server(tunnel.id)
                            request.app.state.frp_server_manager.start_server(
                                tunnel_id=tunnel.id,
                                bind_port=int(bind_port),
                                token=token
                            )
                            time.sleep(1.0)
                            if not request.app.state.frp_server_manager.is_running(tunnel.id):
                                raise RuntimeError("FRP server process not running")
                            tunnel.status = "active"
                            tunnel.error_message = None
                        except Exception as e:
                            logger.error(f"Failed to restart FRP server: {e}")
                            tunnel.status = "error"
                            tunnel.error_message = f"FRP server error: {str(e)}"
            
            if needs_node_apply and tunnel.node_id:
                result = await db.execute(select(Node).where(Node.id == tunnel.node_id))
                node = result.scalar_one_or_none()
                if node:
                    client = NodeClient()
                    try:
                        spec_for_node = tunnel.spec.copy() if tunnel.spec else {}
                        frp_prep_failed = False
                        if tunnel.core == "frp":
                            try:
                                spec_for_node = prepare_frp_spec_for_node(spec_for_node, node, request)
                                logger.info(f"FRP spec prepared for tunnel {tunnel.id}: server_addr={spec_for_node.get('server_addr')}")
                            except Exception as e:
                                error_msg = f"Failed to prepare FRP spec: {str(e)}"
                                logger.error(f"Tunnel {tunnel.id}: {error_msg}", exc_info=True)
                                tunnel.status = "error"
                                tunnel.error_message = f"FRP configuration error: {error_msg}"
                                await db.commit()
                                await db.refresh(tunnel)
                                frp_prep_failed = True
                        
                        if not frp_prep_failed:
                            response = await client.send_to_node(
                                node_id=node.id,
                                endpoint="/api/agent/tunnels/apply",
                                data={
                                    "tunnel_id": tunnel.id,
                                    "core": tunnel.core,
                                    "type": tunnel.type,
                                    "spec": spec_for_node
                                }
                            )
                            
                            if response.get("status") == "success":
                                tunnel.status = "active"
                                tunnel.error_message = None
                            else:
                                tunnel.status = "error"
                                tunnel.error_message = f"Node error: {response.get('message', 'Unknown error')}"
                                if needs_backhaul_server and hasattr(request.app.state, "backhaul_manager"):
                                    try:
                                        request.app.state.backhaul_manager.stop_server(tunnel.id)
                                    except Exception:
                                        pass
                    except Exception as e:
                        logger.error(f"Failed to re-apply tunnel to node: {e}")
                        tunnel.status = "error"
                        tunnel.error_message = f"Node error: {str(e)}"
                        if needs_backhaul_server and hasattr(request.app.state, "backhaul_manager"):
                            try:
                                request.app.state.backhaul_manager.stop_server(tunnel.id)
                            except Exception:
                                pass
            
            await db.commit()
            await db.refresh(tunnel)
        except Exception as e:
            logger.error(f"Failed to re-apply tunnel: {e}", exc_info=True)
            tunnel.status = "error"
            tunnel.error_message = f"Re-apply error: {str(e)}"
            await db.commit()
            await db.refresh(tunnel)
    
    return tunnel


class BulkApplyRequest(BaseModel):
    tunnel_ids: List[str]


class BulkChangeRequest(BaseModel):
    tunnel_ids: List[str]
    core: str | None = None
    type: str | None = None


class BenchmarkStartRequest(BaseModel):
    iran_node_id: str
    foreign_node_id: str
    cores: List[str] | None = None


@router.post("/benchmark")
async def start_benchmark(payload: BenchmarkStartRequest, db: AsyncSession = Depends(get_db)):
    """Start a tunnel quality benchmark between an iran and a foreign node."""
    from app.benchmark_manager import benchmark_manager

    if benchmark_manager.is_running():
        raise HTTPException(status_code=409, detail="A benchmark is already running")

    result = await db.execute(select(Node).where(Node.id == payload.iran_node_id))
    iran_node = result.scalar_one_or_none()
    if not iran_node:
        raise HTTPException(status_code=404, detail="Iran node not found")
    if iran_node.node_metadata.get("role") != "iran":
        raise HTTPException(status_code=400, detail="Selected node is not an iran node")

    result = await db.execute(select(Node).where(Node.id == payload.foreign_node_id))
    foreign_node = result.scalar_one_or_none()
    if not foreign_node:
        raise HTTPException(status_code=404, detail="Foreign node not found")
    if foreign_node.node_metadata.get("role") != "foreign":
        raise HTTPException(status_code=400, detail="Selected node is not a foreign node")

    iran_ip = iran_node.node_metadata.get("ip_address")
    foreign_ip = foreign_node.node_metadata.get("ip_address")
    if not iran_ip:
        raise HTTPException(status_code=400, detail="Iran node has no IP address")
    if not foreign_ip:
        raise HTTPException(status_code=400, detail="Foreign node has no IP address")

    for node in (iran_node, foreign_node):
        if not node.node_metadata.get("api_address"):
            node.node_metadata["api_address"] = (
                f"http://{node.node_metadata.get('ip_address', node.fingerprint)}:{node.node_metadata.get('api_port', 8888)}"
            )
    await db.commit()

    try:
        benchmark_id = benchmark_manager.start(
            iran_node_id=iran_node.id,
            iran_node_name=iran_node.name,
            iran_ip=iran_ip,
            foreign_node_id=foreign_node.id,
            foreign_node_name=foreign_node.name,
            foreign_ip=foreign_ip,
            cores=payload.cores,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"status": "started", "benchmark_id": benchmark_id}


@router.get("/benchmark/status")
async def benchmark_status():
    """Get the state of the current (or last) benchmark run."""
    from app.benchmark_manager import benchmark_manager
    return benchmark_manager.get_state()


async def _resolve_snispoof_node(tunnel_id: str, db: AsyncSession):
    """Load a snispoof tunnel + its node, with normalized spec, for test/auto-tune."""
    result = await db.execute(select(Tunnel).where(Tunnel.id == tunnel_id))
    tunnel = result.scalar_one_or_none()
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    if tunnel.core != "snispoof":
        raise HTTPException(status_code=400, detail="This action is only available for snispoof tunnels")
    node = await resolve_single_node(tunnel, db)
    if not node:
        raise HTTPException(status_code=400, detail="snispoof tunnel has no node assigned")
    if not node.node_metadata.get("api_address"):
        node.node_metadata["api_address"] = (
            f"http://{node.node_metadata.get('ip_address', node.fingerprint)}:{node.node_metadata.get('api_port', 8888)}"
        )
        await db.commit()
    spec = normalize_snispoof_spec(tunnel.spec)
    return tunnel, node, spec


@router.post("/{tunnel_id}/snispoof/test")
async def snispoof_test(tunnel_id: str, db: AsyncSession = Depends(get_db)):
    """Quick check: does the snispoof chain pass traffic right now? Returns the
    exact client outbound to paste into the proxy panel (e.g. Sanaei)."""
    tunnel, node, spec = await _resolve_snispoof_node(tunnel_id, db)
    client = NodeClient()
    resp = await client.send_to_node(
        node.id, "/api/agent/snispoof/test",
        {"tunnel_id": tunnel_id, "spec": spec}, timeout=60.0,
    )
    if resp.get("status") != "success":
        raise HTTPException(status_code=502, detail=resp.get("message") or "Node test failed")
    return resp


@router.post("/{tunnel_id}/snispoof/autotune")
async def snispoof_autotune(tunnel_id: str, db: AsyncSession = Depends(get_db)):
    """Try every desync combo on the node, leave the tunnel on the best working
    one, persist it, and return the ranked results + the client outbound."""
    from sqlalchemy.orm.attributes import flag_modified
    tunnel, node, spec = await _resolve_snispoof_node(tunnel_id, db)
    client = NodeClient()
    resp = await client.send_to_node(
        node.id, "/api/agent/snispoof/autotune",
        {"tunnel_id": tunnel_id, "spec": spec}, timeout=300.0,
    )
    if resp.get("status") != "success":
        raise HTTPException(status_code=502, detail=resp.get("message") or "Node auto-tune failed")

    best = resp.get("best")
    if best:
        new_spec = dict(tunnel.spec or {})
        new_spec["desync_mode"] = best["desync_mode"]
        new_spec["desync_fooling"] = best["desync_fooling"]
        if best.get("fake_tls_sni"):
            new_spec["fake_tls_sni"] = best["fake_tls_sni"]
        tunnel.spec = new_spec
        flag_modified(tunnel, "spec")
        tunnel.revision += 1
        tunnel.status = "active"
        tunnel.error_message = None
        tunnel.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(tunnel)
    return resp


@router.post("/{tunnel_id}/warp/test")
async def warp_test(tunnel_id: str, db: AsyncSession = Depends(get_db)):
    """Verify the WARP egress: fetch Cloudflare's trace through the SOCKS proxy
    and report whether WARP is active plus the masked egress IP."""
    result = await db.execute(select(Tunnel).where(Tunnel.id == tunnel_id))
    tunnel = result.scalar_one_or_none()
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    if tunnel.core != "warp":
        raise HTTPException(status_code=400, detail="This action is only available for WARP tunnels")
    node = await resolve_single_node(tunnel, db)
    if not node:
        raise HTTPException(status_code=400, detail="WARP tunnel has no node assigned")
    if not node.node_metadata.get("api_address"):
        node.node_metadata["api_address"] = (
            f"http://{node.node_metadata.get('ip_address', node.fingerprint)}:{node.node_metadata.get('api_port', 8888)}"
        )
        await db.commit()
    spec = normalize_warp_spec(tunnel.spec)
    client = NodeClient()
    resp = await client.send_to_node(
        node.id, "/api/agent/warp/test",
        {"tunnel_id": tunnel_id, "spec": spec}, timeout=40.0,
    )
    if resp.get("status") != "success":
        raise HTTPException(status_code=502, detail=resp.get("message") or "Node WARP test failed")
    return resp


async def _resolve_hysteria2_nodes(tunnel_id: str, db: AsyncSession):
    """Load a hysteria2 tunnel + its iran (client) and foreign (server) nodes."""
    result = await db.execute(select(Tunnel).where(Tunnel.id == tunnel_id))
    tunnel = result.scalar_one_or_none()
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    if tunnel.core != "hysteria2":
        raise HTTPException(status_code=400, detail="This action is only available for hysteria2 tunnels")
    iran_node = None
    if tunnel.node_id:
        r = await db.execute(select(Node).where(Node.id == tunnel.node_id))
        iran_node = r.scalar_one_or_none()
    r = await db.execute(select(Node))
    all_nodes = r.scalars().all()
    if not iran_node:
        iran_nodes = [n for n in all_nodes if n.node_metadata and n.node_metadata.get("role") == "iran"]
        iran_node = iran_nodes[0] if iran_nodes else None
    foreign_nodes = [n for n in all_nodes if n.node_metadata and n.node_metadata.get("role") == "foreign"]
    foreign_node = foreign_nodes[0] if foreign_nodes else None
    if not iran_node or not foreign_node:
        raise HTTPException(status_code=400, detail="hysteria2 auto-tune needs both an iran and a foreign node")
    for n in (iran_node, foreign_node):
        if not n.node_metadata.get("api_address"):
            n.node_metadata["api_address"] = (
                f"http://{n.node_metadata.get('ip_address', n.fingerprint)}:{n.node_metadata.get('api_port', 8888)}"
            )
    await db.commit()
    return tunnel, iran_node, foreign_node


@router.post("/{tunnel_id}/hysteria2/autotune")
async def hysteria2_autotune(tunnel_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Probe the hysteria2 carrier with obfs ON vs OFF on throwaway test tunnels,
    rank by measured quality, persist the best profile, and re-apply the tunnel.

    Mirrors the snispoof auto-tune: the node side is exercised with the existing
    benchmark sink/probe so we measure real throughput/latency/loss, never just
    "does the process start". obfs (Salamander) is the main DPI-survival lever,
    so that is what we vary; the winner is saved to the tunnel spec.
    """
    import asyncio
    import hashlib
    import uuid as uuid_mod
    from sqlalchemy.orm.attributes import flag_modified
    from app.utils import generate_token, format_address_port

    tunnel, iran_node, foreign_node = await _resolve_hysteria2_nodes(tunnel_id, db)
    iran_ip = iran_node.node_metadata.get("ip_address")
    foreign_ip = foreign_node.node_metadata.get("ip_address")
    ttype = (tunnel.type or (tunnel.spec or {}).get("type") or "udp").lower()
    probe_proto = "tcp" if ttype in ("tcp", "both") else "udp"

    auth = (tunnel.spec or {}).get("auth") or generate_token(24)
    obfs_pw = (tunnel.spec or {}).get("obfs_password") or generate_token(16)
    if str(obfs_pw).strip().lower() in ("", "off", "none"):
        obfs_pw = generate_token(16)
    sni = (tunnel.spec or {}).get("sni") or "www.bing.com"

    port_hash = int(hashlib.md5(tunnel.id.encode()).hexdigest()[:8], 16)
    test_port = 19500 + (port_hash % 300)
    control_port = 19850 + (port_hash % 120)

    profiles = [
        {"id": "obfs_salamander", "obfs_password": obfs_pw},
        {"id": "obfs_off", "obfs_password": ""},
    ]

    client = NodeClient()
    results = []

    async def run_profile(profile):
        run_id = f"h2tune-{uuid_mod.uuid4().hex[:8]}"
        iran_spec = {
            "mode": "client", "type": ttype,
            "server_addr": format_address_port(foreign_ip, control_port),
            "sni": sni, "auth": auth, "obfs_password": profile["obfs_password"],
            "forwards": [{"listen": f"0.0.0.0:{test_port}", "remote": f"127.0.0.1:{test_port}", "protocol": ttype}],
        }
        foreign_spec = {
            "mode": "server", "type": ttype, "listen_port": control_port, "control_port": control_port,
            "sni": sni, "auth": auth, "obfs_password": profile["obfs_password"],
        }
        metrics = {"ok": False, "error": None, "latency_ms": None, "throughput_mbps": None, "loss_percent": None}
        try:
            sink = await client.send_to_node(
                foreign_node.id, "/api/agent/benchmark/sink/start",
                {"sink_id": run_id, "port": test_port, "protocol": probe_proto, "duration_sec": 90},
            )
            if sink.get("status") != "success":
                metrics["error"] = f"sink: {sink.get('message')}"
                return metrics
            sr = await client.send_to_node(
                foreign_node.id, "/api/agent/tunnels/apply",
                {"tunnel_id": run_id, "core": "hysteria2", "type": ttype, "spec": foreign_spec}, timeout=40.0,
            )
            if sr.get("status") != "success":
                metrics["error"] = f"server: {sr.get('message')}"
                return metrics
            cr = await client.send_to_node(
                iran_node.id, "/api/agent/tunnels/apply",
                {"tunnel_id": run_id, "core": "hysteria2", "type": ttype, "spec": iran_spec}, timeout=40.0,
            )
            if cr.get("status") != "success":
                metrics["error"] = f"client: {cr.get('message')}"
                return metrics
            await asyncio.sleep(4.0)
            probe = await client.send_to_node(
                iran_node.id, "/api/agent/benchmark/probe",
                {"host": "127.0.0.1", "port": test_port, "protocol": probe_proto,
                 "ping_count": 10, "throughput_seconds": 3.0}, timeout=40.0,
            )
            if probe.get("status") == "success":
                metrics = probe.get("metrics") or metrics
            else:
                metrics["error"] = f"probe: {probe.get('message')}"
        finally:
            for nid in (iran_node.id, foreign_node.id):
                try:
                    await client.send_to_node(nid, "/api/agent/tunnels/remove", {"tunnel_id": run_id})
                except Exception:
                    pass
            try:
                await client.send_to_node(foreign_node.id, "/api/agent/benchmark/sink/stop", {"sink_id": run_id})
            except Exception:
                pass
        return metrics

    for profile in profiles:
        m = await run_profile(profile)
        score = 0.0
        if m.get("ok"):
            thr = float(m.get("throughput_mbps") or 0.0)
            lat = float(m.get("latency_ms") or 500.0)
            loss = float(m.get("loss_percent") or 0.0)
            score = round(min(thr / 100.0, 1.0) * 60 + max(0.0, 1 - min(lat, 500) / 500) * 30 + max(0.0, 1 - loss / 100) * 10, 1)
        results.append({
            "profile": profile["id"],
            "obfs": "salamander" if profile["obfs_password"] else "off",
            "ok": bool(m.get("ok")),
            "latency_ms": m.get("latency_ms"),
            "throughput_mbps": m.get("throughput_mbps"),
            "loss_percent": m.get("loss_percent"),
            "score": score,
            "error": m.get("error"),
        })

    ranked = sorted(results, key=lambda r: (not r["ok"], -(r["score"] or 0.0)))
    best = next((r for r in ranked if r["ok"]), None)

    applied = False
    if best:
        new_spec = dict(tunnel.spec or {})
        new_spec["auth"] = auth
        new_spec["obfs_password"] = obfs_pw if best["obfs"] == "salamander" else ""
        new_spec["sni"] = sni
        tunnel.spec = new_spec
        flag_modified(tunnel, "spec")
        tunnel.revision += 1
        tunnel.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(tunnel)
        try:
            await apply_tunnel(tunnel_id, request, db)
            applied = True
        except Exception as e:
            logger.warning(f"hysteria2 autotune: re-apply failed for {tunnel_id}: {e}")

    return {
        "status": "success",
        "ok": best is not None,
        "best": ({"obfs": best["obfs"], "throughput_mbps": best["throughput_mbps"],
                  "latency_ms": best["latency_ms"], "applied": applied} if best else None),
        "results": ranked,
        "probe_protocol": probe_proto,
    }


# NOTE: bulk routes must be registered before POST /{tunnel_id}/apply so the
# literal "/bulk/..." paths are not captured by the {tunnel_id} parameter.
@router.post("/bulk/apply")
async def bulk_apply_tunnels(payload: BulkApplyRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Re-apply a list of tunnels, returning per-tunnel results."""
    results = []
    for tid in payload.tunnel_ids:
        result = await db.execute(select(Tunnel).where(Tunnel.id == tid))
        tunnel = result.scalar_one_or_none()
        if not tunnel:
            results.append({"tunnel_id": tid, "name": None, "status": "error", "message": "Tunnel not found"})
            continue
        name = tunnel.name
        try:
            await apply_tunnel(tid, request, db)
            results.append({"tunnel_id": tid, "name": name, "status": "success", "message": "Applied"})
        except HTTPException as e:
            results.append({"tunnel_id": tid, "name": name, "status": "error", "message": str(e.detail)})
        except Exception as e:
            logger.error(f"Bulk apply failed for tunnel {tid}: {e}", exc_info=True)
            results.append({"tunnel_id": tid, "name": name, "status": "error", "message": str(e)})
    succeeded = sum(1 for r in results if r["status"] == "success")
    return {
        "status": "completed",
        "total": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "results": results,
    }


@router.post("/bulk/change")
async def bulk_change_tunnels(payload: BulkChangeRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Change core and/or type of a list of tunnels in place.

    Each tunnel keeps its exposed ports (and forward targets); per-tunnel
    success/error results are returned.
    """
    if not payload.core and not payload.type:
        raise HTTPException(status_code=400, detail="Provide 'core' and/or 'type' to change")
    
    results = []
    for tid in payload.tunnel_ids:
        result = await db.execute(select(Tunnel).where(Tunnel.id == tid))
        tunnel = result.scalar_one_or_none()
        if not tunnel:
            results.append({"tunnel_id": tid, "name": None, "status": "error", "message": "Tunnel not found"})
            continue
        name = tunnel.name
        try:
            tunnel = await change_tunnel_core_type(tunnel, payload.core, payload.type, request, db)
            if tunnel.status == "error":
                results.append({
                    "tunnel_id": tid,
                    "name": name,
                    "status": "error",
                    "message": tunnel.error_message or "Apply failed",
                })
            else:
                results.append({
                    "tunnel_id": tid,
                    "name": name,
                    "status": "success",
                    "message": f"Changed to {tunnel.core}/{tunnel.type}",
                })
        except HTTPException as e:
            results.append({"tunnel_id": tid, "name": name, "status": "error", "message": str(e.detail)})
        except Exception as e:
            logger.error(f"Bulk change failed for tunnel {tid}: {e}", exc_info=True)
            results.append({"tunnel_id": tid, "name": name, "status": "error", "message": str(e)})
    succeeded = sum(1 for r in results if r["status"] == "success")
    return {
        "status": "completed",
        "total": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "results": results,
    }


@router.post("/bulk/delete")
async def bulk_delete_tunnels(payload: BulkApplyRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Delete a list of tunnels, returning per-tunnel results."""
    results = []
    for tid in payload.tunnel_ids:
        result = await db.execute(select(Tunnel).where(Tunnel.id == tid))
        tunnel = result.scalar_one_or_none()
        if not tunnel:
            results.append({"tunnel_id": tid, "name": None, "status": "error", "message": "Tunnel not found"})
            continue
        name = tunnel.name
        try:
            await delete_tunnel(tid, request, db)
            results.append({"tunnel_id": tid, "name": name, "status": "success", "message": "Deleted"})
        except HTTPException as e:
            results.append({"tunnel_id": tid, "name": name, "status": "error", "message": str(e.detail)})
        except Exception as e:
            logger.error(f"Bulk delete failed for tunnel {tid}: {e}", exc_info=True)
            results.append({"tunnel_id": tid, "name": name, "status": "error", "message": str(e)})
    succeeded = sum(1 for r in results if r["status"] == "success")
    return {
        "status": "completed",
        "total": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "results": results,
    }


@router.post("/{tunnel_id}/apply")
async def apply_tunnel(tunnel_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Apply tunnel configuration to node(s) - handles both single-node and reverse tunnels"""
    result = await db.execute(select(Tunnel).where(Tunnel.id == tunnel_id))
    tunnel = result.scalar_one_or_none()
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    
    client = NodeClient()

    if tunnel.core in SINGLE_NODE_CORES:
        await apply_singlenode_tunnel(tunnel, db)
        if tunnel.status == "active":
            return {"status": "applied", "message": "Tunnel reapplied successfully"}
        raise HTTPException(status_code=500, detail=tunnel.error_message or f"Failed to apply {tunnel.core} tunnel")

    is_reverse_tunnel = tunnel.core in {"rathole", "backhaul", "chisel", "frp", "udp2raw", "trusttunnel", "hysteria2", "tuic", "obfs4"}
    foreign_node = None
    iran_node = None
    
    if is_reverse_tunnel:
        iran_node_id = tunnel.iran_node_id or tunnel.node_id
        result = await db.execute(select(Node).where(Node.id == iran_node_id))
        iran_node = result.scalar_one_or_none()
        if not iran_node:
            raise HTTPException(status_code=404, detail=f"Iran node {iran_node_id} not found")
        
        result = await db.execute(select(Node))
        all_nodes = result.scalars().all()
        # Re-apply must target THIS tunnel's foreign node, not just the first one.
        # Using foreign_nodes[0] re-routed the tunnel onto the wrong foreign node so
        # multiple foreign nodes fought over the same rathole service and the
        # tunnels kept dropping. Fall back to the first only for legacy tunnels.
        foreign_node = None
        if tunnel.foreign_node_id:
            foreign_node = next((n for n in all_nodes if n.id == tunnel.foreign_node_id), None)
        if not foreign_node:
            foreign_nodes = [n for n in all_nodes if n.node_metadata and n.node_metadata.get("role") == "foreign"]
            if not foreign_nodes:
                raise HTTPException(status_code=404, detail="No foreign node found. Please ensure at least one node has role='foreign' (set NODE_ROLE=foreign on the foreign node).")
            foreign_node = foreign_nodes[0]
        
        if iran_node.node_metadata.get("role") != "iran":
            raise HTTPException(status_code=400, detail=f"Node {iran_node.id} is not an iran node (role={iran_node.node_metadata.get('role')}). Set NODE_ROLE=iran on the Iran node.")
        if foreign_node.node_metadata.get("role") != "foreign":
            raise HTTPException(status_code=400, detail=f"Node {foreign_node.id} is not a foreign node (role={foreign_node.node_metadata.get('role')}). Set NODE_ROLE=foreign on the foreign node.")
        
        if foreign_node and iran_node:
            try:
                spec = tunnel.spec.copy() if tunnel.spec else {}

                # obfs4 uses a two-phase (server-first, fetch cert, then client)
                # apply, so it bypasses the symmetric sender below.
                if tunnel.core == "obfs4":
                    updated = await apply_obfs4_tunnel(tunnel, foreign_node, iran_node, db, client)
                    if updated.status == "active":
                        return {"status": "applied", "message": "Tunnel reapplied successfully to both nodes"}
                    tunnel.status = "error"
                    raise HTTPException(status_code=500, detail=updated.error_message or "obfs4 apply failed")

                if tunnel.core == "backhaul":
                    transport = spec.get("transport", "tcp")
                    control_port = spec.get("control_port") or spec.get("public_port") or spec.get("listen_port") or 3080
                    public_port = spec.get("public_port") or spec.get("listen_port") or control_port
                    target_host = spec.get("target_host", "127.0.0.1")
                    token = spec.get("token")
                    
                    server_spec = spec.copy()
                    server_spec["bind_addr"] = f"0.0.0.0:{control_port}"
                    server_spec["control_port"] = control_port
                    server_spec["public_port"] = public_port
                    server_spec["listen_port"] = public_port
                    
                    # IMPORTANT: Read ports from spec (which is tunnel.spec.copy()) first
                    ports = spec.get("ports", [])
                    if not ports:
                        ports = tunnel.spec.get("ports", [])
                    if ports:
                        server_spec["ports"] = ports
                    logger.info(f"Backhaul tunnel update {tunnel.id}: received ports from spec: {spec.get('ports')}, from tunnel.spec: {tunnel.spec.get('ports')}, final: {ports} (type: {type(ports)}, length: {len(ports) if isinstance(ports, list) else 'N/A'})")
                    
                    if not ports or (isinstance(ports, list) and len(ports) == 0):
                        target_port = spec.get("target_port") or public_port
                        if target_port:
                            target_addr = f"{target_host}:{target_port}"
                            ports = [f"{public_port}={target_addr}"]
                        else:
                            ports = [str(public_port)]
                    else:
                        if isinstance(ports, list) and ports:
                            processed_ports = []
                            for p in ports:
                                if not p:
                                    continue
                                if isinstance(p, str):
                                    if '=' in p:
                                        processed_ports.append(p)
                                    elif p.isdigit():
                                        processed_ports.append(f"{p}={target_host}:{p}")
                                    else:
                                        processed_ports.append(p)
                                elif isinstance(p, int):
                                    processed_ports.append(f"{p}={target_host}:{p}")
                                elif isinstance(p, dict):
                                    local = p.get("local") or p.get("listen_port") or p.get("public_port")
                                    tgt_host = p.get("target_host") or target_host
                                    tgt_port = p.get("target_port") or p.get("remote_port") or local
                                    if local:
                                        processed_ports.append(f"{local}={tgt_host}:{tgt_port}")
                                else:
                                    processed_ports.append(str(p))
                            ports = processed_ports
                    
                    logger.info(f"Backhaul tunnel update {tunnel.id}: processed ports: {ports} (count: {len(ports)})")
                    server_spec["ports"] = ports
                    server_spec["mode"] = "server"  # Ensure mode is set
                    if token:
                        server_spec["token"] = token
                    
                    # CRITICAL: Update the database spec with processed ports so they're preserved
                    if "ports" not in tunnel.spec:
                        tunnel.spec["ports"] = []
                    tunnel.spec["ports"] = ports.copy() if isinstance(ports, list) else ports
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(tunnel, "spec")
                    await db.commit()
                    await db.refresh(tunnel)
                    logger.info(f"Backhaul tunnel update {tunnel.id}: saved ports to database: {tunnel.spec.get('ports')} (count: {len(tunnel.spec.get('ports', []))})")
                    
                    client_spec = spec.copy()
                    iran_node_ip = iran_node.node_metadata.get("ip_address")
                    if not iran_node_ip:
                        tunnel.status = "error"
                        tunnel.error_message = "Iran node has no IP address"
                        await db.commit()
                        raise HTTPException(status_code=400, detail="Iran node has no IP address")
                    
                    transport_lower = transport.lower()
                    if transport_lower in ("ws", "wsmux"):
                        use_tls = bool(server_spec.get("tls_cert") or server_spec.get("server_options", {}).get("tls_cert"))
                        protocol = "wss://" if use_tls else "ws://"
                        client_spec["remote_addr"] = f"{protocol}{iran_node_ip}:{control_port}"
                    else:
                        client_spec["remote_addr"] = f"{iran_node_ip}:{control_port}"
                    client_spec["transport"] = transport
                    client_spec["type"] = transport
                    client_spec["mode"] = "client"  # Ensure mode is set
                    if token:
                        client_spec["token"] = token
                
                if tunnel.core == "frp":
                    from app.utils import frp_safe_bind_port
                    bind_port = frp_safe_bind_port(tunnel.id, spec.get("bind_port"))
                    
                    token = spec.get("token")
                    if not token:
                        from app.utils import generate_token
                        token = generate_token()
                        spec["token"] = token
                        tunnel.spec["token"] = token
                        from sqlalchemy.orm.attributes import flag_modified
                        flag_modified(tunnel, "spec")
                        await db.commit()
                        await db.refresh(tunnel)
                    
                    iran_node_ip = iran_node.node_metadata.get("ip_address")
                    if not iran_node_ip:
                        tunnel.status = "error"
                        tunnel.error_message = "Iran node has no IP address"
                        await db.commit()
                        raise HTTPException(status_code=400, detail="Iran node has no IP address")
                    
                    server_spec = spec.copy()
                    server_spec["mode"] = "server"
                    server_spec["bind_port"] = bind_port
                    server_spec["token"] = token
                    
                    client_spec = spec.copy()
                    client_spec["mode"] = "client"
                    client_spec["server_addr"] = iran_node_ip
                    client_spec["server_port"] = bind_port
                    client_spec["token"] = token
                    tunnel_type = tunnel.type.lower() if tunnel.type else "tcp"
                    if tunnel_type not in ["tcp", "udp"]:
                        tunnel_type = "tcp"
                    client_spec["type"] = tunnel_type
                    
                    ports = spec.get("ports", [])
                    if not ports:
                        local_port = spec.get("local_port")
                        remote_port = spec.get("remote_port") or spec.get("listen_port")
                        if remote_port and local_port:
                            client_spec["ports"] = [{"local": int(local_port), "remote": int(remote_port)}]
                        elif remote_port:
                            client_spec["ports"] = [{"local": int(remote_port), "remote": int(remote_port)}]
                        elif local_port:
                            client_spec["ports"] = [{"local": int(local_port), "remote": int(local_port)}]
                    else:
                        client_spec["ports"] = ports
                
                elif tunnel.core == "rathole":
                    transport = spec.get("transport") or spec.get("type") or "tcp"
                    proxy_port = spec.get("remote_port") or spec.get("listen_port")
                    token = spec.get("token")

                    # WireGuard Stealth (rathole-TLS): make sure cert material is
                    # present (persist for older tunnels), then refresh our spec copy.
                    if (transport or "tcp").lower() == "tls":
                        from app.tls_utils import ensure_wg_stealth_materials
                        if ensure_wg_stealth_materials(tunnel.spec, tunnel.spec.get("sni")):
                            from sqlalchemy.orm.attributes import flag_modified
                            flag_modified(tunnel, "spec")
                            await db.commit()
                            await db.refresh(tunnel)
                        spec = tunnel.spec.copy()
                    
                    if not proxy_port or not token:
                        tunnel.status = "error"
                        tunnel.error_message = "Missing required fields: remote_port/listen_port or token"
                        await db.commit()
                        raise HTTPException(status_code=400, detail="Missing required fields: remote_port/listen_port or token")
                    
                    from app.utils import parse_address_port
                    remote_addr = spec.get("remote_addr", "0.0.0.0:23333")
                    _, control_port, _ = parse_address_port(remote_addr)
                    if not control_port:
                        import hashlib
                        port_hash = int(hashlib.md5(tunnel.id.encode()).hexdigest()[:8], 16)
                        control_port = 23333 + (port_hash % 1000)
                    
                    server_spec = spec.copy()
                    server_spec["mode"] = "server"
                    server_spec["bind_addr"] = f"0.0.0.0:{control_port}"
                    server_spec["proxy_port"] = proxy_port
                    server_spec["transport"] = transport
                    server_spec["token"] = token
                    
                    iran_node_ip = iran_node.node_metadata.get("ip_address")
                    if not iran_node_ip:
                        tunnel.status = "error"
                        tunnel.error_message = "Iran node has no IP address"
                        await db.commit()
                        raise HTTPException(status_code=400, detail="Iran node has no IP address")
                    
                    client_spec = spec.copy()
                    client_spec["mode"] = "client"
                    transport_lower = transport.lower()
                    if transport_lower in ("websocket", "ws"):
                        use_tls = bool(spec.get("websocket_tls") or spec.get("tls"))
                        protocol = "wss://" if use_tls else "ws://"
                        client_spec["remote_addr"] = f"{protocol}{iran_node_ip}:{control_port}"
                    else:
                        client_spec["remote_addr"] = f"{iran_node_ip}:{control_port}"
                    client_spec["transport"] = transport
                    client_spec["token"] = token
                
                elif tunnel.core == "chisel":
                    listen_port = spec.get("listen_port") or spec.get("remote_port")
                    if not listen_port:
                        tunnel.status = "error"
                        tunnel.error_message = "Missing required field: listen_port or remote_port"
                        await db.commit()
                        raise HTTPException(status_code=400, detail="Missing required field: listen_port or remote_port")
                    
                    import hashlib
                    port_hash = int(hashlib.md5(tunnel.id.encode()).hexdigest()[:8], 16)
                    server_control_port = spec.get("control_port") or (int(listen_port) + 10000 + (port_hash % 1000))
                    
                    server_spec = spec.copy()
                    server_spec["mode"] = "server"
                    server_spec["server_port"] = server_control_port
                    server_spec["reverse_port"] = listen_port
                    
                    iran_node_ip = iran_node.node_metadata.get("ip_address")
                    if not iran_node_ip:
                        tunnel.status = "error"
                        tunnel.error_message = "Iran node has no IP address"
                        await db.commit()
                        raise HTTPException(status_code=400, detail="Iran node has no IP address")
                    
                    client_spec = spec.copy()
                    client_spec["mode"] = "client"
                    from app.utils import is_valid_ipv6_address
                    if is_valid_ipv6_address(iran_node_ip):
                        client_spec["server_url"] = f"http://[{iran_node_ip}]:{server_control_port}"
                    else:
                        client_spec["server_url"] = f"http://{iran_node_ip}:{server_control_port}"
                    client_spec["reverse_port"] = listen_port
                
                elif tunnel.core == "udp2raw":
                    # Iran node runs the udp2raw CLIENT (public entry), foreign node
                    # runs the udp2raw SERVER. server_spec -> iran, client_spec -> foreign.
                    raw_mode = (tunnel.type or spec.get("raw_mode") or "faketcp").lower()
                    if raw_mode not in {"faketcp", "icmp", "udp"}:
                        raw_mode = "faketcp"
                    
                    key = spec.get("key") or spec.get("token")
                    if not key:
                        from app.utils import generate_token
                        key = generate_token()
                        spec["key"] = key
                        tunnel.spec["key"] = key
                        from sqlalchemy.orm.attributes import flag_modified
                        flag_modified(tunnel, "spec")
                        await db.commit()
                        await db.refresh(tunnel)
                    
                    ports = parse_ports_from_spec(spec)
                    listen_port = spec.get("listen_port") or spec.get("public_port") or (ports[0] if ports else None)
                    if not listen_port:
                        tunnel.status = "error"
                        tunnel.error_message = "udp2raw requires listen_port"
                        await db.commit()
                        raise HTTPException(status_code=400, detail="udp2raw requires listen_port")
                    
                    import hashlib
                    port_hash = int(hashlib.md5(tunnel.id.encode()).hexdigest()[:8], 16)
                    raw_port = spec.get("raw_port") or (4096 + (port_hash % 1000))
                    target_host = spec.get("target_host", "127.0.0.1")
                    target_port = spec.get("target_port") or listen_port
                    cipher_mode = spec.get("cipher_mode") or "aes128cbc"
                    auth_mode = spec.get("auth_mode") or "md5"
                    
                    foreign_node_ip = foreign_node.node_metadata.get("ip_address")
                    if not foreign_node_ip:
                        tunnel.status = "error"
                        tunnel.error_message = "Foreign node has no IP address"
                        await db.commit()
                        raise HTTPException(status_code=400, detail="Foreign node has no IP address")
                    
                    from app.utils import format_address_port
                    server_spec = spec.copy()
                    server_spec["mode"] = "client"
                    server_spec["raw_mode"] = raw_mode
                    server_spec["listen_addr"] = f"0.0.0.0:{listen_port}"
                    server_spec["remote_addr"] = format_address_port(foreign_node_ip, int(raw_port))
                    server_spec["key"] = key
                    server_spec["cipher_mode"] = cipher_mode
                    server_spec["auth_mode"] = auth_mode
                    
                    client_spec = spec.copy()
                    client_spec["mode"] = "server"
                    client_spec["raw_mode"] = raw_mode
                    client_spec["listen_addr"] = f"0.0.0.0:{raw_port}"
                    client_spec["forward_addr"] = format_address_port(target_host, int(target_port))
                    client_spec["key"] = key
                    client_spec["cipher_mode"] = cipher_mode
                    client_spec["auth_mode"] = auth_mode

                elif tunnel.core == "trusttunnel":
                    # Iran node runs rstund (server, public listener); foreign node
                    # runs rstunc (client). server_spec -> iran, client_spec -> foreign.
                    transport = (tunnel.type or spec.get("transport") or "tcp").lower()
                    if transport not in {"tcp", "udp", "both"}:
                        transport = "tcp"

                    password = spec.get("password") or spec.get("token")
                    if not password:
                        from app.utils import generate_token
                        password = generate_token(24)
                        spec["password"] = password
                        tunnel.spec["password"] = password
                        from sqlalchemy.orm.attributes import flag_modified
                        flag_modified(tunnel, "spec")
                        await db.commit()
                        await db.refresh(tunnel)

                    ports = parse_ports_from_spec(spec)
                    if not ports:
                        single = spec.get("listen_port") or spec.get("public_port") or spec.get("remote_port")
                        if single and str(single).isdigit():
                            ports = [int(single)]
                    if not ports:
                        tunnel.status = "error"
                        tunnel.error_message = "TrustTunnel requires ports"
                        await db.commit()
                        raise HTTPException(status_code=400, detail="TrustTunnel requires ports")

                    import hashlib
                    port_hash = int(hashlib.md5(tunnel.id.encode()).hexdigest()[:8], 16)
                    control_port = spec.get("control_port") or (6100 + (port_hash % 800))
                    target_host = spec.get("target_host", "127.0.0.1")

                    iran_node_ip = iran_node.node_metadata.get("ip_address")
                    if not iran_node_ip:
                        tunnel.status = "error"
                        tunnel.error_message = "Iran node has no IP address"
                        await db.commit()
                        raise HTTPException(status_code=400, detail="Iran node has no IP address")

                    from app.utils import format_address_port
                    server_spec = spec.copy()
                    server_spec["mode"] = "server"
                    server_spec["transport"] = transport
                    server_spec["password"] = password
                    server_spec["control_port"] = control_port
                    server_spec["target_host"] = target_host
                    server_spec["ports"] = ports

                    client_spec = spec.copy()
                    client_spec["mode"] = "client"
                    client_spec["transport"] = transport
                    client_spec["password"] = password
                    client_spec["server_addr"] = format_address_port(iran_node_ip, int(control_port))
                    client_spec["target_host"] = target_host
                    client_spec["ports"] = ports

                elif tunnel.core == "hysteria2":
                    # Hysteria2 QUIC carrier: FOREIGN = server, IRAN = client.
                    # server_spec -> iran, client_spec -> foreign.
                    ttype = (tunnel.type or spec.get("type") or "udp").lower()
                    ports = parse_ports_from_spec(spec)
                    if not ports:
                        single = spec.get("listen_port") or spec.get("public_port")
                        if single and str(single).isdigit():
                            ports = [int(single)]
                    if not ports:
                        tunnel.status = "error"
                        tunnel.error_message = "Hysteria2 requires ports"
                        await db.commit()
                        raise HTTPException(status_code=400, detail="Hysteria2 requires ports")
                    foreign_node_ip = foreign_node.node_metadata.get("ip_address")
                    if not foreign_node_ip:
                        tunnel.status = "error"
                        tunnel.error_message = "Foreign node has no IP address"
                        await db.commit()
                        raise HTTPException(status_code=400, detail="Foreign node has no IP address")
                    iran_node_ip = iran_node.node_metadata.get("ip_address")
                    spec["ports"] = ports
                    server_spec, client_spec, resolved = build_hysteria2_specs(
                        spec, tunnel.id, ttype, iran_node_ip or "", foreign_node_ip
                    )
                    for k in ("auth", "obfs_password", "sni", "control_port", "target_host", "type"):
                        tunnel.spec[k] = resolved[k]
                    tunnel.spec["ports"] = ports
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(tunnel, "spec")
                    await db.commit()
                    await db.refresh(tunnel)

                elif tunnel.core == "tuic":
                    # TUIC QUIC carrier: FOREIGN = tuic-server, IRAN = tuic-client.
                    # server_spec -> iran, client_spec -> foreign.
                    ttype = (tunnel.type or spec.get("type") or "udp").lower()
                    ports = parse_ports_from_spec(spec)
                    if not ports:
                        single = spec.get("listen_port") or spec.get("public_port")
                        if single and str(single).isdigit():
                            ports = [int(single)]
                    if not ports:
                        tunnel.status = "error"
                        tunnel.error_message = "TUIC requires ports"
                        await db.commit()
                        raise HTTPException(status_code=400, detail="TUIC requires ports")
                    foreign_node_ip = foreign_node.node_metadata.get("ip_address")
                    if not foreign_node_ip:
                        tunnel.status = "error"
                        tunnel.error_message = "Foreign node has no IP address"
                        await db.commit()
                        raise HTTPException(status_code=400, detail="Foreign node has no IP address")
                    iran_node_ip = iran_node.node_metadata.get("ip_address")
                    spec["ports"] = ports
                    server_spec, client_spec, resolved = build_tuic_specs(
                        spec, tunnel.id, ttype, iran_node_ip or "", foreign_node_ip
                    )
                    for k in ("uuid", "password", "sni", "control_port", "target_host", "type", "udp_relay_mode", "congestion_control"):
                        tunnel.spec[k] = resolved[k]
                    tunnel.spec["ports"] = ports
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(tunnel, "spec")
                    await db.commit()
                    await db.refresh(tunnel)

                if not iran_node.node_metadata.get("api_address"):
                    iran_node.node_metadata["api_address"] = f"http://{iran_node.node_metadata.get('ip_address', iran_node.fingerprint)}:{iran_node.node_metadata.get('api_port', 8888)}"
                    await db.commit()
                
                logger.info(f"Reapplying tunnel {tunnel.id}: applying server config to iran node {iran_node.id}")
                server_response = await client.send_to_node(
                    node_id=iran_node.id,
                    endpoint="/api/agent/tunnels/apply",
                    data={
                        "tunnel_id": tunnel.id,
                        "core": tunnel.core,
                        "type": tunnel.type,
                        "spec": server_spec if tunnel.core in ["backhaul", "frp", "rathole", "chisel", "udp2raw", "trusttunnel", "hysteria2", "tuic"] else spec
                    }
                )
                
                if server_response.get("status") == "error":
                    tunnel.status = "error"
                    error_msg = server_response.get("message", "Unknown error from iran node")
                    tunnel.error_message = f"Iran node error: {error_msg}"
                    await db.commit()
                    raise HTTPException(status_code=500, detail=error_msg)
                
                if not foreign_node.node_metadata.get("api_address"):
                    foreign_node.node_metadata["api_address"] = f"http://{foreign_node.node_metadata.get('ip_address', foreign_node.fingerprint)}:{foreign_node.node_metadata.get('api_port', 8888)}"
                    await db.commit()
                
                logger.info(f"Reapplying tunnel {tunnel.id}: applying client config to foreign node {foreign_node.id}")
                client_response = await client.send_to_node(
                    node_id=foreign_node.id,
                    endpoint="/api/agent/tunnels/apply",
                    data={
                        "tunnel_id": tunnel.id,
                        "core": tunnel.core,
                        "type": tunnel.type,
                        "spec": client_spec if tunnel.core in ["backhaul", "frp", "rathole", "chisel", "udp2raw", "trusttunnel", "hysteria2", "tuic"] else spec
                    }
                )
                
                if client_response.get("status") == "error":
                    tunnel.status = "error"
                    error_msg = client_response.get("message", "Unknown error from foreign node")
                    tunnel.error_message = f"Foreign node error: {error_msg}"
                    await db.commit()
                    raise HTTPException(status_code=500, detail=error_msg)
                
                if server_response.get("status") == "success" and client_response.get("status") == "success":
                    tunnel.status = "active"
                    tunnel.error_message = None
                    await db.commit()
                    return {"status": "applied", "message": "Tunnel reapplied successfully to both nodes"}
                else:
                    tunnel.status = "error"
                    tunnel.error_message = "Failed to apply tunnel to one or both nodes"
                    await db.commit()
                    raise HTTPException(status_code=500, detail="Failed to apply tunnel to one or both nodes")
            except HTTPException:
                raise
            except Exception as e:
                tunnel.status = "error"
                tunnel.error_message = f"Error: {str(e)}"
                await db.commit()
                raise HTTPException(status_code=500, detail=f"Failed to reapply tunnel: {str(e)}")
    
    result = await db.execute(select(Node).where(Node.id == tunnel.node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    
    try:
        if not node.node_metadata.get("api_address"):
            node.node_metadata["api_address"] = f"http://{node.fingerprint}:8888"
            await db.commit()
        
        spec_for_node = tunnel.spec.copy() if tunnel.spec else {}
        logger.info(f"Reapplying tunnel {tunnel.id} (core={tunnel.core}, type={tunnel.type}): original spec={spec_for_node}")
        
        if tunnel.core == "gost":
            spec_for_node["type"] = tunnel.type
        
        if tunnel.core == "frp":
            try:
                spec_for_node = prepare_frp_spec_for_node(spec_for_node, node, request)
                logger.info(f"FRP spec prepared for tunnel {tunnel.id}: server_addr={spec_for_node.get('server_addr')}, server_port={spec_for_node.get('server_port')}, full spec={spec_for_node}")
            except Exception as e:
                error_msg = f"Failed to prepare FRP spec: {str(e)}"
                logger.error(f"Tunnel {tunnel.id}: {error_msg}", exc_info=True)
                raise HTTPException(status_code=500, detail=error_msg)
        
        logger.info(f"Sending tunnel {tunnel.id} to node {node.id}: spec={spec_for_node}")
        response = await client.send_to_node(
            node_id=node.id,
            endpoint="/api/agent/tunnels/apply",
            data={
                "tunnel_id": tunnel.id,
                "core": tunnel.core,
                "type": tunnel.type,
                "spec": spec_for_node
            }
        )
        
        if response.get("status") == "success":
            tunnel.status = "active"
            tunnel.error_message = None
            await db.commit()
            return {"status": "applied", "message": "Tunnel reapplied successfully"}
        else:
            error_msg = response.get("message", "Failed to apply tunnel")
            tunnel.status = "error"
            tunnel.error_message = error_msg
            await db.commit()
            raise HTTPException(status_code=500, detail=error_msg)
    except HTTPException:
        raise
    except Exception as e:
        tunnel.status = "error"
        tunnel.error_message = f"Error: {str(e)}"
        await db.commit()
        raise HTTPException(status_code=500, detail=f"Failed to apply tunnel: {str(e)}")


@router.post("/reapply-all")
async def reapply_all_tunnels(request: Request, db: AsyncSession = Depends(get_db)):
    """Reapply all tunnels"""
    result = await db.execute(select(Tunnel))
    tunnels = result.scalars().all()
    
    if not tunnels:
        return {"status": "success", "message": "No tunnels to reapply", "applied": 0, "failed": 0}
    
    applied = 0
    failed = 0
    errors = []
    
    # Call apply_tunnel for each tunnel
    for tunnel in tunnels:
        try:
            # Call apply_tunnel directly - it's in the same module
            try:
                result_data = await apply_tunnel(tunnel.id, request, db)
                if result_data and result_data.get("status") == "applied":
                    applied += 1
                else:
                    failed += 1
                    errors.append(f"Tunnel {tunnel.name}: Failed to apply")
            except HTTPException as e:
                failed += 1
                errors.append(f"Tunnel {tunnel.name}: {e.detail}")
            except Exception as e:
                failed += 1
                error_msg = str(e)
                errors.append(f"Tunnel {tunnel.name}: {error_msg}")
        except Exception as e:
            logger.error(f"Error reapplying tunnel {tunnel.id}: {e}", exc_info=True)
            failed += 1
            errors.append(f"Tunnel {tunnel.name}: {str(e)}")
    
    return {
        "status": "success",
        "message": f"Reapplied {applied} tunnels, {failed} failed",
        "applied": applied,
        "failed": failed,
        "errors": errors[:10]  # Limit errors to first 10
    }


@router.delete("/{tunnel_id}")
async def delete_tunnel(tunnel_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Delete a tunnel"""
    result = await db.execute(select(Tunnel).where(Tunnel.id == tunnel_id))
    tunnel = result.scalar_one_or_none()
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    
    needs_gost_forwarding = tunnel.type in ["tcp", "udp", "ws", "grpc"] and tunnel.core == "gost"
    needs_rathole_server = tunnel.core == "rathole"
    needs_backhaul_server = tunnel.core == "backhaul"
    needs_chisel_server = tunnel.core == "chisel"
    needs_frp_server = tunnel.core == "frp"
    
    if needs_gost_forwarding:
        if hasattr(request.app.state, 'gost_forwarder'):
            try:
                request.app.state.gost_forwarder.stop_forward(tunnel.id)
            except Exception as e:
                import logging
                logging.error(f"Failed to stop gost forwarding: {e}")
    
    elif needs_rathole_server:
        if hasattr(request.app.state, 'rathole_server_manager'):
            try:
                request.app.state.rathole_server_manager.stop_server(tunnel.id)
            except Exception as e:
                import logging
                logging.error(f"Failed to stop Rathole server: {e}")
    elif needs_backhaul_server:
        if hasattr(request.app.state, "backhaul_manager"):
            try:
                request.app.state.backhaul_manager.stop_server(tunnel.id)
            except Exception as e:
                import logging
                logging.error(f"Failed to stop Backhaul server: {e}")
    elif needs_chisel_server:
        if hasattr(request.app.state, 'chisel_server_manager'):
            try:
                request.app.state.chisel_server_manager.stop_server(tunnel.id)
            except Exception as e:
                import logging
                logging.error(f"Failed to stop Chisel server: {e}")
    elif needs_frp_server:
        if hasattr(request.app.state, 'frp_server_manager'):
            try:
                request.app.state.frp_server_manager.stop_server(tunnel.id)
            except Exception as e:
                import logging
                logging.error(f"Failed to stop FRP server: {e}")
    
    if tunnel.core in ("udp2raw", "zapret", "trusttunnel", "snispoof", "hysteria2", "tuic", "obfs4", "warp"):
        # udp2raw/trusttunnel/hysteria2/tuic/obfs4 run on both the iran and
        # foreign nodes; zapret/snispoof/warp run on one node but may have been
        # registered under node_id/iran/foreign. Remove from each so every
        # process (and any iptables rules) is torn down.
        client = NodeClient()
        node_ids = {tunnel.node_id, tunnel.iran_node_id, tunnel.foreign_node_id}
        for node_id in node_ids:
            if not node_id:
                continue
            result = await db.execute(select(Node).where(Node.id == node_id))
            node = result.scalar_one_or_none()
            if node:
                try:
                    await client.send_to_node(
                        node_id=node.id,
                        endpoint="/api/agent/tunnels/remove",
                        data={"tunnel_id": tunnel.id}
                    )
                except:
                    pass
    elif tunnel.status == "active":
        result = await db.execute(select(Node).where(Node.id == tunnel.node_id))
        node = result.scalar_one_or_none()
        if node:
            client = NodeClient()
            try:
                await client.send_to_node(
                    node_id=node.id,
                    endpoint="/api/agent/tunnels/remove",
                    data={"tunnel_id": tunnel.id}
                )
            except:
                pass
    
    await db.delete(tunnel)
    await db.commit()
    return {"status": "deleted"}


