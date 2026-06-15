"""
Loki Node - Lightweight Agent
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import agent
from app.panel_client import PanelClient
from app.core_adapters import AdapterManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Optional node-API authentication. Default OFF so existing panels keep working
# unchanged. To harden (after every node is updated): set NODE_API_TOKEN to a
# shared secret and NODE_AUTH_ENFORCE=1 on both the panel and the nodes. This is
# the "flip enforcement on" step of the staged rollout.
NODE_API_TOKEN = os.environ.get("NODE_API_TOKEN", "")
NODE_AUTH_ENFORCE = os.environ.get("NODE_AUTH_ENFORCE", "").strip().lower() in ("1", "true", "yes", "on")


async def require_node_token(x_node_token: str = Header(default="")):
    """Gate agent endpoints behind a shared token, but only when enforcement is on."""
    if NODE_AUTH_ENFORCE and NODE_API_TOKEN and x_node_token != NODE_API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing node token")
    return True


async def registration_loop(panel_client: PanelClient):
    """Periodic registration loop to pick up FRP config changes"""
    while True:
        try:
            await asyncio.sleep(60)  # Re-register every 60 seconds
            if panel_client and panel_client.client:
                await panel_client.register_with_panel()
                if getattr(panel_client, "blocked", False):
                    logger.error("Node revoked by panel; stopping periodic re-registration.")
                    break
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug(f"Periodic registration error (will retry): {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    h2_client = PanelClient()
    registration_task = None
    try:
        await h2_client.start()
        app.state.h2_client = h2_client
        
        try:
            await h2_client.register_with_panel()
        except Exception as e:
            logger.warning(f"Could not register with panel: {e}")
            logger.warning("Node will continue running but manual registration may be needed")
        
        registration_task = asyncio.create_task(registration_loop(h2_client))
        app.state.registration_task = registration_task
    except Exception as e:
        logger.error(f"Failed to start Panel client: {e}")
        logger.error("Node API will still be available, but panel connection will not work")
        logger.error("Make sure CA certificate is available at the configured path")
        app.state.h2_client = None
    
    adapter_manager = AdapterManager()
    app.state.adapter_manager = adapter_manager
    
    try:
        await adapter_manager.restore_tunnels()
    except Exception as e:
        logger.error(f"Failed to restore tunnels on startup: {e}", exc_info=True)
    
    yield
    if hasattr(app.state, 'registration_task') and app.state.registration_task:
        app.state.registration_task.cancel()
        try:
            await app.state.registration_task
        except asyncio.CancelledError:
            pass
    if hasattr(app.state, 'h2_client') and app.state.h2_client:
        try:
            await app.state.h2_client.stop()
        except:
            pass
    if hasattr(app.state, 'adapter_manager'):
        await app.state.adapter_manager.cleanup()


app = FastAPI(
    title="Loki Node",
    description="Lightweight Tunnel Agent",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(agent.router, prefix="/api/agent", tags=["agent"], dependencies=[Depends(require_node_token)])


@app.get("/")
async def root():
    return {"status": "ok", "service": "smite-node"}


if __name__ == "__main__":
    import uvicorn
    try:
        uvicorn.run(app, host="0.0.0.0", port=settings.node_api_port)
    except Exception as e:
        logger.error(f"Failed to start server: {e}", exc_info=True)
        raise

