"""OpenTelemetry setup: traces, metrics, and log correlation.

Configured entirely via standard OTel env vars — see README.md for the list.
With no OTEL_EXPORTER_OTLP_ENDPOINT set, spans/metrics print to the console
so telemetry is visible with zero configuration; point
OTEL_EXPORTER_OTLP_ENDPOINT at a collector (e.g. Jaeger/otel-collector) to
ship it out instead.
"""

from __future__ import annotations

import logging
import os

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

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
    readers = []
    if endpoint:
        readers.append(
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=f"{endpoint.rstrip('/')}/v1/metrics", headers=headers)
            )
        )
    if use_console:
        readers.append(
            PeriodicExportingMetricReader(ConsoleMetricExporter(), export_interval_millis=30_000)
        )
    meter_provider = MeterProvider(resource=resource, metric_readers=readers)
    metrics.set_meter_provider(meter_provider)

    # --- Log correlation: injects otelTraceID/otelSpanID into log records ---
    LoggingInstrumentor().instrument(set_logging_format=False)

    # --- Outbound HTTP (covers the Anthropic SDK, which is httpx-based) ---
    HTTPXClientInstrumentor().instrument()

    log.info(
        f"OpenTelemetry initialized — service={service_name} env={environment} "
        f"otlp_endpoint={endpoint or 'none'} console={use_console}"
    )


def shutdown_telemetry() -> None:
    """Flush and shut down the tracer/meter providers."""
    tp = trace.get_tracer_provider()
    if hasattr(tp, "shutdown"):
        tp.shutdown()
    mp = metrics.get_meter_provider()
    if hasattr(mp, "shutdown"):
        mp.shutdown()


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
