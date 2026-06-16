"""Client for panel to communicate with nodes"""
import httpx
import os
import ssl
import logging
import asyncio
from typing import Dict, Any, Optional, Tuple


def _node_auth_headers() -> Dict[str, str]:
    """Send the shared node token when configured (no-op until NODE_API_TOKEN is set)."""
    token = os.environ.get("NODE_API_TOKEN", "")
    return {"X-Node-Token": token} if token else {}


def _verify_tls():
    """TLS verification for panel->node calls. Default OFF (self-signed/FRP loopback);
    enable with NODE_TLS_VERIFY=1 once nodes present a trusted certificate (H10)."""
    return os.environ.get("NODE_TLS_VERIFY", "").strip().lower() in ("1", "true", "yes", "on")
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import Node, Settings

logger = logging.getLogger(__name__)


class NodeClient:
    """Client to send requests to nodes via HTTP/HTTPS or FRP"""
    
    def __init__(self):
        self.timeout = httpx.Timeout(30.0)
    
    async def _get_frp_settings(self) -> Optional[Dict[str, Any]]:
        """Get FRP communication settings"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Settings).where(Settings.key == "frp"))
            setting = result.scalar_one_or_none()
            if setting and setting.value and setting.value.get("enabled"):
                return setting.value
        return None
    
    async def _get_node_address(self, node: Node) -> Tuple[str, bool]:
        """
        Get node address (direct or via FRP)
        Returns: (address, using_frp)
        """
        frp_settings = await self._get_frp_settings()
        
        if frp_settings and frp_settings.get("enabled"):
            frp_remote_port = node.node_metadata.get("frp_remote_port") if node.node_metadata else None
            if frp_remote_port:
                # Verify FRP server is running before using FRP
                from app.frp_comm_manager import frp_comm_manager
                if not frp_comm_manager.is_running():
                    logger.warning(f"[HTTP] FRP enabled but FRP server not running, falling back to HTTP for node {node.id}")
                    # Fall through to HTTP
                else:
                    # Use FRP - the server is running, tunnel should be available
                    # Note: If connection fails, retry logic will handle it
                    logger.info(f"[FRP] Using FRP tunnel to communicate with node {node.id} (remote_port={frp_remote_port})")
                    return (f"http://127.0.0.1:{frp_remote_port}", True)
            else:
                # FRP is enabled but node hasn't reported its remote port yet (during initial setup)
                logger.warning(f"[HTTP] FRP enabled but node {node.id} has no frp_remote_port yet, temporarily using HTTP")
                logger.warning(f"[HTTP] This should only happen during node registration. After FRP setup, all communication will use FRP.")
        
        # FRP is not enabled or not available - use HTTP
        node_address = node.node_metadata.get("api_address", f"http://localhost:8888") if node.node_metadata else f"http://localhost:8888"
        if not node_address.startswith("http"):
            node_address = f"http://{node_address}"
        logger.info(f"[HTTP] Using direct HTTP to communicate with node {node.id} at {node_address}")
        return (node_address, False)
    
    async def send_to_node(self, node_id: str, endpoint: str, data: Dict[str, Any],
                           timeout: Optional[float] = None) -> Dict[str, Any]:
        """
        Send request to node via HTTPS or FRP

        `timeout` (seconds) overrides the default 30s for long-running calls
        such as the snispoof auto-tune (which probes many desync combos).
        """
        req_timeout = httpx.Timeout(timeout) if timeout else self.timeout
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Node).where(Node.id == node_id))
            node = result.scalar_one_or_none()
            
            if not node:
                return {"status": "error", "message": f"Node {node_id} not found"}
            
            node_address, using_frp = await self._get_node_address(node)
            url = f"{node_address.rstrip('/')}{endpoint}"
            
            comm_type = "FRP" if using_frp else "HTTP"
            logger.debug(f"[{comm_type}] Sending request to node {node_id}: {endpoint}")
            
            try:
                # Retry logic for FRP connections which may need a moment to stabilize
                max_retries = 5 if using_frp else 1
                last_error = None
                
                for attempt in range(max_retries):
                    try:
                        # For FRP, use a new connection each time to avoid connection reuse issues
                        if using_frp and attempt > 0:
                            await asyncio.sleep(2.0)  # Longer delay for FRP retries
                            logger.info(f"[FRP] Retry {attempt + 1}/{max_retries} for node {node_id} via FRP tunnel")
                        
                        async with httpx.AsyncClient(
                            timeout=req_timeout, 
                            verify=_verify_tls(),
                            limits=httpx.Limits(max_keepalive_connections=0 if using_frp else 5)  # Disable keep-alive for FRP
                        ) as client:
                            response = await client.post(url, json=data, headers=_node_auth_headers())
                            response.raise_for_status()
                            return response.json()
                    except httpx.RequestError as e:
                        last_error = e
                        if attempt < max_retries - 1:
                            if not using_frp:
                                await asyncio.sleep(0.5)
                            continue
                        else:
                            error_msg = f"Network error: {str(e)}"
                            if using_frp:
                                remote_port = url.split(":")[-1].split("/")[0] if ":" in url else "unknown"
                                error_msg += f" (FRP tunnel connection failed after {max_retries} attempts. The panel may not be able to reach FRP server on 127.0.0.1:{remote_port}. Check if panel and FRP server are in the same network namespace, or check FRP server logs.)"
                            return {"status": "error", "message": error_msg}
                
                # Should not reach here, but just in case
                return {"status": "error", "message": f"Network error: {str(last_error)}"}
            except httpx.HTTPStatusError as e:
                try:
                    error_detail = e.response.json().get("detail", str(e))
                except:
                    error_detail = str(e)
                return {"status": "error", "message": f"Node error (HTTP {e.response.status_code}): {error_detail}"}
            except Exception as e:
                return {"status": "error", "message": f"Error: {str(e)}"}
    
    async def get_tunnel_status(self, node_id: str, tunnel_id: str = "") -> Dict[str, Any]:
        """Get tunnel status from node"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Node).where(Node.id == node_id))
            node = result.scalar_one_or_none()
            
            if not node:
                return {"status": "error", "message": f"Node {node_id} not found"}
            
            node_address, using_frp = await self._get_node_address(node)
            url = f"{node_address.rstrip('/')}/api/agent/status"
            
            comm_type = "FRP" if using_frp else "HTTP"
            logger.debug(f"[{comm_type}] Getting tunnel status from node {node_id}")
            
            try:
                timeout = httpx.Timeout(3.0, connect=2.0)
                async with httpx.AsyncClient(timeout=timeout, verify=_verify_tls()) as client:
                    response = await client.get(url, headers=_node_auth_headers())
                    response.raise_for_status()
                    return response.json()
            except httpx.RequestError as e:
                return {"status": "error", "message": f"Network error: {str(e)}"}
            except httpx.HTTPStatusError as e:
                try:
                    error_detail = e.response.json().get("detail", str(e))
                except:
                    error_detail = str(e)
                return {"status": "error", "message": f"Node error (HTTP {e.response.status_code}): {error_detail}"}
            except Exception as e:
                return {"status": "error", "message": f"Error: {str(e)}"}
    
    async def apply_tunnel(self, node_id: str, tunnel_data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply tunnel to node"""
        return await self.send_to_node(node_id, "/api/agent/tunnels/apply", tunnel_data)

    async def get_node_health(self, node_id: str, timeout_s: float = 5.0) -> Dict[str, Any]:
        """Fetch bulk per-tunnel health from a node's /api/agent/health.

        Returns the parsed JSON on success. On any failure returns
        ``{"reachable": False, "message": ...}`` so the caller can tell a real
        "node is down" from "node says it has no tunnels" and avoid destructive
        reconciliation when the node is merely unreachable.

        Falls back to /api/agent/status for nodes not yet updated (the result
        then has ``running`` ids but per-tunnel health is unknown).
        """
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Node).where(Node.id == node_id))
            node = result.scalar_one_or_none()
            if not node:
                return {"reachable": False, "message": f"Node {node_id} not found"}
            node_address, using_frp = await self._get_node_address(node)
            base = node_address.rstrip("/")
            timeout = httpx.Timeout(timeout_s, connect=min(3.0, timeout_s))
            attempts = 3 if using_frp else 1
            last_err = None
            for attempt in range(attempts):
                if using_frp and attempt > 0:
                    await asyncio.sleep(1.5)
                try:
                    async with httpx.AsyncClient(
                        timeout=timeout, verify=_verify_tls(),
                        limits=httpx.Limits(max_keepalive_connections=0 if using_frp else 5),
                    ) as client:
                        resp = await client.get(f"{base}/api/agent/health", headers=_node_auth_headers())
                        if resp.status_code == 404:
                            # Old node without the bulk endpoint: fall back to status.
                            sresp = await client.get(f"{base}/api/agent/status", headers=_node_auth_headers())
                            sresp.raise_for_status()
                            sdata = sresp.json()
                            return {
                                "reachable": True,
                                "legacy": True,
                                "running": sdata.get("tunnels", []),
                                "tunnels": {},
                            }
                        resp.raise_for_status()
                        data = resp.json()
                        data["reachable"] = True
                        return data
                except Exception as e:
                    last_err = e
                    continue
            return {"reachable": False, "message": f"{type(last_err).__name__}: {last_err}"}
