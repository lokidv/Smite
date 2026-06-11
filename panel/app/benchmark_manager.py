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

# (core, mode/type, probe protocol)
BENCH_COMBOS: List[Tuple[str, str, str]] = [
    ("rathole", "tcp", "tcp"),
    ("rathole", "ws", "tcp"),
    ("backhaul", "tcp", "tcp"),
    ("backhaul", "udp", "udp"),
    ("backhaul", "ws", "tcp"),
    ("backhaul", "wsmux", "tcp"),
    ("backhaul", "tcpmux", "tcp"),
    ("chisel", "chisel", "tcp"),
    ("frp", "tcp", "tcp"),
    ("frp", "udp", "udp"),
    ("udp2raw", "faketcp", "udp"),
    ("udp2raw", "icmp", "udp"),
    ("udp2raw", "udp", "udp"),
    ("trusttunnel", "tcp", "tcp"),
    ("trusttunnel", "udp", "udp"),
    ("trusttunnel", "both", "tcp"),
    ("hysteria2", "tcp", "tcp"),
    ("hysteria2", "udp", "udp"),
    ("tuic", "tcp", "tcp"),
    ("tuic", "udp", "udp"),
]

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

    if core == "rathole":
        server = {
            "mode": "server",
            "bind_addr": f"0.0.0.0:{control_port}",
            "ports": [test_port],
            "proxy_port": test_port,
            "transport": mode,
            "type": mode,
            "token": token,
        }
        remote = f"ws://{iran_ip}:{control_port}" if mode in ("ws", "websocket") else f"{iran_ip}:{control_port}"
        client = {
            "mode": "client",
            "remote_addr": remote,
            "transport": mode,
            "type": mode,
            "token": token,
            "ports": [test_port],
        }
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

    if core == "udp2raw":
        # Inverted roles: iran runs the udp2raw client (public UDP entry),
        # foreign runs the udp2raw server (raw listener -> local sink).
        server = {
            "mode": "client",
            "raw_mode": mode,
            "listen_addr": f"0.0.0.0:{test_port}",
            "remote_addr": format_address_port(foreign_ip, control_port),
            "key": token,
            "cipher_mode": "aes128cbc",
            "auth_mode": "md5",
        }
        client = {
            "mode": "server",
            "raw_mode": mode,
            "listen_addr": f"0.0.0.0:{control_port}",
            "forward_addr": f"127.0.0.1:{test_port}",
            "key": token,
            "cipher_mode": "aes128cbc",
            "auth_mode": "md5",
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
    ) -> str:
        if self.is_running():
            raise RuntimeError("A benchmark is already running")

        combos = [c for c in BENCH_COMBOS if not cores or c[0] in cores]
        if not combos:
            raise ValueError("No benchmark combos match the requested cores")

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
