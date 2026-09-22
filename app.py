"""Metrics API and dashboard."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)-12s] %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

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
    # global agent
    # agent = SecureAgent()
    yield


app = FastAPI(
    title="Production Agent",
    version="0.1",
    lifespan=lifespan,
)


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


# Dummy metrics endpoint for testing
@app.get("/metrics", response_class=JSONResponse)
def metrics() -> JSONResponse:
    """Return metrics in JSON format."""
    return JSONResponse(
        {"metrics": {"requests": 100, "errors": 5}},
        headers=NO_CACHE_HEADERS,
    )
