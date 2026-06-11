"""Tunnel benchmark helpers (sink + probe).

Used by the panel's "test between nodes" feature:
  - The FOREIGN node runs a *sink* (echo/count server) bound to 127.0.0.1 on
    the test port. It is the local target service the test tunnel forwards to.
  - The IRAN node runs a *probe* against 127.0.0.1:<test_port> (the tunnel's
    public entry on the iran node), so the measured path is exactly the
    iran -> foreign tunnel leg.

Wire protocols (intentionally tiny):
  TCP sink: first byte of a connection selects the mode -
    b"L": echo every received chunk back (latency pings)
    b"T": read and discard until client half-closes, then reply with the
          total byte count as 8-byte big-endian and close (throughput)
  UDP sink: datagram prefix selects behaviour -
    b"P": echoed back verbatim (latency / loss pings)
    b"D": counted but not echoed (throughput payload)
    b"S": reply with the current counted byte total as 8-byte big-endian
"""
import logging
import socket
import struct
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SINK_DEFAULT_DURATION = 120  # auto-stop safety
PROBE_CONNECT_TIMEOUT = 5.0
PROBE_IO_TIMEOUT = 5.0


class BenchmarkSinkManager:
    """Manages short-lived echo/count sink servers used as tunnel targets."""

    def __init__(self):
        self.sinks: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Lock()

    def start_sink(self, sink_id: str, port: int, protocol: str, duration_sec: int = SINK_DEFAULT_DURATION):
        protocol = (protocol or "tcp").lower()
        if protocol not in ("tcp", "udp"):
            raise ValueError(f"Unsupported sink protocol: {protocol}")

        self.stop_sink(sink_id)

        stop_event = threading.Event()
        if protocol == "tcp":
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind(("127.0.0.1", port))
            server_socket.listen(8)
            server_socket.settimeout(0.5)
            thread = threading.Thread(
                target=self._tcp_sink_loop, args=(sink_id, server_socket, stop_event), daemon=True
            )
        else:
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind(("127.0.0.1", port))
            server_socket.settimeout(0.5)
            thread = threading.Thread(
                target=self._udp_sink_loop, args=(sink_id, server_socket, stop_event), daemon=True
            )

        with self.lock:
            self.sinks[sink_id] = {
                "socket": server_socket,
                "stop_event": stop_event,
                "thread": thread,
                "protocol": protocol,
                "port": port,
            }
        thread.start()

        # Safety timer: never leave a sink running forever.
        timer = threading.Timer(max(duration_sec, 5), self.stop_sink, args=(sink_id,))
        timer.daemon = True
        timer.start()
        logger.info(f"Benchmark sink {sink_id} started on 127.0.0.1:{port}/{protocol}")

    def stop_sink(self, sink_id: str):
        with self.lock:
            sink = self.sinks.pop(sink_id, None)
        if not sink:
            return
        sink["stop_event"].set()
        try:
            sink["socket"].close()
        except Exception:
            pass
        logger.info(f"Benchmark sink {sink_id} stopped")

    def stop_all(self):
        for sink_id in list(self.sinks.keys()):
            self.stop_sink(sink_id)

    def _tcp_sink_loop(self, sink_id: str, server_socket: socket.socket, stop_event: threading.Event):
        while not stop_event.is_set():
            try:
                conn, _ = server_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            handler = threading.Thread(
                target=self._tcp_handle_conn, args=(conn, stop_event), daemon=True
            )
            handler.start()
        try:
            server_socket.close()
        except Exception:
            pass

    def _tcp_handle_conn(self, conn: socket.socket, stop_event: threading.Event):
        try:
            conn.settimeout(PROBE_IO_TIMEOUT * 2)
            mode = conn.recv(1)
            if not mode:
                return
            if mode == b"L":
                while not stop_event.is_set():
                    data = conn.recv(4096)
                    if not data:
                        break
                    conn.sendall(data)
            elif mode == b"T":
                total = 0
                while not stop_event.is_set():
                    data = conn.recv(65536)
                    if not data:
                        break
                    total += len(data)
                conn.sendall(struct.pack(">Q", total))
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _udp_sink_loop(self, sink_id: str, server_socket: socket.socket, stop_event: threading.Event):
        counted_bytes = 0
        while not stop_event.is_set():
            try:
                data, addr = server_socket.recvfrom(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                continue
            try:
                prefix = data[:1]
                if prefix == b"P":
                    server_socket.sendto(data, addr)
                elif prefix == b"D":
                    counted_bytes += len(data)
                elif prefix == b"S":
                    server_socket.sendto(struct.pack(">Q", counted_bytes), addr)
            except Exception:
                pass
        try:
            server_socket.close()
        except Exception:
            pass


sink_manager = BenchmarkSinkManager()


def _recv_exact(conn: socket.socket, count: int) -> Optional[bytes]:
    buf = b""
    while len(buf) < count:
        chunk = conn.recv(count - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def _tcp_probe(host: str, port: int, ping_count: int, throughput_seconds: float) -> Dict[str, Any]:
    rtts = []
    # Phase 1: latency over a single echo connection
    conn = socket.create_connection((host, port), timeout=PROBE_CONNECT_TIMEOUT)
    try:
        conn.settimeout(PROBE_IO_TIMEOUT)
        conn.sendall(b"L")
        payload = b"x" * 16
        for _ in range(ping_count):
            start = time.perf_counter()
            conn.sendall(payload)
            echoed = _recv_exact(conn, len(payload))
            if echoed is None:
                raise ConnectionError("Echo connection closed during latency test")
            rtts.append((time.perf_counter() - start) * 1000.0)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # Phase 2: throughput (send-only, sink replies with received byte count)
    conn = socket.create_connection((host, port), timeout=PROBE_CONNECT_TIMEOUT)
    throughput_mbps = 0.0
    try:
        conn.settimeout(PROBE_IO_TIMEOUT * 2)
        conn.sendall(b"T")
        chunk = b"\x00" * 65536
        sent = 0
        start = time.perf_counter()
        while time.perf_counter() - start < throughput_seconds:
            conn.sendall(chunk)
            sent += len(chunk)
        conn.shutdown(socket.SHUT_WR)
        reply = _recv_exact(conn, 8)
        elapsed = time.perf_counter() - start
        received = struct.unpack(">Q", reply)[0] if reply else 0
        if elapsed > 0 and received > 0:
            throughput_mbps = (received * 8) / elapsed / 1_000_000
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return {
        "ok": True,
        "protocol": "tcp",
        "latency_ms": round(sum(rtts) / len(rtts), 2) if rtts else None,
        "latency_min_ms": round(min(rtts), 2) if rtts else None,
        "latency_max_ms": round(max(rtts), 2) if rtts else None,
        "throughput_mbps": round(throughput_mbps, 2),
        "loss_percent": 0.0,
        "error": None,
    }


def _udp_probe(host: str, port: int, ping_count: int, throughput_seconds: float) -> Dict[str, Any]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(1.0)
    try:
        # Phase 1: latency + loss with echoed "P" datagrams
        rtts = []
        received = 0
        for seq in range(ping_count):
            payload = b"P" + struct.pack(">I", seq) + b"x" * 16
            start = time.perf_counter()
            sock.sendto(payload, (host, port))
            try:
                data, _ = sock.recvfrom(2048)
                if data[:5] == payload[:5]:
                    rtts.append((time.perf_counter() - start) * 1000.0)
                    received += 1
            except socket.timeout:
                pass
            time.sleep(0.02)
        loss_percent = round((1 - received / ping_count) * 100.0, 1) if ping_count else 0.0

        if received == 0:
            return {
                "ok": False,
                "protocol": "udp",
                "latency_ms": None,
                "latency_min_ms": None,
                "latency_max_ms": None,
                "throughput_mbps": 0.0,
                "loss_percent": 100.0,
                "error": "No UDP echo replies received (tunnel not passing UDP traffic)",
            }

        # Phase 2: throughput with counted-but-not-echoed "D" datagrams,
        # sent in paced bursts so the sender does not just fill local buffers.
        chunk = b"D" + b"\x00" * 1199
        start = time.perf_counter()
        while time.perf_counter() - start < throughput_seconds:
            for _ in range(64):
                sock.sendto(chunk, (host, port))
            time.sleep(0.001)
        elapsed = time.perf_counter() - start

        # Drain pending echoes, then ask the sink how much it actually received
        time.sleep(0.3)
        counted = 0
        for _ in range(5):
            try:
                sock.sendto(b"S", (host, port))
                data, _ = sock.recvfrom(64)
                if len(data) >= 8:
                    counted = struct.unpack(">Q", data[:8])[0]
                    break
            except socket.timeout:
                continue
        throughput_mbps = (counted * 8) / elapsed / 1_000_000 if elapsed > 0 else 0.0

        return {
            "ok": True,
            "protocol": "udp",
            "latency_ms": round(sum(rtts) / len(rtts), 2) if rtts else None,
            "latency_min_ms": round(min(rtts), 2) if rtts else None,
            "latency_max_ms": round(max(rtts), 2) if rtts else None,
            "throughput_mbps": round(throughput_mbps, 2),
            "loss_percent": loss_percent,
            "error": None,
        }
    finally:
        try:
            sock.close()
        except Exception:
            pass


def run_probe(
    host: str,
    port: int,
    protocol: str = "tcp",
    ping_count: int = 10,
    throughput_seconds: float = 3.0,
) -> Dict[str, Any]:
    """Measure latency / throughput / loss against host:port over the tunnel."""
    protocol = (protocol or "tcp").lower()
    try:
        if protocol == "udp":
            return _udp_probe(host, port, ping_count, throughput_seconds)
        return _tcp_probe(host, port, ping_count, throughput_seconds)
    except Exception as e:
        logger.warning(f"Benchmark probe failed for {host}:{port}/{protocol}: {e}")
        return {
            "ok": False,
            "protocol": protocol,
            "latency_ms": None,
            "latency_min_ms": None,
            "latency_max_ms": None,
            "throughput_mbps": 0.0,
            "loss_percent": 100.0,
            "error": str(e),
        }
