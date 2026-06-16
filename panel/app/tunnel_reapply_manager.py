"""Tunnel auto reapply manager"""
import asyncio
import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import Settings, Tunnel
from app.node_client import NodeClient
from fastapi import Request

logger = logging.getLogger(__name__)


class TunnelReapplyManager:
    """Manages automatic tunnel reapplication"""
    
    def __init__(self):
        self.task: Optional[asyncio.Task] = None
        self.enabled = False
        self.interval = 60
        self.interval_unit = "minutes"
        self.request: Optional[Request] = None
        # Per-tunnel scheduled restart (independent of the global auto-reapply).
        self._cron_task: Optional[asyncio.Task] = None
        self._last_restart: dict = {}
    
    async def load_settings(self):
        """Load settings from database"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Settings).where(Settings.key == "tunnel"))
            setting = result.scalar_one_or_none()
            if setting and setting.value:
                self.enabled = setting.value.get("auto_reapply_enabled", False)
                self.interval = setting.value.get("auto_reapply_interval", 60)
                self.interval_unit = setting.value.get("auto_reapply_interval_unit", "minutes")
            else:
                self.enabled = False
                self.interval = 60
                self.interval_unit = "minutes"
    
    async def start(self):
        """Start auto reapply task"""
        await self.stop()
        await self.load_settings()
        
        if self.enabled:
            self.task = asyncio.create_task(self._reapply_loop())
            logger.info(f"Tunnel auto reapply task started: interval={self.interval} {self.interval_unit}")
    
    async def stop(self):
        """Stop auto reapply task"""
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
            logger.info("Tunnel auto reapply task stopped")
    
    async def _reapply_loop(self):
        """Background task for automatic tunnel reapplication"""
        try:
            while True:
                await self.load_settings()
                
                if not self.enabled:
                    await asyncio.sleep(60)
                    continue
                
                if self.interval_unit == "hours":
                    sleep_seconds = self.interval * 3600
                else:
                    sleep_seconds = self.interval * 60
                
                await asyncio.sleep(sleep_seconds)
                
                if not self.enabled:
                    continue
                
                try:
                    await self._reapply_all_tunnels()
                except Exception as e:
                    logger.error(f"Error in automatic tunnel reapply: {e}", exc_info=True)
        except asyncio.CancelledError:
            logger.info("Tunnel reapply loop cancelled")
            raise
        except Exception as e:
            logger.error(f"Tunnel reapply loop error: {e}", exc_info=True)
    
    async def _reapply_all_tunnels(self, tunnel_ids=None):
        """Reapply all active tunnels, or only the given ids. Returns (applied, failed)."""
        from app.routers.tunnels import prepare_frp_spec_for_node
        from app.models import Node
        from fastapi import Request
        from starlette.requests import Request as StarletteRequest
        
        async with AsyncSessionLocal() as session:
            query = select(Tunnel).where(Tunnel.status == "active")
            if tunnel_ids:
                query = query.where(Tunnel.id.in_(list(tunnel_ids)))
            result = await session.execute(query)
            tunnels = result.scalars().all()
            
            if not tunnels:
                logger.debug("No active tunnels to reapply")
                return 0, 0
            
            client = NodeClient()
            applied = 0
            failed = 0
            
            from starlette.requests import Request as StarletteRequest
            from starlette.datastructures import Headers
            
            fake_request = StarletteRequest(
                scope={
                    "type": "http",
                    "method": "POST",
                    "path": "/api/tunnels/reapply",
                    "headers": Headers({}).raw,
                    "query_string": b"",
                }
            )
            
            for tunnel in tunnels:
                try:
                    is_reverse_tunnel = tunnel.core in {"rathole", "backhaul", "chisel", "frp", "udp2raw", "trusttunnel"}
                    
                    if is_reverse_tunnel:
                        iran_node_id = tunnel.iran_node_id or tunnel.node_id
                        if not iran_node_id:
                            continue
                            
                        result = await session.execute(select(Node).where(Node.id == iran_node_id))
                        iran_node = result.scalar_one_or_none()
                        if not iran_node:
                            continue
                        
                        result = await session.execute(select(Node))
                        all_nodes = result.scalars().all()
                        # Route to THIS tunnel's foreign node, not just the first one.
                        # Using foreign_nodes[0] re-pushed every tunnel's client to a
                        # single node, so multiple foreign nodes fought over the same
                        # rathole service ("Dropping previous control channel") and the
                        # tunnels kept dropping. Fall back to the first only for legacy
                        # tunnels that never recorded a foreign_node_id.
                        foreign_node = None
                        if tunnel.foreign_node_id:
                            foreign_node = next((n for n in all_nodes if n.id == tunnel.foreign_node_id), None)
                        if not foreign_node:
                            foreign_nodes = [n for n in all_nodes if n.node_metadata and n.node_metadata.get("role") == "foreign"]
                            if not foreign_nodes:
                                continue
                            foreign_node = foreign_nodes[0]
                        
                        spec = tunnel.spec.copy() if tunnel.spec else {}
                        
                        if tunnel.core == "frp":
                            bind_port = spec.get("bind_port", 7000)
                            token = spec.get("token")
                            
                            iran_node_ip = iran_node.node_metadata.get("ip_address")
                            if not iran_node_ip:
                                logger.warning(f"Tunnel {tunnel.id}: Iran node has no IP address, skipping")
                                failed += 1
                                continue
                            
                            spec_for_iran = spec.copy()
                            spec_for_iran["mode"] = "server"
                            spec_for_iran["bind_port"] = bind_port
                            if token:
                                spec_for_iran["token"] = token
                            
                            spec_for_foreign = spec.copy()
                            spec_for_foreign["mode"] = "client"
                            spec_for_foreign["server_addr"] = iran_node_ip
                            spec_for_foreign["server_port"] = bind_port
                            if token:
                                spec_for_foreign["token"] = token
                            tunnel_type = tunnel.type.lower() if tunnel.type else "tcp"
                            if tunnel_type not in ["tcp", "udp"]:
                                tunnel_type = "tcp"
                            spec_for_foreign["type"] = tunnel_type
                            
                            ports = spec.get("ports", [])
                            if not ports:
                                local_port = spec.get("local_port")
                                remote_port = spec.get("remote_port") or spec.get("listen_port")
                                if remote_port and local_port:
                                    spec_for_foreign["ports"] = [{"local": int(local_port), "remote": int(remote_port)}]
                                elif remote_port:
                                    spec_for_foreign["ports"] = [{"local": int(remote_port), "remote": int(remote_port)}]
                                elif local_port:
                                    spec_for_foreign["ports"] = [{"local": int(local_port), "remote": int(local_port)}]
                            else:
                                spec_for_foreign["ports"] = ports
                            
                            server_response = await client.send_to_node(
                                node_id=iran_node.id,
                                endpoint="/api/agent/tunnels/apply",
                                data={
                                    "tunnel_id": tunnel.id,
                                    "core": tunnel.core,
                                    "type": tunnel.type,
                                    "spec": spec_for_iran
                                }
                            )
                            
                            if server_response.get("status") == "error":
                                logger.error(f"Failed to reapply tunnel {tunnel.id} to iran node: {server_response.get('message')}")
                                failed += 1
                                continue
                            
                            client_response = await client.send_to_node(
                                node_id=foreign_node.id,
                                endpoint="/api/agent/tunnels/apply",
                                data={
                                    "tunnel_id": tunnel.id,
                                    "core": tunnel.core,
                                    "type": tunnel.type,
                                    "spec": spec_for_foreign
                                }
                            )
                            
                            if client_response.get("status") == "error":
                                logger.error(f"Failed to reapply tunnel {tunnel.id} to foreign node: {client_response.get('message')}")
                                failed += 1
                                continue
                            
                            if server_response.get("status") == "success" and client_response.get("status") == "success":
                                applied += 1
                                logger.info(f"Successfully reapplied tunnel {tunnel.id} ({tunnel.core})")
                            else:
                                failed += 1
                        else:
                            server_spec = spec.copy()
                            server_spec["mode"] = "server"
                            client_spec = spec.copy()
                            client_spec["mode"] = "client"
                            
                            if tunnel.core == "rathole":
                                transport = server_spec.get("transport") or server_spec.get("type") or "tcp"
                                proxy_port = server_spec.get("remote_port") or server_spec.get("listen_port")
                                token = server_spec.get("token")
                                if not proxy_port or not token:
                                    continue
                                
                                from app.utils import parse_address_port
                                remote_addr = server_spec.get("remote_addr", "0.0.0.0:23333")
                                _, control_port, _ = parse_address_port(remote_addr)
                                if not control_port:
                                    import hashlib
                                    port_hash = int(hashlib.md5(tunnel.id.encode()).hexdigest()[:8], 16)
                                    control_port = 23333 + (port_hash % 1000)
                                server_spec["mode"] = "server"
                                server_spec["bind_addr"] = f"0.0.0.0:{control_port}"
                                server_spec["proxy_port"] = proxy_port
                                server_spec["transport"] = transport
                                server_spec["token"] = token
                                
                                iran_node_ip = iran_node.node_metadata.get("ip_address")
                                if not iran_node_ip:
                                    continue
                                transport_lower = transport.lower()
                                if transport_lower in ("websocket", "ws"):
                                    use_tls = bool(server_spec.get("websocket_tls") or server_spec.get("tls"))
                                    protocol = "wss://" if use_tls else "ws://"
                                    client_spec["remote_addr"] = f"{protocol}{iran_node_ip}:{control_port}"
                                else:
                                    client_spec["remote_addr"] = f"{iran_node_ip}:{control_port}"
                                client_spec["mode"] = "client"
                                client_spec["transport"] = transport
                                client_spec["token"] = token
                            
                            elif tunnel.core == "backhaul":
                                transport = server_spec.get("transport") or server_spec.get("type") or "tcp"
                                control_port = server_spec.get("control_port") or server_spec.get("public_port") or server_spec.get("listen_port") or 3080
                                public_port = server_spec.get("public_port") or server_spec.get("listen_port") or control_port
                                target_host = server_spec.get("target_host", "127.0.0.1")
                                token = server_spec.get("token")
                                
                                server_spec["bind_addr"] = f"0.0.0.0:{control_port}"
                                server_spec["control_port"] = control_port
                                server_spec["public_port"] = public_port
                                server_spec["listen_port"] = public_port
                                ports = server_spec.get("ports", [])
                                if ports:
                                    server_spec["ports"] = ports
                                if token:
                                    server_spec["token"] = token
                                
                                iran_node_ip = iran_node.node_metadata.get("ip_address")
                                if not iran_node_ip:
                                    continue
                                transport_lower = transport.lower()
                                if transport_lower in ("ws", "wsmux"):
                                    use_tls = bool(server_spec.get("tls_cert") or server_spec.get("server_options", {}).get("tls_cert"))
                                    protocol = "wss://" if use_tls else "ws://"
                                    client_spec["remote_addr"] = f"{protocol}{iran_node_ip}:{control_port}"
                                else:
                                    client_spec["remote_addr"] = f"{iran_node_ip}:{control_port}"
                                client_spec["transport"] = transport
                                if token:
                                    client_spec["token"] = token
                            
                            elif tunnel.core == "chisel":
                                listen_port = server_spec.get("listen_port") or server_spec.get("remote_port")
                                if not listen_port:
                                    continue
                                
                                import hashlib
                                port_hash = int(hashlib.md5(tunnel.id.encode()).hexdigest()[:8], 16)
                                server_control_port = server_spec.get("control_port") or (int(listen_port) + 10000 + (port_hash % 1000))
                                server_spec["mode"] = "server"
                                server_spec["server_port"] = server_control_port
                                server_spec["reverse_port"] = listen_port
                                
                                iran_node_ip = iran_node.node_metadata.get("ip_address")
                                if not iran_node_ip:
                                    continue
                                from app.utils import is_valid_ipv6_address
                                if is_valid_ipv6_address(iran_node_ip):
                                    client_spec["server_url"] = f"http://[{iran_node_ip}]:{server_control_port}"
                                else:
                                    client_spec["server_url"] = f"http://{iran_node_ip}:{server_control_port}"
                                client_spec["mode"] = "client"
                                client_spec["reverse_port"] = listen_port
                            
                            elif tunnel.core == "udp2raw":
                                # Iran node runs the udp2raw CLIENT (public entry point),
                                # foreign node runs the udp2raw SERVER.
                                raw_mode = (tunnel.type or server_spec.get("raw_mode") or "faketcp").lower()
                                if raw_mode not in {"faketcp", "icmp", "udp"}:
                                    raw_mode = "faketcp"
                                
                                key = server_spec.get("key") or server_spec.get("token")
                                listen_port = server_spec.get("listen_port") or server_spec.get("public_port")
                                if not listen_port:
                                    ports = server_spec.get("ports") or []
                                    listen_port = ports[0] if ports else None
                                if not key or not listen_port:
                                    logger.warning(f"Tunnel {tunnel.id}: Missing key or listen_port, skipping")
                                    continue
                                
                                import hashlib
                                port_hash = int(hashlib.md5(tunnel.id.encode()).hexdigest()[:8], 16)
                                raw_port = server_spec.get("raw_port") or (4096 + (port_hash % 1000))
                                target_host = server_spec.get("target_host", "127.0.0.1")
                                target_port = server_spec.get("target_port") or listen_port
                                cipher_mode = server_spec.get("cipher_mode") or "aes128cbc"
                                auth_mode = server_spec.get("auth_mode") or "md5"
                                
                                foreign_node_ip = foreign_node.node_metadata.get("ip_address")
                                if not foreign_node_ip:
                                    logger.warning(f"Tunnel {tunnel.id}: Foreign node has no IP address, skipping")
                                    continue
                                
                                from app.utils import format_address_port
                                server_spec["mode"] = "client"
                                server_spec["raw_mode"] = raw_mode
                                server_spec["listen_addr"] = f"0.0.0.0:{listen_port}"
                                server_spec["remote_addr"] = format_address_port(foreign_node_ip, int(raw_port))
                                server_spec["key"] = key
                                server_spec["cipher_mode"] = cipher_mode
                                server_spec["auth_mode"] = auth_mode
                                
                                client_spec["mode"] = "server"
                                client_spec["raw_mode"] = raw_mode
                                client_spec["listen_addr"] = f"0.0.0.0:{raw_port}"
                                client_spec["forward_addr"] = format_address_port(target_host, int(target_port))
                                client_spec["key"] = key
                                client_spec["cipher_mode"] = cipher_mode
                                client_spec["auth_mode"] = auth_mode

                            elif tunnel.core == "trusttunnel":
                                # Iran node runs rstund (server), foreign runs rstunc (client).
                                transport = (tunnel.type or server_spec.get("transport") or "tcp").lower()
                                if transport not in {"tcp", "udp", "both"}:
                                    transport = "tcp"
                                password = server_spec.get("password") or server_spec.get("token")
                                ports = server_spec.get("ports") or []
                                if isinstance(ports, str):
                                    ports = [int(p) for p in ports.split(",") if p.strip().isdigit()]
                                if not ports:
                                    single = server_spec.get("listen_port") or server_spec.get("public_port")
                                    if single and str(single).isdigit():
                                        ports = [int(single)]
                                if not password or not ports:
                                    continue

                                import hashlib
                                port_hash = int(hashlib.md5(tunnel.id.encode()).hexdigest()[:8], 16)
                                control_port = server_spec.get("control_port") or (6100 + (port_hash % 800))
                                target_host = server_spec.get("target_host", "127.0.0.1")

                                iran_node_ip = iran_node.node_metadata.get("ip_address")
                                if not iran_node_ip:
                                    continue

                                from app.utils import format_address_port
                                server_spec["mode"] = "server"
                                server_spec["transport"] = transport
                                server_spec["password"] = password
                                server_spec["control_port"] = control_port
                                server_spec["target_host"] = target_host
                                server_spec["ports"] = ports

                                client_spec["mode"] = "client"
                                client_spec["transport"] = transport
                                client_spec["password"] = password
                                client_spec["server_addr"] = format_address_port(iran_node_ip, int(control_port))
                                client_spec["target_host"] = target_host
                                client_spec["ports"] = ports
                            
                            server_response = await client.send_to_node(
                                node_id=iran_node.id,
                                endpoint="/api/agent/tunnels/apply",
                                data={
                                    "tunnel_id": tunnel.id,
                                    "core": tunnel.core,
                                    "type": tunnel.type,
                                    "spec": server_spec
                                }
                            )
                            
                            if server_response.get("status") == "error":
                                logger.error(f"Failed to reapply tunnel {tunnel.id} to iran node: {server_response.get('message')}")
                                failed += 1
                                continue
                            
                            client_response = await client.send_to_node(
                                node_id=foreign_node.id,
                                endpoint="/api/agent/tunnels/apply",
                                data={
                                    "tunnel_id": tunnel.id,
                                    "core": tunnel.core,
                                    "type": tunnel.type,
                                    "spec": client_spec
                                }
                            )
                            
                            if client_response.get("status") == "error":
                                logger.error(f"Failed to reapply tunnel {tunnel.id} to foreign node: {client_response.get('message')}")
                                failed += 1
                                continue
                            
                            if server_response.get("status") == "success" and client_response.get("status") == "success":
                                applied += 1
                                logger.info(f"Successfully reapplied tunnel {tunnel.id} ({tunnel.core})")
                            else:
                                failed += 1
                    else:
                        result = await session.execute(select(Node).where(Node.id == tunnel.node_id))
                        node = result.scalar_one_or_none()
                        if not node:
                            continue
                        
                        spec = tunnel.spec.copy() if tunnel.spec else {}
                        
                        if tunnel.core == "gost":
                            spec["type"] = tunnel.type
                        
                        if tunnel.core == "frp":
                            spec = prepare_frp_spec_for_node(spec, node, fake_request)
                        
                        response = await client.send_to_node(
                            node_id=node.id,
                            endpoint="/api/agent/tunnels/apply",
                            data={
                                "tunnel_id": tunnel.id,
                                "core": tunnel.core,
                                "type": tunnel.type,
                                "spec": spec
                            }
                        )
                        
                        if response.get("status") == "success":
                            applied += 1
                            logger.info(f"Successfully reapplied tunnel {tunnel.id} ({tunnel.core})")
                        else:
                            failed += 1
                            logger.error(f"Failed to reapply tunnel {tunnel.id}: {response.get('message')}")
                except Exception as e:
                    logger.error(f"Error reapplying tunnel {tunnel.id}: {e}", exc_info=True)
                    failed += 1
            
            logger.info(f"Auto reapply completed: {applied} applied, {failed} failed")
            return applied, failed
    
    async def reapply_tunnels(self, tunnel_ids):
        """Restart (re-apply) specific tunnels on demand. Returns (applied, failed)."""
        ids = [t for t in (tunnel_ids or []) if t]
        if not ids:
            return 0, 0
        try:
            return await self._reapply_all_tunnels(tunnel_ids=ids)
        except Exception as e:
            logger.error(f"reapply_tunnels error: {e}", exc_info=True)
            return 0, len(ids)
    
    async def start_cron(self):
        """Start the per-tunnel scheduled-restart loop (runs independently)."""
        if self._cron_task and not self._cron_task.done():
            return
        self._cron_task = asyncio.create_task(self._cron_loop())
        logger.info("Per-tunnel scheduled-restart loop started")
    
    async def stop_cron(self):
        if self._cron_task:
            self._cron_task.cancel()
            try:
                await self._cron_task
            except asyncio.CancelledError:
                pass
            self._cron_task = None
    
    async def _cron_loop(self):
        """Every minute, restart tunnels whose per-tunnel schedule is due."""
        import time as _time
        try:
            while True:
                await asyncio.sleep(60)
                try:
                    now = _time.time()
                    async with AsyncSessionLocal() as session:
                        result = await session.execute(select(Tunnel).where(Tunnel.status == "active"))
                        tunnels = result.scalars().all()
                    due = []
                    active_ids = set()
                    for t in tunnels:
                        active_ids.add(t.id)
                        spec = t.spec or {}
                        try:
                            mins = int(spec.get("auto_restart_minutes") or 0)
                        except (TypeError, ValueError):
                            mins = 0
                        if mins <= 0:
                            continue
                        last = self._last_restart.get(t.id, 0)
                        if now - last >= mins * 60:
                            due.append(t.id)
                    # Forget tunnels that no longer exist.
                    for gone in [tid for tid in self._last_restart if tid not in active_ids]:
                        self._last_restart.pop(gone, None)
                    for tid in due:
                        self._last_restart[tid] = now
                        applied, failed = await self.reapply_tunnels([tid])
                        logger.info(f"Per-tunnel scheduled restart of {tid}: applied={applied} failed={failed}")
                except Exception as e:
                    logger.error(f"Per-tunnel restart cron error: {e}", exc_info=True)
        except asyncio.CancelledError:
            logger.info("Per-tunnel scheduled-restart loop cancelled")
            raise
    
    def set_request(self, request: Request):
        """Set request object for reapply operations"""
        self.request = request


tunnel_reapply_manager = TunnelReapplyManager()

