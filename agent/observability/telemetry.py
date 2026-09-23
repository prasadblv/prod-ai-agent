"""OpenTelemetry setup: traces, metrics, and logs.

Configured entirely via standard OTel env vars — see README.md for the list.
With no OTEL_EXPORTER_OTLP_ENDPOINT set, spans/metrics/logs print to the
console so telemetry is visible with zero configuration; point
OTEL_EXPORTER_OTLP_ENDPOINT at a collector (e.g. Jaeger/otel-collector) to
ship it out instead. Every stdlib `logging` record (from any `logging.getLogger(...)`
in the app) is forwarded through the OTel logs pipeline via a `LoggingHandler`
attached to the root logger, in addition to whatever handler `app.py`'s
`logging.basicConfig()` already set up for human-readable console output —
expect each record to appear twice locally when console export is on.
"""

from __future__ import annotations

import logging
import os

from opentelemetry import _logs, metrics, trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, ConsoleLogExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from prometheus_client import start_http_server

log = logging.getLogger("otel")

SERVICE_NAME_DEFAULT = "prod-ai-agent"
SERVICE_VERSION_DEFAULT = "0.1.0"

_initialized = False


def _bool_env(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _headers_from_env(raw: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if not raw:
        return headers
    for pair in raw.split(","):
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        headers[k.strip()] = v.strip()
    return headers


def setup_telemetry() -> None:
    """Initialize the global tracer/meter providers. Safe to call multiple times."""
    global _initialized
    if _initialized:
        return
    _initialized = True

    if _bool_env("OTEL_SDK_DISABLED", False):
        log.info("OpenTelemetry disabled via OTEL_SDK_DISABLED")
        return

    service_name = os.getenv("OTEL_SERVICE_NAME", SERVICE_NAME_DEFAULT)
    environment = os.getenv("OTEL_ENVIRONMENT", "development")
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    headers = _headers_from_env(os.getenv("OTEL_EXPORTER_OTLP_HEADERS"))
    use_console = _bool_env("OTEL_CONSOLE_EXPORTER", endpoint is None)
    sample_ratio = float(os.getenv("OTEL_TRACES_SAMPLER_ARG", "1.0"))

    resource = Resource.create(
        {
            SERVICE_NAME: service_name,
            SERVICE_VERSION: SERVICE_VERSION_DEFAULT,
            "deployment.environment": environment,
        }
    )

    # --- Traces ---
    sampler = ParentBased(TraceIdRatioBased(sample_ratio))
    tracer_provider = TracerProvider(resource=resource, sampler=sampler)
    if endpoint:
        tracer_provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces", headers=headers))
        )
    if use_console:
        tracer_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    # --- Metrics ---
    # No fallback to the generic `endpoint` here (unlike traces/logs): in this
    # deployment it points at Jaeger, which only implements an OTLP *traces*
    # receiver, so periodic metrics exports there 404 every cycle. Metrics are
    # already fully covered by the Prometheus scrape endpoint below, so OTLP
    # metrics export is opt-in only, via the OTel-spec per-signal endpoint
    # (a real metrics-capable OTLP receiver, e.g. an otel-collector).
    readers = []
    metrics_endpoint = os.getenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT")
    if metrics_endpoint:
        readers.append(
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=metrics_endpoint, headers=headers)
            )
        )
    if use_console:
        readers.append(
            PeriodicExportingMetricReader(ConsoleMetricExporter(), export_interval_millis=30_000)
        )

    prometheus_enabled = _bool_env("OTEL_EXPORTER_PROMETHEUS_ENABLED", True)
    if prometheus_enabled:
        readers.append(PrometheusMetricReader())
        prometheus_host = os.getenv("OTEL_EXPORTER_PROMETHEUS_HOST", "0.0.0.0")
        prometheus_port = int(os.getenv("OTEL_EXPORTER_PROMETHEUS_PORT", "9464"))
        start_http_server(port=prometheus_port, addr=prometheus_host)
        log.info(f"Prometheus metrics exposed at http://{prometheus_host}:{prometheus_port}/metrics")

    meter_provider = MeterProvider(resource=resource, metric_readers=readers)
    metrics.set_meter_provider(meter_provider)

    # --- Logs: forward every stdlib `logging` record through OTel too ---
    # OTEL_EXPORTER_OTLP_LOGS_ENDPOINT (the OTel-spec per-signal override) lets
    # logs go to a different collector than traces/metrics — e.g. an
    # otel-collector fronting Elasticsearch — without disturbing the generic
    # OTEL_EXPORTER_OTLP_ENDPOINT other signals still use. Per spec, the
    # per-signal var is a full URL used as-is (no `/v1/logs` appended); the
    # generic one gets the path appended, same as traces/metrics above.
    logs_endpoint_override = os.getenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT")
    if logs_endpoint_override:
        logs_url = logs_endpoint_override
    elif endpoint:
        logs_url = f"{endpoint.rstrip('/')}/v1/logs"
    else:
        logs_url = None

    logger_provider = LoggerProvider(resource=resource)
    if logs_url:
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(OTLPLogExporter(endpoint=logs_url, headers=headers))
        )
    if use_console:
        logger_provider.add_log_record_processor(BatchLogRecordProcessor(ConsoleLogExporter()))
    _logs.set_logger_provider(logger_provider)

    # --- Log correlation + export: injects otelTraceID/otelSpanID into log
    # records, and — since a LoggerProvider is now registered above —
    # LoggingInstrumentor also auto-attaches a LoggingHandler to the root
    # logger that forwards every record through the logs pipeline set up
    # above. Don't additionally call `logging.getLogger().addHandler(...)`
    # here; that would double-export every record.
    LoggingInstrumentor().instrument(set_logging_format=False)

    # --- Outbound HTTP (covers the Anthropic SDK, which is httpx-based) ---
    HTTPXClientInstrumentor().instrument()

    log.info(
        f"OpenTelemetry initialized — service={service_name} env={environment} "
        f"otlp_endpoint={endpoint or 'none'} console={use_console}"
    )


def shutdown_telemetry() -> None:
    """Flush and shut down the tracer/meter/logger providers."""
    tp = trace.get_tracer_provider()
    if hasattr(tp, "shutdown"):
        tp.shutdown()
    mp = metrics.get_meter_provider()
    if hasattr(mp, "shutdown"):
        mp.shutdown()
    lp = _logs.get_logger_provider()
    if hasattr(lp, "shutdown"):
        lp.shutdown()


def instrument_fastapi_app(app) -> None:
    """Attach ASGI-level request spans to a FastAPI app instance."""
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)


# Module-level tracer/meter: these are proxies that bind to the real
# providers once setup_telemetry() runs, so importing them before app
# startup (as agent.py / llm.py do) is safe.
tracer = trace.get_tracer(SERVICE_NAME_DEFAULT)
meter = metrics.get_meter(SERVICE_NAME_DEFAULT)

request_counter = meter.create_counter(
    "agent.requests.total", unit="1", description="Agent requests by status/label"
)
token_counter = meter.create_counter(
    "agent.tokens.total", unit="{token}", description="LLM tokens consumed"
)
cost_counter = meter.create_counter(
    "agent.cost_usd.total", unit="usd", description="Estimated LLM cost in USD"
)
latency_histogram = meter.create_histogram(
    "agent.request.duration", unit="ms", description="Agent request latency"
)
