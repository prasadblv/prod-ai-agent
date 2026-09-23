import logging
import time

from opentelemetry.trace import Status, StatusCode

from agent.llm.llm import LLM
from agent.metrics.metrics import METRICS
from agent.observability.telemetry import (
    cost_counter,
    latency_histogram,
    request_counter,
    token_counter,
    tracer,
)
from agent.types.types import AgentRequest, AgentResponse, SecurityContext

logger = logging.getLogger("agent")

class Agent:
    """Agent class that handles requests and responses."""

    def __init__(self):
        self.llm = LLM()  # Initialize the LLM instance


    def run(self, input: str, ctx: SecurityContext, *, label: str = "") -> AgentResponse:
        """Run the agent with the given input and security context."""
        logger.info(f"Running agent with request id: {ctx.request_id}")
        t0 = time.perf_counter()
        request = AgentRequest(raw_input=input, security_context=ctx)
        with tracer.start_as_current_span("agent.run") as span:
            span.set_attributes(
                {
                    "agent.request_id": ctx.request_id,
                    "agent.user_id": ctx.user_id,
                    "agent.session_id": ctx.session_id,
                    "agent.label": label or "",
                    "agent.permissions": ",".join(ctx.permissions),
                }
            )
            try:
                ts = time.perf_counter()
                messages = [{"role": "user", "content": request.raw_input}]
                response = self.llm.call(request, messages)
                l1_ms = max(1, int((time.perf_counter() - ts) * 1000))
                response.layer_timings = {
                    "l4_security_ms": 0,
                    "l2_memory_ms": 0,
                    "l1_llm_ms": l1_ms,
                    "total_ms": max(1, int((time.perf_counter() - t0) * 1000)),
                }
                response.status = "ok"
                METRICS.record(
                    status="ok",
                    tokens=response.tokens_used,
                    cost_usd=response.cost_usd,
                    latency_ms=response.latency_ms,
                    layer_timings=response.layer_timings,
                    content=response.content,
                    label=label or "ok",
                )
                attrs = {"status": "ok", "label": label or "ok"}
                request_counter.add(1, attrs)
                token_counter.add(response.tokens_used, attrs)
                cost_counter.add(response.cost_usd, attrs)
                latency_histogram.record(response.layer_timings["total_ms"], attrs)
                span.set_attributes(
                    {
                        "agent.status": "ok",
                        "agent.tokens_used": response.tokens_used,
                        "agent.cost_usd": response.cost_usd,
                        "agent.latency_ms": response.layer_timings["total_ms"],
                    }
                )
                logger.info(
                    f"[AGENT] complete — request_id={response.request_id} "
                    f"total={response.layer_timings['total_ms']}ms "
                    f"cost=${response.cost_usd}"
                )
                return response
            except PermissionError as e:
                timings = {"total_ms": max(1, int((time.perf_counter() - t0) * 1000))}
                METRICS.record(
                    status="blocked",
                    latency_ms=timings["total_ms"],
                    layer_timings=timings,
                    content=str(e),
                    label=label or "blocked",
                )
                attrs = {"status": "blocked", "label": label or "blocked"}
                request_counter.add(1, attrs)
                latency_histogram.record(timings["total_ms"], attrs)
                span.set_attribute("agent.status", "blocked")
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "blocked"))
                raise
            except ValueError as e:
                timings = {"total_ms": max(1, int((time.perf_counter() - t0) * 1000))}
                METRICS.record(
                    status="rejected",
                    latency_ms=timings["total_ms"],
                    layer_timings=timings,
                    content=str(e),
                    label=label or "rejected",
                )
                attrs = {"status": "rejected", "label": label or "rejected"}
                request_counter.add(1, attrs)
                latency_histogram.record(timings["total_ms"], attrs)
                span.set_attribute("agent.status", "rejected")
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "rejected"))
                raise