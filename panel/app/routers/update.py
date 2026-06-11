"""Panel self-update API (GitHub releases via foreign-node relay)"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.update_manager import update_manager, DEFAULT_REPO, panel_runtime

router = APIRouter()
logger = logging.getLogger(__name__)


class UpdateStartRequest(BaseModel):
    tag: str
    repo: str | None = None


@router.get("/releases")
async def list_releases(repo: str = "", limit: int = 10):
    """List GitHub releases through a foreign node (the panel has no GitHub access)."""
    try:
        result = await update_manager.list_releases(repo=repo, limit=limit)
        result["repo"] = repo or DEFAULT_REPO
        result["panel_runtime"] = panel_runtime()
        return result
    except Exception as e:
        logger.error(f"Failed to list releases: {e}")
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/start")
async def start_update(payload: UpdateStartRequest):
    """Start updating all nodes + the panel itself to the given release tag."""
    if not payload.tag:
        raise HTTPException(status_code=400, detail="Release tag is required")
    try:
        return await update_manager.start(payload.tag, repo=payload.repo or "")
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/status")
async def update_status():
    """Per-node + panel progress of the current/last update run."""
    return await update_manager.get_status()
