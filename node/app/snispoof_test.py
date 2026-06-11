"""SNI-spoof self-test + auto-tune.

Goal: make the snispoof core "just work" without the user hand-tuning zapret.

The node runs the snispoof front proxy (a local VLESS/TCP inbound -> WS+TLS
fronting outbound), with a zapret nfqws desync on the outbound :443. Whether the
desync survives the local DPI depends on the desync mode / fooling combination,
which is hard to guess. This module measures it directly:

  1. Start a throwaway xray "tester client": an HTTP-proxy inbound that forwards
     to the live front proxy exactly like the user's Sanaei panel would
     (VLESS/TCP to 127.0.0.1:<local_port> with the inbound UUID).
  2. For each candidate desync combo, re-apply the tunnel's composed zapret and
     probe a real HTTPS URL through the proxy chain, recording success + latency.
  3. Rank the combos, leave the tunnel on the best working one, and report the
     ranked list plus the exact client outbound to paste into Sanaei.

Everything runs on the iran node next to the live tunnel; the panel only
orchestrates and persists the chosen combo.
"""
import logging
import socket
import subprocess
import time
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_URL = "https://www.gstatic.com/generate_204"
TESTER_DIR = Path("/tmp/smite-snispoof-test")
PROBE_TIMEOUT = 8.0
SETTLE_SECONDS = 1.3

# Curated desync combos to try, ordered roughly by how often they work for
# TLS-SNI DPI. "off" = front proxy only (tells us if a desync is needed at all).
DEFAULT_COMBOS: List[Dict[str, str]] = [
    {"desync_mode": "off"},
    {"desync_mode": "fake", "desync_fooling": "badseq,ts"},
    {"desync_mode": "fake", "desync_fooling": "badseq"},
    {"desync_mode": "fake", "desync_fooling": "datanoack"},
    {"desync_mode": "fake", "desync_fooling": "md5sig"},
    {"desync_mode": "fakedsplit", "desync_fooling": "badseq,ts"},
    {"desync_mode": "fakeddisorder", "desync_fooling": "badseq,ts"},
    {"desync_mode": "multisplit", "desync_fooling": "badseq,ts"},
    {"desync_mode": "multidisorder", "desync_fooling": "badseq,ts"},
    {"desync_mode": "syndata", "desync_fooling": "badseq,ts"},
    {"desync_mode": "disorder2", "desync_fooling": "badseq,ts"},
    {"desync_mode": "split2", "desync_fooling": "badseq,ts"},
]


def build_client_outbound(spec: Dict[str, Any]) -> Dict[str, Any]:
    """The exact VLESS outbound a client panel (e.g. Sanaei) must use to reach
    the local front-proxy inbound. This is plain VLESS over TCP, security none -
    NOT the backend's WS/TLS settings."""
    try:
        local_port = int(spec.get("local_port") or 0)
    except (TypeError, ValueError):
        local_port = 0
    inbound_uuid = (spec.get("inbound_uuid") or "").strip()
    address = "127.0.0.1"
    link = (
        f"vless://{inbound_uuid}@{address}:{local_port}"
        f"?encryption=none&security=none&type=tcp#snispoof-local"
    )
    return {
        "protocol": "vless",
        "address": address,
        "port": local_port,
        "uuid": inbound_uuid,
        "encryption": "none",
        "security": "none",
        "network": "tcp",
        "vless_link": link,
    }


def _free_loopback_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def _build_tester_config(spec: Dict[str, Any], http_port: int) -> Dict[str, Any]:
    """An xray client whose HTTP-proxy inbound forwards to the live front proxy,
    exactly like the user's client panel would."""
    listen_addr = (spec.get("listen_addr") or "127.0.0.1").strip()
    local_port = int(spec.get("local_port") or 0)
    inbound_uuid = (spec.get("inbound_uuid") or "").strip()
    if not local_port or not inbound_uuid:
        raise ValueError("snispoof test: local_port and inbound_uuid are required")
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": "http-in",
                "listen": "127.0.0.1",
                "port": http_port,
                "protocol": "http",
                "settings": {},
            }
        ],
        "outbounds": [
            {
                "tag": "to-local",
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": listen_addr,
                            "port": local_port,
                            "users": [{"id": inbound_uuid, "encryption": "none"}],
                        }
                    ]
                },
                "streamSettings": {"network": "tcp", "security": "none"},
            }
        ],
    }


def _resolve_xray(adapter_manager) -> Path:
    snispoof = adapter_manager.adapters.get("snispoof")
    if snispoof is not None:
        return snispoof._resolve_binary_path()
    raise FileNotFoundError("snispoof adapter not available")


class _Tester:
    """Throwaway xray HTTP proxy -> front proxy, used to probe the chain."""

    def __init__(self, adapter_manager, tunnel_id: str, spec: Dict[str, Any]):
        self.adapter_manager = adapter_manager
        self.tunnel_id = tunnel_id
        self.spec = spec
        self.http_port = _free_loopback_port()
        self.proc: Optional[subprocess.Popen] = None
        self.dir = TESTER_DIR / tunnel_id
        self.dir.mkdir(parents=True, exist_ok=True)

    def start(self):
        import json

        config = _build_tester_config(self.spec, self.http_port)
        config_file = self.dir / "client.json"
        with open(config_file, "w") as f:
            json.dump(config, f, indent=2)
        binary = _resolve_xray(self.adapter_manager)
        log_file = self.dir / "client.log"
        self._log = open(log_file, "w", buffering=1)
        self.proc = subprocess.Popen(
            [str(binary), "run", "-c", str(config_file)],
            stdout=self._log,
            stderr=subprocess.STDOUT,
            cwd=str(self.dir),
            start_new_session=True,
        )
        time.sleep(1.2)
        if self.proc.poll() is not None:
            err = log_file.read_text()[-400:] if log_file.exists() else ""
            raise RuntimeError(f"tester xray failed to start: {err}")

    def stop(self):
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            except Exception:
                pass
            self.proc = None
        try:
            self._log.close()
        except Exception:
            pass

    def probe(self, url: str) -> Dict[str, Any]:
        proxy = f"http://127.0.0.1:{self.http_port}"
        t0 = time.perf_counter()
        try:
            try:
                client = httpx.Client(proxy=proxy, timeout=PROBE_TIMEOUT, follow_redirects=False)
            except TypeError:
                client = httpx.Client(proxies=proxy, timeout=PROBE_TIMEOUT, follow_redirects=False)
            try:
                resp = client.get(url)
            finally:
                client.close()
            latency = round((time.perf_counter() - t0) * 1000.0, 1)
            ok = resp.status_code in (200, 204)
            return {"ok": ok, "status": resp.status_code, "latency_ms": latency,
                    "error": None if ok else f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"ok": False, "status": None, "latency_ms": None,
                    "error": f"{type(e).__name__}: {e}"}


def _ensure_front_proxy(adapter_manager, tunnel_id: str, spec: Dict[str, Any]):
    """Make sure the snispoof front proxy (xray) is running before we probe."""
    snispoof = adapter_manager.adapters.get("snispoof")
    if snispoof is None:
        raise RuntimeError("snispoof adapter not registered on this node")
    proc = snispoof.processes.get(tunnel_id)
    if not proc or proc.poll() is not None:
        snispoof.apply(tunnel_id, spec)
    return snispoof


def test_current(adapter_manager, tunnel_id: str, spec: Dict[str, Any],
                 url: str = DEFAULT_URL, attempts: int = 2) -> Dict[str, Any]:
    """Probe the tunnel as-is and return a single pass/fail + the client outbound."""
    _ensure_front_proxy(adapter_manager, tunnel_id, spec)
    tester = _Tester(adapter_manager, tunnel_id, spec)
    results: List[Dict[str, Any]] = []
    try:
        tester.start()
        for _ in range(max(1, attempts)):
            results.append(tester.probe(url))
    finally:
        tester.stop()
    oks = [r for r in results if r["ok"]]
    latency = round(median([r["latency_ms"] for r in oks]), 1) if oks else None
    return {
        "ok": bool(oks),
        "latency_ms": latency,
        "attempts": len(results),
        "success": len(oks),
        "url": url,
        "error": None if oks else (results[-1]["error"] if results else "no probe"),
        "client_outbound": build_client_outbound(spec),
    }


def autotune(adapter_manager, tunnel_id: str, spec: Dict[str, Any],
             combos: Optional[List[Dict[str, str]]] = None,
             url: str = DEFAULT_URL, probes: int = 2) -> Dict[str, Any]:
    """Try each desync combo on the live tunnel, rank them, and leave the tunnel
    on the best working combo. Returns the ranked results + recommended combo +
    the exact client outbound."""
    combos = combos or DEFAULT_COMBOS
    url = url or DEFAULT_URL
    snispoof = _ensure_front_proxy(adapter_manager, tunnel_id, spec)
    zap = snispoof.zapret
    base_sub = snispoof._build_zapret_spec(spec)  # filter_tcp/l7, target_ip, max_pkt, queue
    default_sni = (spec.get("fake_tls_sni") or "hcaptcha.com")

    def sub_for(combo: Dict[str, str]) -> Optional[Dict[str, Any]]:
        if combo.get("desync_mode") == "off":
            return None
        sub = dict(base_sub)
        sub["desync_mode"] = combo["desync_mode"]
        sub["desync_fooling"] = combo.get("desync_fooling", "badseq,ts")
        sub["fake_tls_sni"] = combo.get("fake_tls_sni") or default_sni
        return sub

    tester = _Tester(adapter_manager, tunnel_id, spec)
    results: List[Dict[str, Any]] = []
    ranked: List[Dict[str, Any]] = []
    best: Optional[Dict[str, Any]] = None
    off_ok = False
    try:
        tester.start()
        for combo in combos:
            sub = sub_for(combo)
            try:
                zap.remove(tunnel_id)
                time.sleep(0.3)
                if sub is not None:
                    zap.apply(tunnel_id, sub)
                time.sleep(SETTLE_SECONDS)
            except Exception as e:
                results.append({
                    "desync_mode": combo.get("desync_mode"),
                    "desync_fooling": combo.get("desync_fooling", ""),
                    "fake_tls_sni": (combo.get("fake_tls_sni") or default_sni) if sub else "",
                    "ok": False, "success": 0, "attempts": 0,
                    "latency_ms": None, "error": f"apply failed: {e}",
                })
                continue
            probe_results = [tester.probe(url) for _ in range(max(1, probes))]
            oks = [r for r in probe_results if r["ok"]]
            latency = round(median([r["latency_ms"] for r in oks]), 1) if oks else None
            results.append({
                "desync_mode": combo.get("desync_mode"),
                "desync_fooling": combo.get("desync_fooling", "") if sub else "",
                "fake_tls_sni": (combo.get("fake_tls_sni") or default_sni) if sub else "",
                "ok": bool(oks),
                "success": len(oks),
                "attempts": len(probe_results),
                "latency_ms": latency,
                "error": None if oks else (probe_results[-1]["error"] if probe_results else "no probe"),
            })

        ranked = sorted(
            results,
            key=lambda r: (
                -(r["success"] / r["attempts"] if r.get("attempts") else 0),
                r["latency_ms"] if r["latency_ms"] is not None else 1e9,
            ),
        )
        # The recommended combo is the best working *real* desync (not "off"),
        # so we always have a valid mode to persist + re-apply.
        best = next((r for r in ranked if r["ok"] and r["desync_mode"] != "off"), None)
        off_ok = any(r["ok"] and r["desync_mode"] == "off" for r in results)
    finally:
        # Leave the tunnel consistent with what we report: the chosen combo if we
        # found one, else exactly the original spec's desync (do no harm).
        try:
            zap.remove(tunnel_id)
            time.sleep(0.2)
            if best is not None:
                restore = dict(base_sub)
                restore["desync_mode"] = best["desync_mode"]
                restore["desync_fooling"] = best["desync_fooling"]
                restore["fake_tls_sni"] = best["fake_tls_sni"] or default_sni
                zap.apply(tunnel_id, restore)
            else:
                zap.apply(tunnel_id, base_sub)
        except Exception as e:
            logger.warning(f"snispoof autotune restore failed for {tunnel_id}: {e}")
        tester.stop()

    recommended = None
    if best:
        recommended = {
            "desync_mode": best["desync_mode"],
            "desync_fooling": best["desync_fooling"],
            "fake_tls_sni": best["fake_tls_sni"],
            "latency_ms": best["latency_ms"],
        }
    return {
        "ok": best is not None,
        "best": recommended,
        "off_ok": off_ok,
        "results": ranked,
        "url": url,
        "client_outbound": build_client_outbound(spec),
    }
