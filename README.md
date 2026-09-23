# prod-ai-agent
prod-ai-agent

## Observability (OpenTelemetry)

Traces and metrics are instrumented with OpenTelemetry. `agent.run` and `llm.call`
each produce a span (tokens, cost, latency, `gen_ai.*` attributes on the LLM
span), inbound FastAPI requests and outbound HTTP calls (the Anthropic SDK,
which is httpx-based) are auto-instrumented, and log lines are tagged with
`otelTraceID`/`otelSpanID` for correlation.

With no configuration, telemetry prints to the console — zero setup needed
for local dev. Point it at a collector to ship telemetry elsewhere:

| Env var | Default | Purpose |
|---|---|---|
| `OTEL_SERVICE_NAME` | `prod-ai-agent` | Service name on the resource |
| `OTEL_ENVIRONMENT` | `development` | `deployment.environment` resource attribute |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | Base URL of an OTLP/HTTP collector, e.g. `http://localhost:4318` |
| `OTEL_EXPORTER_OTLP_HEADERS` | unset | Comma-separated `key=value` pairs sent with exports |
| `OTEL_CONSOLE_EXPORTER` | `true` if no OTLP endpoint set | Force console export on/off alongside OTLP |
| `OTEL_TRACES_SAMPLER_ARG` | `1.0` | Trace sampling ratio (0.0–1.0) |
| `OTEL_SDK_DISABLED` | `false` | Set `true` to fully disable telemetry |

Run a local Jaeger instance to view traces:

```bash
docker run --rm -p 16686:16686 -p 4318:4318 jaegertracing/all-in-one:latest
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 ./start.sh
```

Then open http://localhost:16686 and select the `prod-ai-agent` service.
