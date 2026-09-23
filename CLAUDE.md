# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Dependencies live in `.venv`, which was created **without** a `pip` executable in `.venv/bin` — plain `pip install` installs into the system/Framework Python instead of the venv. Always invoke pip as a module:

```bash
./.venv/bin/python3 -m pip install -r requirements.txt
```

Run the server:
```bash
./start.sh              # reads .env, refuses to start if an "uvicorn app:app" process is already running, backgrounds uvicorn on $PORT (default 8080)
./stop.sh                # pkills the "uvicorn app:app" process
# or directly:
./.venv/bin/python3 -m uvicorn app:app --host 127.0.0.1 --port 8080
```
- Dashboard: `http://127.0.0.1:8080/dashboard` (also served at `/`)
- Health check: `/health`

Run the CLI demo (no HTTP server) instead of the API:
```bash
./.venv/bin/python3 main.py
```

Tests:
```bash
./.venv/bin/python3 -m pytest
./.venv/bin/python3 -m pytest tests/test_agent_metrics.py -k test_records_ok_in_metrics  # single test
```
No pytest config file exists — defaults apply (`tests/` dir, `test_*.py` files). `tests/conftest.py` has shared fixtures (`security_context`, `fresh_metric_store`); `Agent`/`LLM` are tested with mocked dependencies (`Agent.llm` mocked directly, `anthropic.Anthropic` patched) rather than hitting the network — there's no live-API test mode.

## Environment variables

- `ANTHROPIC_API_KEY` — if unset, `LLM` runs in stub mode (canned response, fake token counts, no network call). Set it to exercise the real Anthropic call path.
- `ANTHROPIC_MODEL` — defaults to `claude-sonnet-5`.
- `PORT` — used by `start.sh` (default `8080`).
- `OTEL_*` — see the Observability section of README.md (service name, OTLP endpoint, sampling, etc.). With no `OTEL_EXPORTER_OTLP_ENDPOINT` set, traces/metrics print to the console by default.

## Architecture

**Request flow:** `app.py` (FastAPI) → `agent/agent.py::Agent.run()` → `agent/llm/llm.py::LLM.call()`. `Agent.run` builds an `AgentRequest` (from `agent/types/types.py`), calls the LLM layer, and on success/`PermissionError`/`ValueError` records to two independent, parallel systems every time — don't update one without the other:
1. `agent.metrics.metrics.METRICS` (`agent/metrics/metrics.py`) — an in-process, lock-protected singleton whose `.snapshot()` dict shape is consumed directly by `dashboard.html`'s JS (`render(d)` reads `d.requests_total`, `d.recent_events`, etc.) and served verbatim by `GET /metrics`. If you change the dict's keys, update `dashboard.html` too.
2. OpenTelemetry spans/metrics via `agent/observability/telemetry.py` (see below).

**The "4-layer" architecture is partially aspirational.** `layer_timings` in `Agent.run` hardcodes `l4_security_ms` and `l2_memory_ms` to `0` — `agent/security/` and `agent/tool/` are empty stub packages, and `agent/memory/memory.py` (`InMemoryStore`) exists but is never called from `Agent.run`. Only the L1 LLM layer is actually wired up. Don't assume security/memory/tool enforcement exists just because the types or directory structure imply it.

**Stub vs. real LLM mode:** `LLM.__init__` checks `bool(os.getenv("ANTHROPIC_API_KEY"))` once at construction and sets `self._use_real_llm`; there is no per-request override. In real mode, exceptions from the Anthropic client (`APIConnectionError`, `RateLimitError`, `APIStatusError`) are logged, recorded on the OTel span, and re-raised — they are *not* `PermissionError`/`ValueError`, so they propagate past `Agent.run`'s except clauses and surface as unhandled 500s in `app.py`'s `/chat` and `/demo` handlers.

**Observability (`agent/observability/telemetry.py`):** `tracer`/`meter` and the metric instruments (`request_counter`, `token_counter`, `cost_counter`, `latency_histogram`) are created at import time as OTel proxy objects — safe to import in `agent.py`/`llm.py` before `setup_telemetry()` has actually run. `setup_telemetry()` itself is called once, from `app.py`'s FastAPI `lifespan` (HTTP mode) or from `main.py::main()` (CLI mode); it's idempotent (`_initialized` guard). FastAPI instrumentation (`instrument_fastapi_app`) is applied at module import time in `app.py`, outside the lifespan.

**Types (`agent/types/types.py`):** native `pydantic` v2 `BaseModel`s (`AgentRole`, `SecurityContext`, `AgentRequest`, `AgentResponse`). No `Config`/`model_config` is set on any of them, so they're mutable after construction — `Agent.run` relies on this, setting `response.layer_timings` and `response.status` post-hoc after `LLM.call()` returns. `app.py`'s `ChatBody` is a separate, unrelated `pydantic` model used only for the FastAPI request body; none of the 4 types above are ever used as a FastAPI request/response model directly.

**`dashboard.html`** is a single static file with inline CSS/JS (no build step) — `app.py` reads it once at import time from disk (`DASHBOARD_PATH.read_text()`) and serves the cached string; a change to the file requires restarting the server to take effect. It polls `GET /metrics` every second and posts to `POST /demo` to trigger a canned request.
