"""Metrics API and dashboard."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from agent.agent import Agent
from agent.metrics.metrics import METRICS
from agent.observability.telemetry import instrument_fastapi_app, setup_telemetry, shutdown_telemetry
from agent.types.types import SecurityContext

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)-12s] %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


agent: Agent | None = None


NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}

DASHBOARD_PATH = Path(__file__).parent / "dashboard.html"
try:
    DASHBOARD_HTML = DASHBOARD_PATH.read_text()
except OSError:
    logger.exception("Failed to read dashboard HTML from %s", DASHBOARD_PATH)
    raise RuntimeError(f"Could not load dashboard template at {DASHBOARD_PATH}") from None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global agent
    setup_telemetry()
    agent = Agent()
    yield
    shutdown_telemetry()


app = FastAPI(
    title="Production Agent",
    version="0.1",
    lifespan=lifespan,
)
instrument_fastapi_app(app)


class ChatBody(BaseModel):
    """Class representing chat body."""
    prompt: str = Field(min_length=1, max_length=8000)
    user_id: str = "User: "
    session_id: str = "Session: "
    permissions: list[str] = Field(default_factory=lambda: ["read"])
    label: str = "Api"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy", "service": "prod-agent"}


@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    return HTMLResponse(DASHBOARD_HTML, headers=NO_CACHE_HEADERS)

@app.post("/chat")
def chat(body: ChatBody)-> dict[str,Any]:
    if agent is None:
        raise HTTPException(status_code=503,detail="Agent not ready!")
    ctx = SecurityContext(
        user_id=body.user_id,
        session_id=body.session_id,
        permissions=body.permissions,
    )
    try:
        resp = agent.run(input=body.prompt,ctx=ctx,label=body.label)
        return {
            "status": "ok",
            "content": resp.content,
            "tokens_used": resp.tokens_used,
            "cost_usd": resp.cost_usd,
            "latency_ms": resp.latency_ms,
            "layer_timings": resp.layer_timings,
            "request_id": resp.request_id,
        }
    except PermissionError as e:
        return {"status": "blocked", "content": str(e)}
    except ValueError as e:
        return {"status": "rejected", "content": str(e)}
    
DEMO_STEPS = [
    ("NORMAL", "Explain the 4-layer agent architecture."),
]

@app.post("/demo")
def run_demo() -> dict[str, Any]:
    if agent is None:
        raise HTTPException(status_code=503, detail="Agent not ready")
    ctx = SecurityContext(
        user_id="demo-user",
        session_id="session_demo",
        permissions=["read"],
        rate_limit_tier="standard",
    )
    results: list[dict[str,Any]] = []
    for label, prompt in DEMO_STEPS:
        try:
            resp = agent.run(input=prompt,ctx=ctx,label=label)
            results.append({
                "label": label,
                "status": "ok",
                "content": resp.content,
                "tokens_used": resp.tokens_used,
                "cost_usd": resp.cost_usd,
                "latency_ms": resp.latency_ms,
            })
        except PermissionError as e:
            results.append({"label": label, "status": "blocked", "content": str(e)})
        except ValueError as e:
            results.append({"label": label, "status": "rejected", "content": str(e)})
    METRICS.bump_demo()
    snap = METRICS.snapshot()
    return {"results": results, "metrics": snap}

@app.get("/metrics", response_class=JSONResponse)
def metrics() -> JSONResponse:
    """Return metrics in JSON format."""
    return JSONResponse(METRICS.snapshot(), headers=NO_CACHE_HEADERS)
