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
- `OTEL_*` — see the Observability section of README.md (service name, OTLP endpoint, sampling, etc.). With no `OTEL_EXPORTER_OTLP_ENDPOINT` set, traces/metrics print to the console by default. `OTEL_EXPORTER_PROMETHEUS_ENABLED` (default `true`) additionally starts a `prometheus_client` HTTP server (`OTEL_EXPORTER_PROMETHEUS_HOST`/`_PORT`, default `0.0.0.0:9464`) exposing the same OTel metric instruments in Prometheus text format — this runs alongside, not instead of, the OTLP/console readers.

## Architecture

**Request flow:** `app.py` (FastAPI) → `agent/agent.py::Agent.run()` → `agent/llm/llm.py::LLM.call()`. `Agent.run` builds an `AgentRequest` (from `agent/types/types.py`), calls the LLM layer, and on success/`PermissionError`/`ValueError` records to two independent, parallel systems every time — don't update one without the other:
1. `agent.metrics.metrics.METRICS` (`agent/metrics/metrics.py`) — an in-process, lock-protected singleton whose `.snapshot()` dict shape is consumed directly by `dashboard.html`'s JS (`render(d)` reads `d.requests_total`, `d.recent_events`, etc.) and served verbatim by FastAPI's `GET /metrics` on port 8080 (JSON). If you change the dict's keys, update `dashboard.html` too.
2. OpenTelemetry spans/metrics via `agent/observability/telemetry.py` (see below) — `request_counter`/`token_counter`/`cost_counter`/`latency_histogram`, exported to the console and (by default) as Prometheus text format on a *separate* port 9464 `GET /metrics`. Two unrelated `/metrics` endpoints exist on different ports — don't conflate them. OTLP metrics export is opt-in only (`OTEL_EXPORTER_OTLP_METRICS_ENDPOINT`), not automatic — see the Observability note below for why.

**The "4-layer" architecture is partially aspirational.** `layer_timings` in `Agent.run` hardcodes `l4_security_ms` and `l2_memory_ms` to `0` — `agent/security/` and `agent/tool/` are empty stub packages, and `agent/memory/memory.py` (`InMemoryStore`) exists but is never called from `Agent.run`. Only the L1 LLM layer is actually wired up. Don't assume security/memory/tool enforcement exists just because the types or directory structure imply it.

**Stub vs. real LLM mode:** `LLM.__init__` checks `bool(os.getenv("ANTHROPIC_API_KEY"))` once at construction and sets `self._use_real_llm`; there is no per-request override. In real mode, exceptions from the Anthropic client (`APIConnectionError`, `RateLimitError`, `APIStatusError`) are logged, recorded on the OTel span, and re-raised — they are *not* `PermissionError`/`ValueError`, so they propagate past `Agent.run`'s except clauses and surface as unhandled 500s in `app.py`'s `/chat` and `/demo` handlers.

**Observability (`agent/observability/telemetry.py`):** `tracer`/`meter` and the metric instruments (`request_counter`, `token_counter`, `cost_counter`, `latency_histogram`) are created at import time as OTel proxy objects — safe to import in `agent.py`/`llm.py` before `setup_telemetry()` has actually run. `setup_telemetry()` itself is called once, from `app.py`'s FastAPI `lifespan` (HTTP mode) or from `main.py::main()` (CLI mode); it's idempotent (`_initialized` guard). FastAPI instrumentation (`instrument_fastapi_app`) is applied at module import time in `app.py`, outside the lifespan.

Logs are also exported through OTel: `setup_telemetry()` registers a `LoggerProvider` via `_logs.set_logger_provider()` *before* calling `LoggingInstrumentor().instrument(...)` — that ordering matters, because `LoggingInstrumentor` auto-attaches its own `LoggingHandler` to the root logger the moment a provider is already registered. Don't also manually `logging.getLogger().addHandler(LoggingHandler(...))`; that double-exports every record (confirmed while building this — see git history). Every `logging.getLogger(...)` call in the app propagates to root, so every record is forwarded, tagged with `trace_id`/`span_id` when emitted inside an active span. `main.py` never calls `logging.basicConfig()`, so in CLI mode the root logger stays at the default `WARNING` level and `INFO` logs (including from `otel`/`agent`/`llm`) are silently dropped before they ever reach a handler — this predates the logs work, not a regression from it. `app.py` does call `basicConfig(level=INFO)`, so HTTP mode gets both the human-readable console line and the OTel-forwarded copy.

Logs can be routed to a *different* OTLP endpoint than traces via `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` (the OTel-spec per-signal override — used as a full URL as-is, unlike the generic `OTEL_EXPORTER_OTLP_ENDPOINT` which gets `/v1/logs`/`/v1/traces` appended). `docker-compose.yml` uses this to send logs to `otel-collector` → Elasticsearch while traces still go straight to the `otel` (Jaeger) service — the app has no Elasticsearch-specific code or dependency; it only ever speaks OTLP. The collector (`otel-collector-config.yaml`) needs the **contrib** image (`otel/opentelemetry-collector-contrib`, not the core one) for the `elasticsearch` exporter to exist at all. Its logs pipeline deliberately has no traces/metrics receivers wired — don't add `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318` (the generic one) expecting it to also carry traces, that pipeline doesn't exist in the collector config. Also: do **not** set the exporter's `logs_index` to a plain custom name — ES doesn't auto-create plain indices on first write (confirmed: caused a 404 `index_not_found_exception` loop). Leaving it unset makes the exporter default to the `logs-generic.otel-default` **data stream**, which ES 8.x auto-creates via its built-in `logs-*-*` index template.

**Metrics do NOT go to the generic `OTEL_EXPORTER_OTLP_ENDPOINT` by default** — this used to be automatic (`if endpoint: readers.append(PeriodicExportingMetricReader(OTLPMetricExporter(...)))`), but Jaeger's all-in-one (the `otel` service that endpoint points at) never implemented an OTLP metrics receiver, so every periodic export 404'd (`Failed to export metrics batch code: 404, reason: Not Found`, confirmed in logs — silent otherwise since it only surfaced once logs export started working and the SDK's own error log became visible/shippable). Fixed by making OTLP metrics export opt-in only via `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` (no fallback to the generic endpoint, unlike traces/logs) — metrics are already fully covered by the Prometheus scrape endpoint, so nothing sets this var today. If you ever add a real OTLP metrics receiver (e.g. wire a metrics pipeline into `otel-collector-config.yaml`), point this var at it rather than re-adding the generic-endpoint fallback.

**`grafana` (`docker-compose.yml`)** is a dashboarding UI over the `prometheus` service — no independent role in the app's telemetry pipeline, and nothing depends on it (same relationship `kibana` has to `elasticsearch`). Its Prometheus data source is file-provisioned via `grafana/provisioning/datasources/prometheus.yml` (mounted read-only into `/etc/grafana/provisioning`), not clicked together in the UI — confirmed working end-to-end (queried real `up`/`agent_requests_total` series through Grafana's own `/api/ds/query`, not just that the data source object exists). If you add more provisioned resources (dashboards, alerts), they go under `grafana/provisioning/<kind>/` following the same pattern — Grafana auto-discovers everything under the mounted `/etc/grafana/provisioning` tree.

`docker-compose.yml` also runs a `kibana` service against the same `elasticsearch` service (pointed at it via `ELASTICSEARCH_HOSTS`, no auth needed since `xpack.security.enabled=false`) purely as a UI for browsing what's already in ES — it has no independent config file and isn't in the app's data path; nothing depends on it and the app would work identically if it were removed.

**Types (`agent/types/types.py`):** native `pydantic` v2 `BaseModel`s (`AgentRole`, `SecurityContext`, `AgentRequest`, `AgentResponse`). No `Config`/`model_config` is set on any of them, so they're mutable after construction — `Agent.run` relies on this, setting `response.layer_timings` and `response.status` post-hoc after `LLM.call()` returns. `app.py`'s `ChatBody` is a separate, unrelated `pydantic` model used only for the FastAPI request body; none of the 4 types above are ever used as a FastAPI request/response model directly.

**`dashboard.html`** is a single static file with inline CSS/JS (no build step) — `app.py` reads it once at import time from disk (`DASHBOARD_PATH.read_text()`) and serves the cached string; a change to the file requires restarting the server to take effect. It polls `GET /metrics` every 10 seconds and posts to `POST /demo` to trigger a canned request.
