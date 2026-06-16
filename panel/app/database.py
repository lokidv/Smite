"""Database setup and session management"""
import os
import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import text
from app.config import settings

Base = declarative_base()

if settings.db_type == "sqlite":
    db_url = f"sqlite+aiosqlite:///{settings.db_path}"
else:
    raise ValueError(f"Unsupported DB type: {settings.db_type}")

engine = create_async_engine(db_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

logger = logging.getLogger(__name__)


async def migrate_db():
    """Migrate database schema - add missing columns"""
    if settings.db_type != "sqlite":
        return
    
    async with engine.begin() as conn:
        result = await conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tunnels'"
        ))
        if not result.scalar():
            return
        
        result = await conn.execute(text(
            "PRAGMA table_info(tunnels)"
        ))
        columns = [row[1] for row in result.fetchall()]
        
        if "foreign_node_id" not in columns:
            logger.info("Adding foreign_node_id column to tunnels table")
            await conn.execute(text(
                "ALTER TABLE tunnels ADD COLUMN foreign_node_id VARCHAR"
            ))
        
        if "iran_node_id" not in columns:
            logger.info("Adding iran_node_id column to tunnels table")
            await conn.execute(text(
                "ALTER TABLE tunnels ADD COLUMN iran_node_id VARCHAR"
            ))

        # Real-time health columns (separate from the configured `status`).
        if "health" not in columns:
            logger.info("Adding health column to tunnels table")
            await conn.execute(text(
                "ALTER TABLE tunnels ADD COLUMN health VARCHAR DEFAULT 'unknown'"
            ))
        if "health_detail" not in columns:
            logger.info("Adding health_detail column to tunnels table")
            await conn.execute(text(
                "ALTER TABLE tunnels ADD COLUMN health_detail TEXT"
            ))
        if "health_checked_at" not in columns:
            logger.info("Adding health_checked_at column to tunnels table")
            await conn.execute(text(
                "ALTER TABLE tunnels ADD COLUMN health_checked_at DATETIME"
            ))


async def init_db():
    """Initialize database tables"""
    if settings.db_type == "sqlite":
        os.makedirs(os.path.dirname(settings.db_path), exist_ok=True)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Run migrations after creating tables
    await migrate_db()


async def get_db():
    """Database session dependency"""
    async with AsyncSessionLocal() as session:
        yield session

