"""Nodes API endpoints"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from datetime import datetime
from pydantic import BaseModel
import httpx
import logging
import os


def _node_auth_enforced() -> bool:
    return os.environ.get("NODE_AUTH_ENFORCE", "").strip().lower() in ("1", "true", "yes", "on")

from app.database import get_db
from app.models import Node, Settings, RevokedNode
from app.node_client import NodeClient
from app.routers.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


class NodeCreate(BaseModel):
    name: str
    ip_address: str
    api_port: int = 8888
    metadata: dict = {}


class NodeResponse(BaseModel):
    id: str
    name: str
    fingerprint: str
    status: str
    registered_at: datetime
    last_seen: datetime
    metadata: dict
    
    class Config:
        from_attributes = True
    


@router.post("", response_model=NodeResponse)
async def create_node(node: NodeCreate, db: AsyncSession = Depends(get_db)):
    """Register a new node"""
    import hashlib
    
    fingerprint_data = f"{node.ip_address}:{node.api_port}".encode()
    fingerprint = hashlib.sha256(fingerprint_data).hexdigest()[:16]
    
    # A deleted node keeps its agent running and re-registers every 60s. Block
    # re-registration for fingerprints an admin explicitly revoked.
    revoked = await db.execute(select(RevokedNode).where(RevokedNode.fingerprint == fingerprint))
    if revoked.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=403,
            detail="This node was removed by an administrator and is blocked from re-registering. "
                   "Clear its revocation in the panel to allow it again.",
        )
    
    result = await db.execute(select(Node).where(Node.fingerprint == fingerprint))
    existing = result.scalar_one_or_none()
    
    metadata = node.metadata.copy() if node.metadata else {}
    metadata["api_address"] = f"http://{node.ip_address}:{node.api_port}"
    metadata["ip_address"] = node.ip_address
    metadata["api_port"] = node.api_port
    
    incoming_role = node.metadata.get("role", "iran") if node.metadata else "iran"
    if incoming_role not in ["iran", "foreign"]:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid role '{incoming_role}'. Role must be either 'iran' or 'foreign'"
        )
    metadata["role"] = incoming_role
    
    if existing:
        existing_role = existing.node_metadata.get("role", "iran") if existing.node_metadata else "iran"
        if existing_role != incoming_role:
            raise HTTPException(
                status_code=409,
                detail=f"Node with this fingerprint already exists with role '{existing_role}'. "
                       f"Cannot register as '{incoming_role}'. "
                       f"Each node must have a consistent role."
            )
        
        existing.last_seen = datetime.utcnow()
        existing.status = "active"
        existing.node_metadata.update(metadata)
        existing.node_metadata["role"] = existing_role
        await db.commit()
        await db.refresh(existing)
        
        response_metadata = existing.node_metadata.copy() if existing.node_metadata else {}
        
        result = await db.execute(select(Settings).where(Settings.key == "frp"))
        frp_setting = result.scalar_one_or_none()
        # Only foreign nodes use the FRP reverse channel. Iran/domestic nodes are
        # reachable directly, and (when co-located with the panel) starting FRP for
        # them is unnecessary. Restricting to foreign avoids touching working nodes.
        if frp_setting and frp_setting.value and frp_setting.value.get("enabled") and existing_role == "foreign":
            panel_host = node.metadata.get("panel_address", "").split(":")[0] if node.metadata else ""
            if not panel_host or panel_host == "panel.example.com":
                import socket
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.connect(("8.8.8.8", 80))
                    panel_host = s.getsockname()[0]
                    s.close()
                except:
                    panel_host = "127.0.0.1"
            
            response_metadata["frp_config"] = {
                "enabled": True,
                "server_addr": panel_host,
                "server_port": frp_setting.value.get("port", 7000),
                "token": frp_setting.value.get("token")
            }
        
        return NodeResponse(
            id=existing.id,
            name=existing.name,
            fingerprint=existing.fingerprint,
            status=existing.status,
            registered_at=existing.registered_at,
            last_seen=existing.last_seen,
            metadata=response_metadata
        )
    
    db_node = Node(
        name=node.name,
        fingerprint=fingerprint,
        status="active",
        node_metadata=metadata
    )
    db.add(db_node)
    await db.commit()
    await db.refresh(db_node)
    
    response_metadata = db_node.node_metadata.copy() if db_node.node_metadata else {}
    
    result = await db.execute(select(Settings).where(Settings.key == "frp"))
    frp_setting = result.scalar_one_or_none()
    # Only foreign nodes use the FRP reverse channel (see note in the existing-node branch).
    if frp_setting and frp_setting.value and frp_setting.value.get("enabled") and incoming_role == "foreign":
        panel_host = node.metadata.get("panel_address", "").split(":")[0] if node.metadata else ""
        if not panel_host or panel_host == "panel.example.com":
            import socket
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                panel_host = s.getsockname()[0]
                s.close()
            except:
                panel_host = "127.0.0.1"
        
        response_metadata["frp_config"] = {
            "enabled": True,
            "server_addr": panel_host,
            "server_port": frp_setting.value.get("port", 7000),
            "token": frp_setting.value.get("token")
        }
    
    return NodeResponse(
        id=db_node.id,
        name=db_node.name,
        fingerprint=db_node.fingerprint,
        status=db_node.status,
        registered_at=db_node.registered_at,
        last_seen=db_node.last_seen,
        metadata=response_metadata
    )


@router.get("", response_model=List[NodeResponse], dependencies=[Depends(get_current_user)])
async def list_nodes(db: AsyncSession = Depends(get_db)):
    """List all nodes with connection state"""
    import asyncio
    result = await db.execute(select(Node))
    nodes = result.scalars().all()
    
    client = NodeClient()
    node_responses = []
    
    async def check_node_status(node):
        connection_status = "failed"
        try:
            response = await client.get_tunnel_status(node.id, "")
            if response and response.get("status") == "ok":
                connection_status = "connected"
            else:
                error_msg = response.get("message", "Node disconnected") if response else "Node not responding"
                if "timeout" in error_msg.lower() or "connection" in error_msg.lower():
                    if node.node_metadata and node.node_metadata.get("frp_connected"):
                        connection_status = "connected"
                    else:
                        connection_status = "reconnecting"
                else:
                    connection_status = "failed"
        except httpx.ConnectError:
            if node.node_metadata and node.node_metadata.get("frp_connected"):
                connection_status = "connected"
            else:
                connection_status = "connecting"
        except httpx.TimeoutException:
            if node.node_metadata and node.node_metadata.get("frp_connected"):
                connection_status = "connected"
            else:
                connection_status = "reconnecting"
        except Exception:
            if node.node_metadata and node.node_metadata.get("frp_connected"):
                connection_status = "connected"
            else:
                connection_status = "failed"
        
        metadata = node.node_metadata.copy() if node.node_metadata else {}
        metadata["connection_status"] = connection_status
        
        return NodeResponse(
            id=node.id,
            name=node.name,
            fingerprint=node.fingerprint,
            status=node.status,
            registered_at=node.registered_at,
            last_seen=node.last_seen,
            metadata=metadata
        )
    
    tasks = [check_node_status(node) for node in nodes]
    node_responses = await asyncio.gather(*tasks, return_exceptions=True)
    
    results = []
    for i, response in enumerate(node_responses):
        if isinstance(response, Exception):
            node = nodes[i]
            metadata = node.node_metadata.copy() if node.node_metadata else {}
            metadata["connection_status"] = "failed"
            results.append(NodeResponse(
                id=node.id,
                name=node.name,
                fingerprint=node.fingerprint,
                status=node.status,
                registered_at=node.registered_at,
                last_seen=node.last_seen,
                metadata=metadata
            ))
        else:
            results.append(response)
    
    return results


@router.get("/revoked", dependencies=[Depends(get_current_user)])
async def list_revoked(db: AsyncSession = Depends(get_db)):
    """List fingerprints blocked from re-registering (admin-deleted nodes)."""
    result = await db.execute(select(RevokedNode))
    rows = result.scalars().all()
    return [
        {"fingerprint": r.fingerprint, "name": r.name,
         "revoked_at": r.revoked_at.isoformat() if r.revoked_at else None}
        for r in rows
    ]


@router.delete("/revoked/{fingerprint}", dependencies=[Depends(get_current_user)])
async def clear_revoked(fingerprint: str, db: AsyncSession = Depends(get_db)):
    """Allow a previously-deleted node to enroll again (its agent re-registers within ~60s)."""
    result = await db.execute(select(RevokedNode).where(RevokedNode.fingerprint == fingerprint))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Fingerprint is not revoked")
    await db.delete(row)
    await db.commit()
    return {"status": "cleared"}


@router.get("/{node_id}", response_model=NodeResponse, dependencies=[Depends(get_current_user)])
async def get_node(node_id: str, db: AsyncSession = Depends(get_db)):
    """Get node by ID"""
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return NodeResponse(
        id=node.id,
        name=node.name,
        fingerprint=node.fingerprint,
        status=node.status,
        registered_at=node.registered_at,
        last_seen=node.last_seen,
        metadata=node.node_metadata or {}
    )


@router.put("/{node_id}/frp-status")
async def update_frp_status(node_id: str, frp_status: dict, request: Request, db: AsyncSession = Depends(get_db)):
    """Update node FRP connection status"""
    from sqlalchemy.orm.attributes import flag_modified
    
    # Optional node auth (default OFF): when enforcement is enabled the calling
    # node must present the shared token, preventing frp-status hijacking (H16).
    if _node_auth_enforced():
        _tok = os.environ.get("NODE_API_TOKEN", "")
        if _tok and request.headers.get("x-node-token") != _tok:
            raise HTTPException(status_code=401, detail="Invalid or missing node token")
    
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    
    if not node.node_metadata:
        node.node_metadata = {}
    
    if frp_status.get("connected") and frp_status.get("remote_port"):
        node.node_metadata["frp_remote_port"] = frp_status.get("remote_port")
        node.node_metadata["frp_connected"] = True
        logger.info(f"[FRP] Node {node_id} FRP status updated: remote_port={frp_status.get('remote_port')}")
    else:
        node.node_metadata["frp_connected"] = False
        node.node_metadata.pop("frp_remote_port", None)
        logger.info(f"[FRP] Node {node_id} FRP status cleared")
    
    # Mark JSON column as modified so SQLAlchemy detects the change
    flag_modified(node, "node_metadata")
    
    await db.commit()
    await db.refresh(node)
    return {"status": "success"}


@router.delete("/{node_id}", dependencies=[Depends(get_current_user)])
async def delete_node(node_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a node"""
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    
    # Tombstone the fingerprint so the still-running agent cannot silently
    # re-register the node a minute later.
    existing_rev = await db.execute(
        select(RevokedNode).where(RevokedNode.fingerprint == node.fingerprint)
    )
    if existing_rev.scalar_one_or_none() is None:
        db.add(RevokedNode(fingerprint=node.fingerprint, name=node.name))
    
    await db.delete(node)
    await db.commit()
    return {"status": "deleted"}

