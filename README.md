# prod-ai-agent
prod-ai-agent

## Observability (OpenTelemetry)

Traces, metrics, and logs are all instrumented with OpenTelemetry. `agent.run` and
`llm.call` each produce a span (tokens, cost, latency, `gen_ai.*` attributes on the
LLM span), inbound FastAPI requests and outbound HTTP calls (the Anthropic SDK,
which is httpx-based) are auto-instrumented, and every `logging` record from the
app (`agent`, `llm`, `otel`, etc. loggers) is forwarded through the OTel logs
pipeline — tagged with `trace_id`/`span_id` when emitted inside an active span —
alongside the human-readable console line from `logging.basicConfig()`.

With no configuration, telemetry prints to the console — zero setup needed
for local dev. Point it at a collector to ship telemetry elsewhere:

| Env var | Default | Purpose |
|---|---|---|
| `OTEL_SERVICE_NAME` | `prod-ai-agent` | Service name on the resource |
| `OTEL_ENVIRONMENT` | `development` | `deployment.environment` resource attribute |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | Base URL of an OTLP/HTTP collector for **traces**, e.g. `http://localhost:4318` — Jaeger's all-in-one (the `otel` compose service) only implements an OTLP traces receiver, so this is traces-only in this deployment; don't expect it to also carry metrics |
| `OTEL_EXPORTER_OTLP_HEADERS` | unset | Comma-separated `key=value` pairs sent with exports |
| `OTEL_CONSOLE_EXPORTER` | `true` if no OTLP endpoint set | Force console export on/off alongside OTLP |
| `OTEL_TRACES_SAMPLER_ARG` | `1.0` | Trace sampling ratio (0.0–1.0) |
| `OTEL_SDK_DISABLED` | `false` | Set `true` to fully disable telemetry |
| `OTEL_EXPORTER_PROMETHEUS_ENABLED` | `true` | Set `false` to disable the Prometheus scrape endpoint |
| `OTEL_EXPORTER_PROMETHEUS_HOST` | `0.0.0.0` | Bind address for the Prometheus scrape endpoint |
| `OTEL_EXPORTER_PROMETHEUS_PORT` | `9464` | Port for the Prometheus scrape endpoint |
| `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` | unset (falls back to `OTEL_EXPORTER_OTLP_ENDPOINT` + `/v1/logs`) | Full OTLP/HTTP URL for **logs only** — lets logs go to a different collector than traces, e.g. an otel-collector fronting Elasticsearch |
| `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` | unset — **no fallback** to `OTEL_EXPORTER_OTLP_ENDPOINT` | Full OTLP/HTTP URL for **metrics only**, opt-in. Metrics already export via the Prometheus endpoint above; only set this if you have a real OTLP metrics receiver to send to as well |

Run a local Jaeger instance to view traces:

```bash
docker run --rm -p 16686:16686 -p 4318:4318 jaegertracing/all-in-one:latest
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 ./start.sh
```

Then open http://localhost:16686 and select the `prod-ai-agent` service.

Prometheus-format metrics are served on their own port (separate from the JSON
`GET /metrics` the dashboard polls) via `opentelemetry-exporter-prometheus`,
scraped from `http://localhost:9464/metrics` by default. `docker compose up`
starts a `prometheus` service pre-configured (`prometheus.yml`) to scrape the
`agent` service; its UI is at http://localhost:9090.

Grafana is also available for dashboarding on top of that Prometheus data —
`docker compose up` starts a `grafana` service at http://localhost:3000
(default login `admin`/`admin`) with a Prometheus data source already
provisioned (`grafana/provisioning/datasources/prometheus.yml`, pointed at
`http://prometheus:9090`) — no manual data source setup needed, just build a
dashboard against metrics like `agent_requests_total`.

Logs ship to Elasticsearch via an `otel-collector` (contrib distribution, for
its `elasticsearch` exporter) sitting between the app and ES — the app never
talks to Elasticsearch directly. `docker compose up` starts `elasticsearch`
(single-node, security disabled, for local dev only) and `otel-collector`
(config in `otel-collector-config.yaml`), and points the agent's
`OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` at the collector while traces/metrics keep
going to the `otel` (Jaeger) service as before. Logs land in the
`logs-generic.otel-default` data stream (the exporter's default — ES 8.x
auto-creates it via a built-in index template; don't set a custom
`logs_index` in the collector config unless you also create that index
yourself, or every write 404s). Query them directly:

```bash
curl "http://localhost:9200/logs-generic.otel-default/_search?pretty"
```

Or browse them in Kibana — `docker compose up` also starts a `kibana` service
at http://localhost:5601 (pointed at the same `elasticsearch` service, no
login needed since security is disabled). Create a Data View there for
`logs-generic.otel-default` (or `logs-*`) to use Discover.
