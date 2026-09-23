"""Integration tests for Agent.run() and its effect on the METRICS singleton."""

from unittest.mock import MagicMock

import pytest

from agent.agent import Agent
from agent.metrics.metrics import MetricStore
from agent.types.types import AgentResponse, SecurityContext


@pytest.fixture
def agent(monkeypatch):
    """An Agent with a mocked LLM and an isolated MetricStore."""
    a = Agent.__new__(Agent)  # skip LLM() construction, which reads env
    a.llm = MagicMock()
    isolated_metrics = MetricStore()
    monkeypatch.setattr("agent.agent.METRICS", isolated_metrics)
    return a


@pytest.fixture
def ctx():
    return SecurityContext(user_id="u1", session_id="s1", permissions=["read"])


class TestAgentRunSuccess:
    def test_returns_llm_response(self, agent, ctx):
        agent.llm.call.return_value = AgentResponse(
            request_id=ctx.request_id, content="hello", tokens_used=10, cost_usd=0.01
        )
        resp = agent.run("hi", ctx)
        assert resp.content == "hello"
        assert resp.request_id == ctx.request_id

    def test_sets_layer_timings_and_status(self, agent, ctx):
        agent.llm.call.return_value = AgentResponse(request_id=ctx.request_id, content="hi")
        resp = agent.run("hi", ctx)
        assert resp.status == "ok"
        assert set(resp.layer_timings.keys()) == {
            "l4_security_ms",
            "l2_memory_ms",
            "l1_llm_ms",
            "total_ms",
        }
        assert resp.layer_timings["l4_security_ms"] == 0
        assert resp.layer_timings["l2_memory_ms"] == 0
        assert resp.layer_timings["total_ms"] >= resp.layer_timings["l1_llm_ms"]

    def test_records_ok_in_metrics(self, agent, ctx):
        agent.llm.call.return_value = AgentResponse(
            request_id=ctx.request_id, content="hi", tokens_used=5, cost_usd=0.02
        )
        agent.run("hi", ctx, label="greeting")

        from agent.agent import METRICS

        snap = METRICS.snapshot()
        assert snap["requests_total"] == 1
        assert snap["requests_ok"] == 1
        assert snap["tokens_total"] == 5
        assert snap["recent_events"][0]["label"] == "greeting"

    def test_builds_agent_request_from_input_and_context(self, agent, ctx):
        agent.llm.call.return_value = AgentResponse(request_id=ctx.request_id, content="hi")
        agent.run("some input", ctx)
        called_request, called_messages = agent.llm.call.call_args[0]
        assert called_request.raw_input == "some input"
        assert called_request.security_context is ctx
        assert called_messages == [{"role": "user", "content": "some input"}]


class TestAgentRunPermissionError:
    def test_reraises_and_records_blocked(self, agent, ctx):
        agent.llm.call.side_effect = PermissionError("nope")

        with pytest.raises(PermissionError):
            agent.run("hi", ctx, label="blocked-case")

        from agent.agent import METRICS

        snap = METRICS.snapshot()
        assert snap["requests_total"] == 1
        assert snap["requests_blocked"] == 1
        assert snap["requests_ok"] == 0
        assert snap["last_status"] == "blocked"
        assert snap["recent_events"][0]["label"] == "blocked-case"


class TestAgentRunValueError:
    def test_reraises_and_records_rejected(self, agent, ctx):
        agent.llm.call.side_effect = ValueError("bad input")

        with pytest.raises(ValueError):
            agent.run("hi", ctx)

        from agent.agent import METRICS

        snap = METRICS.snapshot()
        assert snap["requests_total"] == 1
        assert snap["requests_rejected"] == 1
        assert snap["last_status"] == "rejected"
        # no explicit label passed -> defaults to "rejected"
        assert snap["recent_events"][0]["label"] == "rejected"


class TestAgentRunOtherExceptions:
    def test_unhandled_exception_propagates_without_recording(self, agent, ctx):
        agent.llm.call.side_effect = RuntimeError("boom")

        with pytest.raises(RuntimeError):
            agent.run("hi", ctx)

        from agent.agent import METRICS

        assert METRICS.snapshot()["requests_total"] == 0
