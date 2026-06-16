"""Database models"""
from sqlalchemy import Column, String, Integer, DateTime, Float, JSON, Boolean, Text
from sqlalchemy.dialects.sqlite import DATETIME as SQLiteDATETIME
from datetime import datetime
from app.database import Base
import uuid


def generate_uuid():
    return str(uuid.uuid4())


class Node(Base):
    __tablename__ = "nodes"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    fingerprint = Column(String, unique=True, nullable=False)
    status = Column(String, default="pending")
    registered_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    node_metadata = Column("metadata", JSON, default=dict)
    

class Tunnel(Base):
    __tablename__ = "tunnels"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    core = Column(String, nullable=False)
    type = Column(String, nullable=False)
    node_id = Column(String, nullable=False)
    foreign_node_id = Column(String, nullable=True)  # For reverse tunnels: foreign node (server side)
    iran_node_id = Column(String, nullable=True)  # For reverse tunnels: iran node (client side)
    spec = Column(JSON, nullable=False)
    quota_mb = Column(Float, default=0)
    used_mb = Column(Float, default=0)
    expires_at = Column(DateTime, nullable=True)
    status = Column(String, default="pending")  # configured/desired state: pending|active|error
    error_message = Column(Text, nullable=True)
    # Real-time, monitor-derived link state (separate from the configured status):
    # healthy|connecting|disconnected|degraded|node_offline|conflict|stopped|unknown
    health = Column(String, default="unknown")
    health_detail = Column(Text, nullable=True)
    health_checked_at = Column(DateTime, nullable=True)
    revision = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Admin(Base):
    __tablename__ = "admins"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Usage(Base):
    __tablename__ = "usage"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    tunnel_id = Column(String, nullable=False)
    node_id = Column(String, nullable=False)
    bytes_used = Column(Integer, default=0)
    timestamp = Column(DateTime, default=datetime.utcnow)


class CoreResetConfig(Base):
    __tablename__ = "core_reset_config"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    core = Column(String, nullable=False, unique=True)
    enabled = Column(Boolean, default=False)
    interval_minutes = Column(Integer, default=10)
    last_reset = Column(DateTime, nullable=True)
    next_reset = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Settings(Base):
    __tablename__ = "settings"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    key = Column(String, unique=True, nullable=False)
    value = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RevokedNode(Base):
    """Fingerprints of nodes an admin deleted.

    The node agent keeps re-registering every 60s, so without this tombstone a
    deleted node silently reappears. Register rejects revoked fingerprints; an
    admin can clear the entry to allow a server to enroll again.
    """
    __tablename__ = "revoked_nodes"

    fingerprint = Column(String, primary_key=True)
    name = Column(String, nullable=True)
    revoked_at = Column(DateTime, default=datetime.utcnow)


class NodeProblem(Base):
    """A detected health problem for a node/tunnel, surfaced in the panel.

    The health monitor records issues here (orphan/conflict/disconnected/
    node_offline/process_dead/port_conflict/...) and what it did to auto-heal
    them. Rows are deduplicated by (node_id, tunnel_id, kind): a recurring issue
    bumps ``occurrences`` and ``last_seen`` instead of creating duplicates.
    """
    __tablename__ = "node_problems"

    id = Column(String, primary_key=True, default=generate_uuid)
    node_id = Column(String, nullable=True)
    tunnel_id = Column(String, nullable=True)
    kind = Column(String, nullable=False)
    severity = Column(String, default="warning")  # info|warning|critical
    message = Column(Text, nullable=False)
    detail = Column(JSON, nullable=True)
    status = Column(String, default="open")  # open|auto_resolved|resolved
    auto_heal_action = Column(String, nullable=True)
    auto_heal_result = Column(String, nullable=True)
    occurrences = Column(Integer, default=1)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

