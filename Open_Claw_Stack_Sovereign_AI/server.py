"""
Open Claw Stack — FastAPI WebSocket Server
============================================
Serves the real-time dashboard and REST API.

Endpoints:
  GET  /           → Serve dashboard (index.html)
  GET  /status     → Current system state (JSON)
  POST /task       → Submit a new task to the Supervisor
  GET  /report     → Latest final report
  GET  /execwall   → Execwall audit log
  WS   /ws         → Real-time state updates (version-polled)

Architecture:
  - Task execution runs in a ThreadPoolExecutor (non-blocking)
  - WebSocket handler polls SharedState.version every 200ms
  - State changes broadcast to ALL connected clients simultaneously
"""
import asyncio
import json
import logging
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Set

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ── Path setup ──────────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from core.state import SharedState
from core.execwall import Execwall

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("open_claw.server")

# ── Globals (injected from main.py) ─────────────
shared_state: SharedState  = None
execwall:     Execwall     = None
supervisor                 = None          # SupervisorAgent instance
executor = ThreadPoolExecutor(max_workers=4)

# ── FastAPI App ──────────────────────────────────
app = FastAPI(
    title="Open Claw Stack",
    description="Sovereign AI Multi-Agent System",
    version="1.0.0",
)

# Static files (dashboard)
DASH_DIR = ROOT / "dashboard"
if DASH_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(DASH_DIR)), name="static")

# Active WebSocket connections
_connections: Set[WebSocket] = set()
_connections_lock = threading.Lock()


# ════════════════════════════════════════════════
# HTTP Routes
# ════════════════════════════════════════════════

@app.get("/")
async def serve_dashboard():
    index = DASH_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return JSONResponse({"error": "Dashboard not found"}, status_code=404)


@app.get("/status")
async def get_status():
    """Return full system state as JSON."""
    return JSONResponse(shared_state.to_dict())


@app.get("/report")
async def get_report():
    """Return the latest final report."""
    return JSONResponse({
        "report":       shared_state.final_report,
        "current_task": shared_state.current_task,
        "pra_phase":    shared_state.pra_phase,
    })


@app.get("/execwall")
async def get_execwall():
    """Return Execwall audit summary."""
    return JSONResponse(execwall.get_audit_summary())


@app.post("/task")
async def submit_task(body: dict):
    """
    Submit a new task to the Supervisor Agent.
    Body: {"task": "The network is slow..."}
    """
    task = (body.get("task") or "").strip()
    if not task:
        return JSONResponse({"error": "task field is required"}, status_code=400)

    if supervisor is None:
        return JSONResponse({"error": "Supervisor not initialized"}, status_code=503)

    # Check if a task is already running
    if shared_state.pra_phase not in ("idle", "done", ""):
        return JSONResponse({"error": "A task is already in progress"}, status_code=429)

    # Reset state and dispatch in background thread
    shared_state.reset()
    loop = asyncio.get_event_loop()

    def run_task():
        try:
            supervisor.run(task)
        except Exception as exc:
            logger.error(f"Task error: {exc}", exc_info=True)
            shared_state.add_message("system", f"❌ Task failed: {exc}", "system")

    executor.submit(run_task)

    return JSONResponse({"status": "accepted", "task": task})


@app.post("/reset")
async def reset_state():
    """Reset the system state."""
    shared_state.reset()
    return JSONResponse({"status": "reset"})


# ════════════════════════════════════════════════
# WebSocket
# ════════════════════════════════════════════════

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    with _connections_lock:
        _connections.add(ws)
    logger.info(f"WebSocket connected: {ws.client}")

    last_version = -1
    try:
        # Send initial state immediately
        await ws.send_json(shared_state.to_dict())
        last_version = shared_state.version

        while True:
            current = shared_state.version
            if current != last_version:
                data         = shared_state.to_dict()
                last_version = current
                await ws.send_json(data)
            await asyncio.sleep(0.2)   # 200ms poll — good balance of responsiveness

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as exc:
        logger.warning(f"WebSocket error: {exc}")
    finally:
        with _connections_lock:
            _connections.discard(ws)


# ════════════════════════════════════════════════
# Server Factory
# ════════════════════════════════════════════════

def create_server(host: str = "localhost", port: int = 8765) -> uvicorn.Server:
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
    )
    return uvicorn.Server(config)
