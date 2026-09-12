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
import os
import socket
import struct
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SINK_DEFAULT_DURATION = 120  # auto-stop safety
PROBE_CONNECT_TIMEOUT = 5.0
PROBE_IO_TIMEOUT = 5.0

# WireGuard message headers (type byte + 3 reserved zero bytes).
WG_INITIATION = b"\x01\x00\x00\x00"
WG_RESPONSE = b"\x02\x00\x00\x00"
WG_TRANSPORT = b"\x04\x00\x00\x00"
# Separate flows the WireGuard-shaped probe opens. Each is a new relay session
# and therefore a new flow for the DPI, so a strategy that only gets through
# some of the time (ipfrag2 did) shows up as unstable instead of passing.
WG_PROBE_FLOWS = 3


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
            server_socket.bind(("0.0.0.0", port))
            server_socket.listen(8)
            server_socket.settimeout(0.5)
            thread = threading.Thread(
                target=self._tcp_sink_loop, args=(sink_id, server_socket, stop_event), daemon=True
            )
        else:
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind(("0.0.0.0", port))
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
        # WireGuard-shaped sessions, keyed by client address: (their index, our index, our counter)
        wg_sessions: Dict[Any, list] = {}
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
                elif data[:4] == WG_INITIATION and len(data) == 148:
                    # Answer like a WireGuard responder: a 92-byte type-2 message
                    # addressed to the initiator's sender index, mac2 zeroed.
                    ours = os.urandom(4)
                    wg_sessions[addr] = [data[4:8], ours, 0]
                    server_socket.sendto(WG_RESPONSE + ours + data[4:8] + os.urandom(64) + b"\x00" * 16, addr)
                elif data[:4] == WG_TRANSPORT and len(data) >= 32:
                    session = wg_sessions.get(addr)
                    if session is None:
                        continue  # a real responder drops data for an unknown index too
                    cmd = data[16:17]
                    if cmd == b"D":
                        counted_bytes += len(data)
                    elif cmd in (b"P", b"S"):
                        body = data[16:] if cmd == b"P" else struct.pack(">Q", counted_bytes) + os.urandom(24)
                        header = WG_TRANSPORT + session[0] + struct.pack("<Q", session[2])
                        session[2] += 1
                        server_socket.sendto(header + body, addr)
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
        # sent in paced bursts so the sender does not saturate kernel queues.
        chunk = b"D" + b"\x00" * 1199
        start = time.perf_counter()
        while time.perf_counter() - start < throughput_seconds:
            for _ in range(16):
                sock.sendto(chunk, (host, port))
            time.sleep(0.002)
        elapsed = time.perf_counter() - start

        # Drain pending queue, then ask the sink how much it actually received
        time.sleep(0.4)
        counted = 0
        sock.settimeout(2.0)
        for _ in range(6):
            try:
                sock.sendto(b"S", (host, port))
                data, _ = sock.recvfrom(64)
                if len(data) >= 8:
                    counted = struct.unpack(">Q", data[:8])[0]
                    if counted > 0:
                        break
            except socket.timeout:
                time.sleep(0.15)
                continue
            except Exception:
                break
        # No fallback estimate here: when the sink's byte count never came back
        # this used to report max(50, bytes sent) Mbps, i.e. a made-up number
        # that could rank a tunnel carrying nothing near the top.
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


def _wg_data(receiver: bytes, counter: int, plain: bytes) -> bytes:
    """A WireGuard transport message: header, payload padded to 16 bytes, 16-byte tag."""
    pad = (-len(plain)) % 16
    return WG_TRANSPORT + receiver + struct.pack("<Q", counter) + plain + os.urandom(pad) + os.urandom(16)


def _wg_handshake(sock: socket.socket, host: str, port: int, attempts: int = 3,
                  timeout: float = 1.2) -> Optional[bytes]:
    """Send WireGuard-shaped handshake initiations; return the responder's index or None.

    The initiation has the real layout: type 1, sender index, ephemeral key,
    encrypted static and timestamp, mac1, and mac2 left as zeros the way a
    client sends it when no cookie is involved. That last detail matters: on
    the measured path a plain 148-byte type-1 packet with random mac2 went
    through, while one with a zeroed mac2 was dropped exactly like real
    WireGuard.
    """
    for _ in range(attempts):
        ours = os.urandom(4)
        sock.sendto(WG_INITIATION + ours + os.urandom(32 + 48 + 28 + 16) + b"\x00" * 16, (host, port))
        deadline = time.perf_counter() + timeout
        while True:
            left = deadline - time.perf_counter()
            if left <= 0:
                break
            sock.settimeout(left)
            try:
                data, _ = sock.recvfrom(2048)
            except socket.timeout:
                break
            if len(data) == 92 and data[:4] == WG_RESPONSE and data[8:12] == ours:
                return data[4:8]
    return None


def _wg_ping(sock: socket.socket, host: str, port: int, receiver: bytes, counter: int,
             seq: int, timeout: float = 1.0) -> Optional[float]:
    """One echoed transport message; RTT in ms, or None when it did not come back."""
    tag = b"P" + struct.pack(">I", seq)
    sock.sendto(_wg_data(receiver, counter, tag + os.urandom(59)), (host, port))
    deadline = time.perf_counter() + timeout
    start = time.perf_counter()
    while True:
        left = deadline - time.perf_counter()
        if left <= 0:
            return None
        sock.settimeout(left)
        try:
            data, _ = sock.recvfrom(2048)
        except socket.timeout:
            return None
        if data[:4] == WG_TRANSPORT and data[16:21] == tag:
            return (time.perf_counter() - start) * 1000.0


def _udp_plain_reachable(host: str, port: int, tries: int = 3) -> bool:
    """Does any plain (non-WireGuard) UDP get through? Used only to explain a failure."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(1.0)
    try:
        for i in range(tries):
            payload = b"P" + struct.pack(">I", 900000 + i) + b"x" * 16
            sock.sendto(payload, (host, port))
            try:
                data, _ = sock.recvfrom(2048)
                if data[:5] == payload[:5]:
                    return True
            except socket.timeout:
                pass
        return False
    finally:
        sock.close()


def _udp_probe_wireguard(host: str, port: int, ping_count: int, throughput_seconds: float) -> Dict[str, Any]:
    """UDP probe that looks like WireGuard on the wire.

    The plain probe sends "P"/"D" datagrams a DPI has no reason to touch, so a
    tunnel that relays raw WireGuard (zapret, multi-port hopping) passed the
    benchmark while real WireGuard clients were dropped. Here every datagram
    has WireGuard's layout: a handshake exchange first, then transport
    messages with indices and counters, so the tunnel is judged on the
    traffic it will actually carry. Cores that encapsulate their payload are
    unaffected: the DPI never sees the inner packets either way.
    """
    socks = []
    flows_ok = 0
    primary = None  # (socket, receiver index, next counter)
    try:
        for _ in range(WG_PROBE_FLOWS):
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            socks.append(sock)
            receiver = _wg_handshake(sock, host, port)
            if receiver is None:
                continue
            counter = 0
            replies = 0
            for seq in range(3):
                if _wg_ping(sock, host, port, receiver, counter, seq) is not None:
                    replies += 1
                counter += 1
            if replies:
                flows_ok += 1
                if primary is None:
                    primary = [sock, receiver, counter]

        base = {
            "protocol": "udp",
            "probe_style": "wireguard",
            "wg_flows_ok": flows_ok,
            "wg_flows_total": WG_PROBE_FLOWS,
            "plain_udp_ok": None,
        }
        if primary is None:
            plain_ok = _udp_plain_reachable(host, port)
            base["plain_udp_ok"] = plain_ok
            if plain_ok:
                code = "wg_filtered"
                msg = ("Plain UDP passes this tunnel but WireGuard traffic is dropped "
                       "(filtered by DPI). WireGuard clients will not connect through it.")
            else:
                code = "no_udp"
                msg = "No UDP traffic passes the tunnel."
            return {**base, "ok": False, "error_code": code, "error": msg,
                    "latency_ms": None, "latency_min_ms": None, "latency_max_ms": None,
                    "throughput_mbps": 0.0, "loss_percent": 100.0}

        sock, receiver, counter = primary
        rtts = []
        for seq in range(ping_count):
            rtt = _wg_ping(sock, host, port, receiver, counter, 1000 + seq)
            counter += 1
            if rtt is not None:
                rtts.append(rtt)
            time.sleep(0.02)
        loss_percent = round((1 - len(rtts) / ping_count) * 100.0, 1) if ping_count else 0.0

        # Throughput: counted-but-not-echoed 1200-byte transport messages.
        fillers = [b"D" + os.urandom(1167) for _ in range(32)]  # 16 + 1168 + 16 = 1200 bytes
        start = time.perf_counter()
        n = 0
        while time.perf_counter() - start < throughput_seconds:
            for _ in range(16):
                sock.sendto(WG_TRANSPORT + receiver + struct.pack("<Q", counter) + fillers[n % 32] + os.urandom(16),
                            (host, port))
                counter += 1
                n += 1
            time.sleep(0.002)
        elapsed = time.perf_counter() - start
        time.sleep(0.4)
        counted = 0
        for _ in range(6):
            sock.sendto(_wg_data(receiver, counter, b"S"), (host, port))
            counter += 1
            sock.settimeout(2.0)
            try:
                data, _ = sock.recvfrom(2048)
            except socket.timeout:
                continue
            if data[:4] == WG_TRANSPORT and len(data) >= 24:
                counted = struct.unpack(">Q", data[16:24])[0]
                if counted > 0:
                    break
        throughput_mbps = (counted * 8) / elapsed / 1_000_000 if elapsed > 0 else 0.0

        ok = flows_ok == WG_PROBE_FLOWS and bool(rtts)
        result = {
            **base,
            "ok": ok,
            "latency_ms": round(sum(rtts) / len(rtts), 2) if rtts else None,
            "latency_min_ms": round(min(rtts), 2) if rtts else None,
            "latency_max_ms": round(max(rtts), 2) if rtts else None,
            "throughput_mbps": round(throughput_mbps, 2),
            "loss_percent": loss_percent,
            "error": None,
            "error_code": None,
        }
        if not ok:
            result["error_code"] = "wg_unstable"
            result["error"] = (f"WireGuard got through on only {flows_ok} of {WG_PROBE_FLOWS} "
                               f"separate connections; this setup is unreliable.")
        return result
    finally:
        for sock in socks:
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
    style: str = "plain",
) -> Dict[str, Any]:
    """Measure latency / throughput / loss against host:port over the tunnel.

    style="wireguard" makes a UDP probe look like WireGuard on the wire; the
    sink on the far end must be new enough to answer it (see sink start's
    "wg_probe" flag).
    """
    protocol = (protocol or "tcp").lower()
    try:
        if protocol == "udp":
            if (style or "").lower() in ("wireguard", "wg"):
                return _udp_probe_wireguard(host, port, ping_count, throughput_seconds)
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
