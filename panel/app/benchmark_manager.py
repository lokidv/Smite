"""Benchmark orchestration: test every tunnel core x mode between two nodes.

For each combo the manager (sequentially, on dedicated test ports and unique
bench-* tunnel ids so real tunnels are never touched):
  1. starts a sink on the foreign node (the tunnel's local target),
  2. applies a test tunnel to the iran node (server role) and the foreign
     node (client role) exactly like the real spec builders do,
  3. asks the iran node to probe 127.0.0.1:<test_port> through the tunnel,
     measuring latency, throughput and packet loss,
  4. tears everything down and records the metrics.

Results are ranked with a composite quality score so the UI can recommend
the best core/mode for the selected node pair.
"""
import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.node_client import NodeClient
from app.utils import generate_token, format_address_port

logger = logging.getLogger(__name__)

COMBO_METADATA: List[Dict[str, Any]] = [
    {
        "id": "awg_ws:tls",
        "core": "awg_ws",
        "mode": "tls",
        "category": "nextgen",
        "protocol": "udp",
        "label": "👑 AWG-over-WebSocket (Digikala TLS)",
        "label_fa": "👑 AWG-over-WebSocket (دیجی‌کالا TLS)",
        "mode_label": "Digikala TLS (Port 8581)",
        "mode_label_fa": "حالت: دیجی‌کالا TLS (پورت ۸۵۸۱)",
        "description": "AmneziaWG UDP over reverse WebSocket + TLS camouflage with Digikala SNI disguise",
        "stealth": True,
        "default_selected": True,
        "badge": "جدید",
    },
    {
        "id": "mport_hop:udp",
        "core": "mport_hop",
        "mode": "udp",
        "category": "nextgen",
        "protocol": "udp",
        "label": "🛡️ Dynamic Multi-Port Hopping",
        "label_fa": "🛡️ Dynamic Multi-Port Hopping (پرش پورت)",
        "mode_label": "Kernel NAT (20000:40000)",
        "mode_label_fa": "حالت: پرش پورت در سطح کرنل (20000:40000)",
        "description": "Kernel iptables PREROUTING port hopping for WireGuard with 0% CPU overhead",
        "stealth": True,
        "default_selected": True,
        "badge": "جدید",
    },
    {
        "id": "fec_faketcp:faketcp",
        "core": "fec_faketcp",
        "mode": "faketcp",
        "category": "nextgen",
        "protocol": "udp",
        "label": "⚡ FEC + FakeTCP (Zero-Packet-Loss)",
        "label_fa": "⚡ FEC + FakeTCP (ضد پکت‌لاس شدید)",
        "mode_label": "FakeTCP + Reed-Solomon FEC",
        "mode_label_fa": "حالت: FakeTCP + تصحیح خطای FEC",
        "description": "Reed-Solomon Forward Error Correction + Raw Kernel FakeTCP for severe blackout loss",
        "stealth": True,
        "default_selected": True,
        "badge": "جدید",
    },
    {
        "id": "zapret:mci",
        "core": "zapret",
        "mode": "mci",
        "category": "nextgen",
        "protocol": "udp",
        "label": "🔮 Zapret (Anti-DPI Bypass)",
        "label_fa": "🔮 Zapret (بای‌پس فیلترینگ DPI ایران)",
        "mode_label": "Hamrah-e Avval (MCI Anti-DPI)",
        "mode_label_fa": "حالت: همراه اول (MCI Anti-DPI)",
        "description": "Kernel NFQUEUE packet fragmentation & SNI desynchronization for WireGuard and TLS",
        "stealth": True,
        "default_selected": True,
        "badge": "جدید",
    },
    {
        "id": "rathole:tls",
        "core": "rathole",
        "mode": "tls",
        "category": "standard",
        "protocol": "udp",
        "label": "Rathole",
        "label_fa": "Rathole",
        "mode_label": "WireGuard Stealth (TLS+SNI)",
        "mode_label_fa": "حالت: استتار وایرگارد (TLS+SNI)",
        "description": "Native TLS transport with SNI mimicry forwarding WireGuard UDP packets",
        "stealth": True,
        "default_selected": True,
    },
    {
        "id": "udp2raw:faketcp",
        "core": "udp2raw",
        "mode": "faketcp",
        "category": "standard",
        "protocol": "udp",
        "label": "udp2raw (FakeTCP / ICMP)",
        "label_fa": "udp2raw (FakeTCP / ICMP)",
        "mode_label": "FakeTCP",
        "mode_label_fa": "حالت: FakeTCP",
        "description": "Encapsulates UDP in real TCP handshakes to bypass aggressive UDP blocking",
        "stealth": True,
        "default_selected": True,
    },
    {
        "id": "udp2raw:icmp",
        "core": "udp2raw",
        "mode": "icmp",
        "category": "standard",
        "protocol": "udp",
        "label": "udp2raw (FakeTCP / ICMP)",
        "label_fa": "udp2raw (FakeTCP / ICMP)",
        "mode_label": "ICMP (Ping Mode)",
        "mode_label_fa": "حالت: ICMP (پینگ بدون پورت)",
        "description": "Raw ICMP echo frames without ports, survives strict port whitelisting",
        "stealth": True,
        "default_selected": True,
    },
    {
        "id": "udp2raw:udp",
        "core": "udp2raw",
        "mode": "udp",
        "category": "standard",
        "protocol": "udp",
        "label": "udp2raw (FakeTCP / ICMP)",
        "label_fa": "udp2raw (FakeTCP / ICMP)",
        "mode_label": "UDP (Encrypted)",
        "mode_label_fa": "حالت: UDP رمزنگاری شده",
        "description": "Encrypted UDP wrapper with anti-replay and drop defense",
        "stealth": True,
        "default_selected": False,
    },
    {
        "id": "hysteria2:udp",
        "core": "hysteria2",
        "mode": "udp",
        "category": "standard",
        "protocol": "udp",
        "label": "Hysteria2 (QUIC carrier)",
        "label_fa": "Hysteria2 (QUIC carrier)",
        "mode_label": "UDP (Brutal Congestion)",
        "mode_label_fa": "حالت: UDP (کنترل ازدحام تهاجمی)",
        "description": "Custom QUIC protocol delivering throughput over high loss links",
        "stealth": True,
        "default_selected": True,
    },
    {
        "id": "hysteria2:tcp",
        "core": "hysteria2",
        "mode": "tcp",
        "category": "standard",
        "protocol": "tcp",
        "label": "Hysteria2 (QUIC carrier)",
        "label_fa": "Hysteria2 (QUIC carrier)",
        "mode_label": "TCP",
        "mode_label_fa": "حالت: TCP",
        "description": "TCP forwarding over Hysteria 2 QUIC transport",
        "stealth": True,
        "default_selected": False,
    },
    {
        "id": "tuic:udp",
        "core": "tuic",
        "mode": "udp",
        "category": "standard",
        "protocol": "udp",
        "label": "TUIC (QUIC carrier)",
        "label_fa": "TUIC (QUIC carrier)",
        "mode_label": "UDP (0-RTT QUIC)",
        "mode_label_fa": "حالت: UDP (کوئیک بدون تاخیر)",
        "description": "Native QUIC tunneling with 0-RTT fast connection",
        "stealth": True,
        "default_selected": True,
    },
    {
        "id": "tuic:tcp",
        "core": "tuic",
        "mode": "tcp",
        "category": "standard",
        "protocol": "tcp",
        "label": "TUIC (QUIC carrier)",
        "label_fa": "TUIC (QUIC carrier)",
        "mode_label": "TCP",
        "mode_label_fa": "حالت: TCP",
        "description": "TCP streams over TUIC v5 QUIC",
        "stealth": True,
        "default_selected": False,
    },
    {
        "id": "trusttunnel:udp",
        "core": "trusttunnel",
        "mode": "udp",
        "category": "standard",
        "protocol": "udp",
        "label": "TrustTunnel (QUIC)",
        "label_fa": "TrustTunnel (QUIC)",
        "mode_label": "UDP",
        "mode_label_fa": "حالت: UDP",
        "description": "Obfuscated UDP tunnel designed for filtered networks",
        "stealth": True,
        "default_selected": True,
    },
    {
        "id": "trusttunnel:tcp",
        "core": "trusttunnel",
        "mode": "tcp",
        "category": "standard",
        "protocol": "tcp",
        "label": "TrustTunnel (QUIC)",
        "label_fa": "TrustTunnel (QUIC)",
        "mode_label": "TCP",
        "mode_label_fa": "حالت: TCP",
        "description": "Obfuscated TCP tunnel with custom handshake",
        "stealth": True,
        "default_selected": False,
    },
    {
        "id": "rathole:tcp",
        "core": "rathole",
        "mode": "tcp",
        "category": "standard",
        "protocol": "tcp",
        "label": "Rathole",
        "label_fa": "Rathole",
        "mode_label": "TCP",
        "mode_label_fa": "حالت: TCP",
        "description": "High throughput TCP multiplexer with low overhead",
        "stealth": False,
        "default_selected": True,
    },
    {
        "id": "rathole:ws",
        "core": "rathole",
        "mode": "ws",
        "category": "standard",
        "protocol": "tcp",
        "label": "Rathole",
        "label_fa": "Rathole",
        "mode_label": "WebSocket",
        "mode_label_fa": "حالت: WebSocket",
        "description": "WebSocket transport for reverse proxy/CDN setup",
        "stealth": False,
        "default_selected": False,
    },
    {
        "id": "backhaul:tcp",
        "core": "backhaul",
        "mode": "tcp",
        "category": "standard",
        "protocol": "tcp",
        "label": "Backhaul",
        "label_fa": "Backhaul",
        "mode_label": "TCP",
        "mode_label_fa": "حالت: TCP",
        "description": "Go-based high concurrency TCP tunnel",
        "stealth": False,
        "default_selected": True,
    },
    {
        "id": "backhaul:udp",
        "core": "backhaul",
        "mode": "udp",
        "category": "standard",
        "protocol": "udp",
        "label": "Backhaul",
        "label_fa": "Backhaul",
        "mode_label": "UDP",
        "mode_label_fa": "حالت: UDP",
        "description": "Raw UDP forwarding via Backhaul",
        "stealth": False,
        "default_selected": True,
    },
    {
        "id": "backhaul:ws",
        "core": "backhaul",
        "mode": "ws",
        "category": "standard",
        "protocol": "tcp",
        "label": "Backhaul",
        "label_fa": "Backhaul",
        "mode_label": "WebSocket",
        "mode_label_fa": "حالت: WebSocket",
        "description": "WebSocket transport for Web proxies",
        "stealth": False,
        "default_selected": False,
    },
    {
        "id": "backhaul:wsmux",
        "core": "backhaul",
        "mode": "wsmux",
        "category": "standard",
        "protocol": "tcp",
        "label": "Backhaul",
        "label_fa": "Backhaul",
        "mode_label": "WS Mux",
        "mode_label_fa": "حالت: WS Mux",
        "description": "Multiplexed WebSocket streams",
        "stealth": False,
        "default_selected": False,
    },
    {
        "id": "backhaul:tcpmux",
        "core": "backhaul",
        "mode": "tcpmux",
        "category": "standard",
        "protocol": "tcp",
        "label": "Backhaul",
        "label_fa": "Backhaul",
        "mode_label": "TCP Mux",
        "mode_label_fa": "حالت: TCP Mux",
        "description": "Multiplexed TCP connections",
        "stealth": False,
        "default_selected": False,
    },
    {
        "id": "chisel:chisel",
        "core": "chisel",
        "mode": "chisel",
        "category": "standard",
        "protocol": "tcp",
        "label": "Chisel",
        "label_fa": "Chisel",
        "mode_label": "HTTP/TCP",
        "mode_label_fa": "حالت: HTTP/TCP",
        "description": "HTTP reverse TCP tunnel",
        "stealth": False,
        "default_selected": False,
    },
    {
        "id": "frp:tcp",
        "core": "frp",
        "mode": "tcp",
        "category": "standard",
        "protocol": "tcp",
        "label": "FRP",
        "label_fa": "FRP",
        "mode_label": "TCP",
        "mode_label_fa": "حالت: TCP",
        "description": "Fast Reverse Proxy TCP",
        "stealth": False,
        "default_selected": False,
    },
    {
        "id": "frp:udp",
        "core": "frp",
        "mode": "udp",
        "category": "standard",
        "protocol": "udp",
        "label": "FRP",
        "label_fa": "FRP",
        "mode_label": "UDP",
        "mode_label_fa": "حالت: UDP",
        "description": "Fast Reverse Proxy UDP",
        "stealth": False,
        "default_selected": False,
    },
]

# (core, mode/type, probe protocol)
BENCH_COMBOS: List[Tuple[str, str, str]] = [
    (m["core"], m["mode"], m["protocol"]) for m in COMBO_METADATA
]


def get_available_combos() -> List[Dict[str, Any]]:
    """Return available combos with rich metadata for UI selection and ordering."""
    return [dict(c) for c in COMBO_METADATA]

# Dedicated port ranges so test tunnels never collide with real ones.
TEST_PORT_BASE = 17800
CONTROL_PORT_BASE = 18800

SETTLE_SECONDS = 4.0
PING_COUNT = 10
THROUGHPUT_SECONDS = 3.0


def _build_specs(
    core: str,
    mode: str,
    test_port: int,
    control_port: int,
    iran_ip: str,
    foreign_ip: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build (iran_spec, foreign_spec) for a test tunnel, mirroring create_tunnel."""
    token = generate_token()

    if core in ("rathole", "awg_ws"):
        # mode "tls" == WireGuard Stealth: native TLS transport + udp service.
        is_tls = mode == "tls" or core == "awg_ws"
        service_type = "udp" if (is_tls or core == "awg_ws") else "tcp"
        server = {
            "mode": "server",
            "bind_addr": f"0.0.0.0:{control_port}",
            "ports": [test_port],
            "proxy_port": test_port,
            "transport": mode,
            "type": mode,
            "token": token,
            "service_type": service_type,
            "sni": "www.digikala.com" if core == "awg_ws" else None,
        }
        remote = f"wss://{iran_ip}:{control_port}" if (mode in ("ws", "websocket") and is_tls) else (f"ws://{iran_ip}:{control_port}" if mode in ("ws", "websocket") else f"{iran_ip}:{control_port}")
        client = {
            "mode": "client",
            "remote_addr": remote,
            "transport": mode,
            "type": mode,
            "token": token,
            "ports": [test_port],
            "service_type": service_type,
            "sni": "www.digikala.com" if core == "awg_ws" else None,
        }
        if is_tls:
            from app.tls_utils import generate_wg_stealth_cert
            material = generate_wg_stealth_cert("www.digikala.com")
            for s in (server, client):
                s["tls_pkcs12_b64"] = material["pkcs12_b64"]
                s["tls_pkcs12_password"] = material["pkcs12_password"]
                s["tls_ca_pem_b64"] = material["ca_pem_b64"]
                s["sni"] = material["sni"]
        return server, client

    if core == "chisel":
        server = {
            "mode": "server",
            "server_port": control_port,
            "reverse_port": test_port,
            "auth": token,
        }
        client = {
            "mode": "client",
            "server_url": f"http://{iran_ip}:{control_port}",
            "reverse_port": test_port,
            "ports": [test_port],
            "auth": token,
        }
        return server, client

    if core == "frp":
        server = {"mode": "server", "bind_port": control_port, "token": token}
        client = {
            "mode": "client",
            "server_addr": iran_ip,
            "server_port": control_port,
            "token": token,
            "type": mode,
            "local_ip": "127.0.0.1",
            "ports": [{"local": test_port, "remote": test_port}],
        }
        return server, client

    if core == "backhaul":
        server = {
            "mode": "server",
            "bind_addr": f"0.0.0.0:{control_port}",
            "control_port": control_port,
            "transport": mode,
            "type": mode,
            "token": token,
            "ports": [f"{test_port}=127.0.0.1:{test_port}"],
        }
        remote = f"ws://{iran_ip}:{control_port}" if mode in ("ws", "wsmux") else f"{iran_ip}:{control_port}"
        client = {
            "mode": "client",
            "remote_addr": remote,
            "transport": mode,
            "type": mode,
            "token": token,
        }
        return server, client

    if core in ("udp2raw", "fec_faketcp"):
        # Inverted roles: iran runs the udp2raw client (public UDP entry),
        # foreign runs the udp2raw server (raw listener -> local sink).
        cipher = "aes128cfb" if core == "fec_faketcp" else "aes128cbc"
        server = {
            "mode": "client",
            "raw_mode": mode,
            "listen_addr": f"0.0.0.0:{test_port}",
            "remote_addr": format_address_port(foreign_ip, control_port),
            "key": token,
            "cipher_mode": cipher,
            "auth_mode": "md5",
            "seq_mode": 3 if core == "fec_faketcp" else 1,
        }
        client = {
            "mode": "server",
            "raw_mode": mode,
            "listen_addr": f"0.0.0.0:{control_port}",
            "forward_addr": f"127.0.0.1:{test_port}",
            "key": token,
            "cipher_mode": cipher,
            "auth_mode": "md5",
            "seq_mode": 3 if core == "fec_faketcp" else 1,
        }
        return server, client

    if core == "trusttunnel":
        server = {
            "mode": "server",
            "transport": mode,
            "password": token,
            "control_port": control_port,
            "target_host": "127.0.0.1",
            "ports": [test_port],
        }
        client = {
            "mode": "client",
            "transport": mode,
            "password": token,
            "server_addr": format_address_port(iran_ip, control_port),
            "target_host": "127.0.0.1",
            "ports": [test_port],
        }
        return server, client

    if core == "hysteria2":
        # Inverted roles (like udp2raw): iran runs the hysteria CLIENT (public
        # forward listener -> probe entry), foreign runs the hysteria SERVER
        # (dials the local sink). server -> iran, client -> foreign.
        obfs = generate_token(16)
        iran_spec = {
            "mode": "client",
            "type": mode,
            "server_addr": format_address_port(foreign_ip, control_port),
            "sni": "www.bing.com",
            "auth": token,
            "obfs_password": obfs,
            "forwards": [{"listen": f"0.0.0.0:{test_port}", "remote": f"127.0.0.1:{test_port}", "protocol": mode}],
        }
        foreign_spec = {
            "mode": "server",
            "type": mode,
            "listen_port": control_port,
            "control_port": control_port,
            "sni": "www.bing.com",
            "auth": token,
            "obfs_password": obfs,
        }
        return iran_spec, foreign_spec

    if core == "tuic":
        # Inverted roles (like hysteria2): iran runs the tuic CLIENT (public
        # forward listener -> probe entry), foreign runs the tuic SERVER (dials
        # the local sink). server -> iran, client -> foreign.
        import uuid as uuid_mod
        tuic_uuid = str(uuid_mod.uuid4())
        iran_spec = {
            "mode": "client",
            "type": mode,
            "server_addr": format_address_port(foreign_ip, control_port),
            "sni": "www.bing.com",
            "uuid": tuic_uuid,
            "password": token,
            "udp_relay_mode": "native",
            "forwards": [{"listen": f"0.0.0.0:{test_port}", "remote": f"127.0.0.1:{test_port}", "protocol": mode}],
        }
        foreign_spec = {
            "mode": "server",
            "type": mode,
            "listen_port": control_port,
            "control_port": control_port,
            "sni": "www.bing.com",
            "uuid": tuic_uuid,
            "password": token,
        }
        return iran_spec, foreign_spec

    if core == "mport_hop":
        server = {
            "mode": "server",
            "target_port": test_port,
            "port_range": f"{test_port}:{test_port+5}",
            "ports": [test_port],
        }
        client = {
            "mode": "client",
            "target_port": test_port,
            "port_range": f"{test_port}:{test_port+5}",
            "ports": [test_port],
        }
        return server, client

    if core == "zapret":
        preset = mode or "mci"
        server = {
            "mode": "server",
            "preset": preset,
            "filter_udp": str(test_port),
            "filter_tcp": str(test_port),
            "ports": [test_port],
        }
        client = {
            "mode": "client",
            "preset": preset,
            "filter_udp": str(test_port),
            "filter_tcp": str(test_port),
            "ports": [test_port],
        }
        return server, client

    raise ValueError(f"Unsupported benchmark core: {core}")


def _score(metrics: Optional[Dict[str, Any]]) -> float:
    """Composite 0-100 quality score (throughput 60%, latency 30%, loss 10%)."""
    if not metrics or not metrics.get("ok"):
        return 0.0
    throughput = float(metrics.get("throughput_mbps") or 0.0)
    latency = float(metrics.get("latency_ms") or 500.0)
    loss = float(metrics.get("loss_percent") or 0.0)
    thr_score = min(throughput / 100.0, 1.0) * 60.0
    lat_score = max(0.0, 1.0 - min(latency, 500.0) / 500.0) * 30.0
    loss_score = max(0.0, 1.0 - loss / 100.0) * 10.0
    return round(thr_score + lat_score + loss_score, 1)


class BenchmarkManager:
    """Singleton-style manager running at most one benchmark at a time."""

    def __init__(self):
        self.state: Dict[str, Any] = {"status": "idle"}
        self._task: Optional[asyncio.Task] = None

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def get_state(self) -> Dict[str, Any]:
        return self.state

    def start(
        self,
        iran_node_id: str,
        iran_node_name: str,
        iran_ip: str,
        foreign_node_id: str,
        foreign_node_name: str,
        foreign_ip: str,
        cores: Optional[List[str]] = None,
        custom_combos: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        if self.is_running():
            raise RuntimeError("A benchmark is already running")

        combos: List[Tuple[str, str, str]] = []
        if custom_combos:
            for item in custom_combos:
                c_core = item.get("core")
                c_mode = item.get("mode")
                c_proto = item.get("protocol")
                if not c_core or not c_mode:
                    c_id = item.get("id", "")
                    if ":" in c_id:
                        c_core, c_mode = c_id.split(":", 1)
                if not c_proto:
                    matched = next((m for m in COMBO_METADATA if m["core"] == c_core and m["mode"] == c_mode), None)
                    c_proto = matched["protocol"] if matched else "tcp"
                if c_core and c_mode and c_proto:
                    combos.append((c_core, c_mode, c_proto))
        elif cores:
            combos = [c for c in BENCH_COMBOS if c[0] in cores]
        else:
            combos = list(BENCH_COMBOS)

        if not combos:
            raise ValueError("No benchmark combos match the requested criteria")

        benchmark_id = f"bench-{uuid.uuid4().hex[:8]}"
        self.state = {
            "status": "running",
            "benchmark_id": benchmark_id,
            "iran_node_id": iran_node_id,
            "iran_node_name": iran_node_name,
            "foreign_node_id": foreign_node_id,
            "foreign_node_name": foreign_node_name,
            "total": len(combos),
            "completed": 0,
            "current": None,
            "results": [],
            "started_at": time.time(),
            "finished_at": None,
            "error": None,
        }
        self._task = asyncio.create_task(
            self._run(benchmark_id, combos, iran_node_id, foreign_node_id, iran_ip, foreign_ip)
        )
        return benchmark_id

    async def _run(
        self,
        benchmark_id: str,
        combos: List[Tuple[str, str, str]],
        iran_node_id: str,
        foreign_node_id: str,
        iran_ip: str,
        foreign_ip: str,
    ):
        client = NodeClient()
        try:
            for index, (core, mode, protocol) in enumerate(combos):
                self.state["current"] = {"core": core, "mode": mode}
                test_port = TEST_PORT_BASE + index
                control_port = CONTROL_PORT_BASE + index
                tunnel_id = f"{benchmark_id}-{core}-{mode}"
                result: Dict[str, Any] = {
                    "core": core,
                    "mode": mode,
                    "protocol": protocol,
                    "ok": False,
                    "latency_ms": None,
                    "throughput_mbps": None,
                    "loss_percent": None,
                    "score": 0.0,
                    "error": None,
                }
                try:
                    metrics = await self._run_combo(
                        client, tunnel_id, core, mode, protocol,
                        test_port, control_port,
                        iran_node_id, foreign_node_id, iran_ip, foreign_ip,
                    )
                    result["ok"] = bool(metrics.get("ok"))
                    result["latency_ms"] = metrics.get("latency_ms")
                    result["throughput_mbps"] = metrics.get("throughput_mbps")
                    result["loss_percent"] = metrics.get("loss_percent")
                    result["error"] = metrics.get("error")
                    result["score"] = _score(metrics)
                except Exception as e:
                    logger.warning(f"Benchmark combo {core}/{mode} failed: {e}")
                    result["error"] = str(e)

                self.state["results"].append(result)
                self.state["completed"] = index + 1

            # Rank: successful combos by score desc, failures last.
            self.state["results"].sort(key=lambda r: (not r["ok"], -(r["score"] or 0.0)))
            self.state["status"] = "done"
        except Exception as e:
            logger.error(f"Benchmark {benchmark_id} aborted: {e}", exc_info=True)
            self.state["status"] = "error"
            self.state["error"] = str(e)
        finally:
            self.state["current"] = None
            self.state["finished_at"] = time.time()

    async def _run_combo(
        self,
        client: NodeClient,
        tunnel_id: str,
        core: str,
        mode: str,
        protocol: str,
        test_port: int,
        control_port: int,
        iran_node_id: str,
        foreign_node_id: str,
        iran_ip: str,
        foreign_ip: str,
    ) -> Dict[str, Any]:
        iran_spec, foreign_spec = _build_specs(core, mode, test_port, control_port, iran_ip, foreign_ip)

        try:
            # 1. Sink on the foreign node = the tunnel's local target service.
            sink_response = await client.send_to_node(
                node_id=foreign_node_id,
                endpoint="/api/agent/benchmark/sink/start",
                data={"sink_id": tunnel_id, "port": test_port, "protocol": protocol, "duration_sec": 120},
            )
            if sink_response.get("status") != "success":
                raise RuntimeError(f"Foreign sink failed: {sink_response.get('message', 'unknown error')}")

            # 2. Apply the test tunnel on both nodes (iran first: it hosts the
            # listener the foreign side dials into for most cores).
            server_response = await client.send_to_node(
                node_id=iran_node_id,
                endpoint="/api/agent/tunnels/apply",
                data={"tunnel_id": tunnel_id, "core": core, "type": mode, "spec": iran_spec},
            )
            if server_response.get("status") != "success":
                raise RuntimeError(f"Iran apply failed: {server_response.get('message', 'unknown error')}")

            client_response = await client.send_to_node(
                node_id=foreign_node_id,
                endpoint="/api/agent/tunnels/apply",
                data={"tunnel_id": tunnel_id, "core": core, "type": mode, "spec": foreign_spec},
            )
            if client_response.get("status") != "success":
                raise RuntimeError(f"Foreign apply failed: {client_response.get('message', 'unknown error')}")

            # 3. Let the tunnel establish, then probe from the iran node.
            await asyncio.sleep(SETTLE_SECONDS)

            probe_response = await client.send_to_node(
                node_id=iran_node_id,
                endpoint="/api/agent/benchmark/probe",
                data={
                    "host": "127.0.0.1",
                    "port": test_port,
                    "protocol": protocol,
                    "ping_count": PING_COUNT,
                    "throughput_seconds": THROUGHPUT_SECONDS,
                },
            )
            if probe_response.get("status") != "success":
                raise RuntimeError(f"Probe failed: {probe_response.get('message', 'unknown error')}")
            return probe_response.get("metrics") or {"ok": False, "error": "No metrics returned"}
        finally:
            # 4. Teardown, best effort.
            for node_id in (iran_node_id, foreign_node_id):
                try:
                    await client.send_to_node(
                        node_id=node_id,
                        endpoint="/api/agent/tunnels/remove",
                        data={"tunnel_id": tunnel_id},
                    )
                except Exception:
                    pass
            try:
                await client.send_to_node(
                    node_id=foreign_node_id,
                    endpoint="/api/agent/benchmark/sink/stop",
                    data={"sink_id": tunnel_id},
                )
            except Exception:
                pass


benchmark_manager = BenchmarkManager()
