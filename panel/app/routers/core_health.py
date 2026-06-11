"""Core Health and Reset API endpoints"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Dict, Any
from datetime import datetime, timedelta
from pydantic import BaseModel
import logging
import asyncio
import httpx

from app.database import get_db
from app.models import Tunnel, Node, CoreResetConfig
from app.node_client import NodeClient

router = APIRouter()
logger = logging.getLogger(__name__)

CORES = ["backhaul", "rathole", "chisel", "frp", "udp2raw", "zapret"]


class CoreHealthResponse(BaseModel):
    core: str
    nodes_status: Dict[str, Dict[str, Any]]  # Iran nodes
    servers_status: Dict[str, Dict[str, Any]]  # Foreign servers


class ResetConfigResponse(BaseModel):
    core: str
    enabled: bool
    interval_minutes: int
    last_reset: datetime | None
    next_reset: datetime | None


class ResetConfigUpdate(BaseModel):
    enabled: bool | None = None
    interval_minutes: int | None = None


@router.get("/health", response_model=List[CoreHealthResponse])
async def get_core_health(request: Request, db: AsyncSession = Depends(get_db)):
    """Get health status for all cores"""
    health_data = []
    
    result = await db.execute(select(Node))
    all_nodes = result.scalars().all()
    
    iran_nodes_all = {n.id: n for n in all_nodes if n.node_metadata and n.node_metadata.get("role") == "iran"}
    foreign_nodes_all = {n.id: n for n in all_nodes if n.node_metadata and n.node_metadata.get("role") == "foreign"}
    
    for core in CORES:
        result = await db.execute(select(Tunnel).where(Tunnel.core == core, Tunnel.status == "active"))
        active_tunnels = result.scalars().all()
        
        node_ids = set(t.node_id for t in active_tunnels if t.node_id)
        
        for tunnel in active_tunnels:
            if tunnel.spec and tunnel.spec.get("foreign_node_id"):
                node_ids.add(tunnel.spec.get("foreign_node_id"))
        
        iran_nodes = {}
        foreign_nodes = {}
        
        client = NodeClient()
        
        async def check_iran_node(node_id, node):
            connection_status = {
                "status": "failed",
                "error_message": None
            }
            
            try:
                response = await client.get_tunnel_status(node_id, "")
                if response and response.get("status") == "ok":
                    connection_status["status"] = "connected"
                else:
                    error_msg = response.get("message", "Node disconnected") if response else "Node not responding"
                    if "timeout" in error_msg.lower() or "connection" in error_msg.lower():
                        connection_status["status"] = "reconnecting"
                    else:
                        connection_status["status"] = "failed"
                    connection_status["error_message"] = error_msg
            except httpx.ConnectError:
                connection_status["status"] = "connecting"
                connection_status["error_message"] = "Connecting to node..."
            except httpx.TimeoutException:
                connection_status["status"] = "reconnecting"
                connection_status["error_message"] = "Connection timeout"
            except Exception as e:
                logger.error(f"Error checking {core} node {node_id} health: {e}")
                connection_status["status"] = "failed"
                connection_status["error_message"] = str(e)
            
            return {
                "id": node_id,
                "name": node.name,
                "role": "iran",
                **connection_status
            }
        
        async def check_foreign_node(node_id, node):
            connection_status = {
                "status": "failed",
                "error_message": None
            }
            
            try:
                response = await client.get_tunnel_status(node_id, "")
                if response and response.get("status") == "ok":
                    connection_status["status"] = "connected"
                else:
                    error_msg = response.get("message", "Node disconnected") if response else "Node not responding"
                    if "timeout" in error_msg.lower() or "connection" in error_msg.lower():
                        connection_status["status"] = "reconnecting"
                    else:
                        connection_status["status"] = "failed"
                    connection_status["error_message"] = error_msg
            except httpx.ConnectError:
                connection_status["status"] = "connecting"
                connection_status["error_message"] = "Connecting to node..."
            except httpx.TimeoutException:
                connection_status["status"] = "reconnecting"
                connection_status["error_message"] = "Connection timeout"
            except Exception as e:
                logger.error(f"Error checking {core} node {node_id} health: {e}")
                connection_status["status"] = "failed"
                connection_status["error_message"] = str(e)
            
            return {
                "id": node_id,
                "name": node.name,
                "role": "foreign",
                **connection_status
            }
        
        iran_tasks = [check_iran_node(node_id, node) for node_id, node in iran_nodes_all.items()]
        foreign_tasks = [check_foreign_node(node_id, node) for node_id, node in foreign_nodes_all.items()]
        
        iran_results = await asyncio.gather(*iran_tasks, return_exceptions=True)
        foreign_results = await asyncio.gather(*foreign_tasks, return_exceptions=True)
        
        for result in iran_results:
            if isinstance(result, Exception):
                continue
            iran_nodes[result["id"]] = result
        
        for result in foreign_results:
            if isinstance(result, Exception):
                continue
            foreign_nodes[result["id"]] = result
        
        health_data.append(CoreHealthResponse(
            core=core,
            nodes_status=iran_nodes,
            servers_status=foreign_nodes
        ))
    
    return health_data


@router.get("/reset-config", response_model=List[ResetConfigResponse])
async def get_reset_configs(db: AsyncSession = Depends(get_db)):
    """Get reset timer configuration for all cores"""
    configs = []
    
    for core in CORES:
        result = await db.execute(select(CoreResetConfig).where(CoreResetConfig.core == core))
        config = result.scalar_one_or_none()
        
        if not config:
            config = CoreResetConfig(
                core=core,
                enabled=False,
                interval_minutes=10
            )
            db.add(config)
            await db.commit()
            await db.refresh(config)
        
        configs.append(ResetConfigResponse(
            core=config.core,
            enabled=config.enabled,
            interval_minutes=config.interval_minutes,
            last_reset=config.last_reset,
            next_reset=config.next_reset
        ))
    
    return configs


@router.put("/reset-config/{core}", response_model=ResetConfigResponse)
async def update_reset_config(
    core: str,
    config_update: ResetConfigUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update reset timer configuration for a core"""
    if core not in CORES:
        raise HTTPException(status_code=400, detail=f"Invalid core: {core}")
    
    result = await db.execute(select(CoreResetConfig).where(CoreResetConfig.core == core))
    config = result.scalar_one_or_none()
    
    if not config:
        config = CoreResetConfig(core=core, enabled=False, interval_minutes=10)
        db.add(config)
    
    if config_update.enabled is not None:
        config.enabled = config_update.enabled
    
    if config_update.interval_minutes is not None:
        if config_update.interval_minutes < 1:
            raise HTTPException(status_code=400, detail="Interval must be at least 1 minute")
        config.interval_minutes = config_update.interval_minutes
    
        if config.enabled and config.interval_minutes:
            now = datetime.utcnow()
            if config.last_reset:
                calculated_next = config.last_reset + timedelta(minutes=config.interval_minutes)
                if calculated_next > now:
                    config.next_reset = calculated_next
                else:
                    config.next_reset = now + timedelta(minutes=config.interval_minutes)
            else:
                config.next_reset = now + timedelta(minutes=config.interval_minutes)
    else:
        config.next_reset = None
    
    config.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(config)
    
    return ResetConfigResponse(
        core=config.core,
        enabled=config.enabled,
        interval_minutes=config.interval_minutes,
        last_reset=config.last_reset,
        next_reset=config.next_reset
    )


@router.post("/reset/{core}")
async def manual_reset_core(core: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Manually reset a core (restart servers and clients)"""
    if core not in CORES:
        raise HTTPException(status_code=400, detail=f"Invalid core: {core}")
    
    try:
        result = await db.execute(select(CoreResetConfig).where(CoreResetConfig.core == core))
        config = result.scalar_one_or_none()
        
        reset_time = datetime.utcnow()
        
        if not config:
            config = CoreResetConfig(core=core, enabled=False, interval_minutes=10)
            db.add(config)
        
        config.last_reset = reset_time
        if config.enabled and config.interval_minutes:
            config.next_reset = reset_time + timedelta(minutes=config.interval_minutes)
        await db.commit()
        await db.refresh(config)
        
        await _reset_core(core, request, db)
        
        return {
            "status": "success",
            "message": f"{core} reset successfully",
            "last_reset": config.last_reset.isoformat() if config.last_reset else None
        }
    except Exception as e:
        logger.error(f"Error resetting {core}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


async def _reset_core(core: str, app_or_request, db: AsyncSession):
    """Internal function to reset a core - handles both foreign and iran nodes"""
    if hasattr(app_or_request, 'app'):
        app = app_or_request.app
    else:
        app = app_or_request
    
    result = await db.execute(select(Tunnel).where(Tunnel.core == core, Tunnel.status == "active"))
    active_tunnels = result.scalars().all()
    
    client = NodeClient()
    
    for tunnel in active_tunnels:
        try:
            if core == "zapret":
                # zapret is single-node: just re-push the spec to its node.
                target = None
                if tunnel.node_id:
                    result = await db.execute(select(Node).where(Node.id == tunnel.node_id))
                    target = result.scalar_one_or_none()
                if not target:
                    logger.warning(f"Tunnel {tunnel.id}: zapret node not found, skipping reset")
                    continue
                spec = tunnel.spec.copy() if tunnel.spec else {}
                if not target.node_metadata.get("api_address"):
                    target.node_metadata["api_address"] = f"http://{target.node_metadata.get('ip_address', target.fingerprint)}:{target.node_metadata.get('api_port', 8888)}"
                    await db.commit()
                resp = await client.send_to_node(
                    node_id=target.id,
                    endpoint="/api/agent/tunnels/apply",
                    data={"tunnel_id": tunnel.id, "core": core, "type": tunnel.type, "spec": spec},
                )
                if resp.get("status") == "error":
                    logger.error(f"Failed to reset zapret tunnel {tunnel.id}: {resp.get('message')}")
                await asyncio.sleep(0.5)
                continue

            iran_node = None
            foreign_node = None
            
            if tunnel.node_id:
                result = await db.execute(select(Node).where(Node.id == tunnel.node_id))
                iran_node = result.scalar_one_or_none()
                if iran_node and iran_node.node_metadata.get("role") != "iran":
                    foreign_node = iran_node
                    iran_node = None
            
            if not foreign_node:
                result = await db.execute(select(Node))
                all_nodes = result.scalars().all()
                foreign_nodes = [n for n in all_nodes if n.node_metadata and n.node_metadata.get("role") == "foreign"]
                if foreign_nodes:
                    foreign_node = foreign_nodes[0]
            
            if not iran_node:
                if tunnel.node_id:
                    result = await db.execute(select(Node).where(Node.id == tunnel.node_id))
                    iran_node = result.scalar_one_or_none()
                if not iran_node:
                    result = await db.execute(select(Node))
                    all_nodes = result.scalars().all()
                    iran_nodes = [n for n in all_nodes if n.node_metadata and n.node_metadata.get("role") == "iran"]
                    if iran_nodes:
                        iran_node = iran_nodes[0]
            
            if not foreign_node or not iran_node:
                logger.warning(f"Tunnel {tunnel.id}: Missing foreign or iran node, skipping reset")
                continue
            
            server_spec = tunnel.spec.copy() if tunnel.spec else {}
            server_spec["mode"] = "server"
            
            client_spec = tunnel.spec.copy() if tunnel.spec else {}
            client_spec["mode"] = "client"
            
            if core == "rathole":
                transport = server_spec.get("transport") or server_spec.get("type") or "tcp"
                proxy_port = server_spec.get("remote_port") or server_spec.get("listen_port")
                token = server_spec.get("token")
                if not proxy_port or not token:
                    logger.warning(f"Tunnel {tunnel.id}: Missing remote_port or token, skipping")
                    continue
                
                remote_addr = server_spec.get("remote_addr", "0.0.0.0:23333")
                from app.utils import parse_address_port
                _, control_port, _ = parse_address_port(remote_addr)
                if not control_port:
                    control_port = 23333
                server_spec["bind_addr"] = f"0.0.0.0:{control_port}"
                server_spec["proxy_port"] = proxy_port
                server_spec["transport"] = transport
                server_spec["type"] = transport
                if "websocket_tls" in server_spec:
                    server_spec["websocket_tls"] = server_spec["websocket_tls"]
                elif "tls" in server_spec:
                    server_spec["websocket_tls"] = server_spec["tls"]
                
                iran_node_ip = iran_node.node_metadata.get("ip_address")
                if not iran_node_ip:
                    logger.warning(f"Tunnel {tunnel.id}: Iran node has no IP address, skipping")
                    continue
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
                if "websocket_tls" in server_spec:
                    client_spec["websocket_tls"] = server_spec["websocket_tls"]
                elif "tls" in server_spec:
                    client_spec["websocket_tls"] = server_spec["tls"]
                local_addr = client_spec.get("local_addr")
                if not local_addr:
                    local_addr = f"{iran_node_ip}:{proxy_port}"
                client_spec["local_addr"] = local_addr
            
            elif core == "chisel":
                listen_port = server_spec.get("listen_port") or server_spec.get("remote_port")
                if not listen_port:
                    logger.warning(f"Tunnel {tunnel.id}: Missing listen_port, skipping")
                    continue
                
                iran_node_ip = iran_node.node_metadata.get("ip_address")
                if not iran_node_ip:
                    logger.warning(f"Tunnel {tunnel.id}: Iran node has no IP address, skipping")
                    continue
                server_control_port = server_spec.get("control_port") or (int(listen_port) + 10000)
                server_spec["server_port"] = server_control_port
                server_spec["reverse_port"] = listen_port
                auth = server_spec.get("auth")
                if auth:
                    server_spec["auth"] = auth
                fingerprint = server_spec.get("fingerprint")
                if fingerprint:
                    server_spec["fingerprint"] = fingerprint
                
                client_spec["server_url"] = f"http://{iran_node_ip}:{server_control_port}"
                client_spec["reverse_port"] = listen_port
                if auth:
                    client_spec["auth"] = auth
                if fingerprint:
                    client_spec["fingerprint"] = fingerprint
                local_addr = client_spec.get("local_addr")
                if not local_addr:
                    local_addr = f"{iran_node_ip}:{listen_port}"
                client_spec["local_addr"] = local_addr
            
            elif core == "frp":
                bind_port = server_spec.get("bind_port", 7000)
                token = server_spec.get("token")
                server_spec["mode"] = "server"
                server_spec["bind_port"] = bind_port
                if token:
                    server_spec["token"] = token
                
                iran_node_ip = iran_node.node_metadata.get("ip_address")
                if not iran_node_ip:
                    logger.warning(f"Tunnel {tunnel.id}: Iran node has no IP address, skipping")
                    continue
                client_spec["mode"] = "client"
                client_spec["server_addr"] = iran_node_ip
                client_spec["server_port"] = bind_port
                if token:
                    client_spec["token"] = token
                tunnel_type = tunnel.type.lower() if tunnel.type else "tcp"
                if tunnel_type not in ["tcp", "udp"]:
                    tunnel_type = "tcp"
                client_spec["type"] = tunnel_type
                local_ip = client_spec.get("local_ip") or iran_node_ip
                local_port = client_spec.get("local_port") or bind_port
                client_spec["local_ip"] = local_ip
                client_spec["local_port"] = local_port
            
            elif core == "backhaul":
                transport = server_spec.get("transport") or server_spec.get("type") or "tcp"
                control_port = server_spec.get("control_port") or server_spec.get("listen_port") or 3080
                public_port = server_spec.get("public_port") or server_spec.get("remote_port") or server_spec.get("listen_port")
                target_host = server_spec.get("target_host", "127.0.0.1")
                target_port = server_spec.get("target_port") or public_port
                token = server_spec.get("token")
                
                if not public_port:
                    logger.warning(f"Tunnel {tunnel.id}: Missing public_port, skipping")
                    continue
                
                bind_ip = server_spec.get("bind_ip") or server_spec.get("listen_ip") or "0.0.0.0"
                server_spec["bind_addr"] = f"{bind_ip}:{control_port}"
                server_spec["transport"] = transport
                server_spec["type"] = transport
                if target_port:
                    target_addr = f"{target_host}:{target_port}"
                    server_spec["ports"] = [f"{public_port}={target_addr}"]
                else:
                    server_spec["ports"] = [str(public_port)]
                if token:
                    server_spec["token"] = token
                
                iran_node_ip = iran_node.node_metadata.get("ip_address")
                if not iran_node_ip:
                    logger.warning(f"Tunnel {tunnel.id}: Iran node has no IP address, skipping")
                    continue
                transport_lower = transport.lower()
                if transport_lower in ("ws", "wsmux"):
                    use_tls = bool(server_spec.get("tls_cert") or server_spec.get("server_options", {}).get("tls_cert"))
                    protocol = "wss://" if use_tls else "ws://"
                    client_spec["remote_addr"] = f"{protocol}{iran_node_ip}:{control_port}"
                else:
                    client_spec["remote_addr"] = f"{iran_node_ip}:{control_port}"
                client_spec["transport"] = transport
                client_spec["type"] = transport
                if token:
                    client_spec["token"] = token
            
            elif core == "udp2raw":
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
            
            if not iran_node.node_metadata.get("api_address"):
                iran_node.node_metadata["api_address"] = f"http://{iran_node.node_metadata.get('ip_address', iran_node.fingerprint)}:{iran_node.node_metadata.get('api_port', 8888)}"
                await db.commit()
            
            logger.info(f"Restarting tunnel {tunnel.id}: applying server config to iran node {iran_node.id}")
            server_response = await client.send_to_node(
                node_id=iran_node.id,
                endpoint="/api/agent/tunnels/apply",
                data={
                    "tunnel_id": tunnel.id,
                    "core": core,
                    "type": tunnel.type,
                    "spec": server_spec
                }
            )
            
            if server_response.get("status") == "error":
                error_msg = server_response.get("message", "Unknown error from iran node")
                logger.error(f"Failed to restart tunnel {tunnel.id} on iran node {iran_node.id}: {error_msg}")
                continue
            
            if not foreign_node.node_metadata.get("api_address"):
                foreign_node.node_metadata["api_address"] = f"http://{foreign_node.node_metadata.get('ip_address', foreign_node.fingerprint)}:{foreign_node.node_metadata.get('api_port', 8888)}"
                await db.commit()
            
            logger.info(f"Restarting tunnel {tunnel.id}: applying client config to foreign node {foreign_node.id}")
            client_response = await client.send_to_node(
                node_id=foreign_node.id,
                endpoint="/api/agent/tunnels/apply",
                data={
                    "tunnel_id": tunnel.id,
                    "core": core,
                    "type": tunnel.type,
                    "spec": client_spec
                }
            )
            
            if client_response.get("status") == "error":
                error_msg = client_response.get("message", "Unknown error from foreign node")
                logger.error(f"Failed to restart tunnel {tunnel.id} on foreign node {foreign_node.id}: {error_msg}")
            else:
                logger.info(f"Successfully restarted tunnel {tunnel.id} on both nodes")
            
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Failed to restart tunnel {tunnel.id}: {e}", exc_info=True)

