import pytest
from pydantic import ValidationError

from agent.types.types import AgentRequest, AgentResponse, SecurityContext


class TestSecurityContext:
    def test_defaults(self):
        ctx = SecurityContext(user_id="u1", session_id="s1")
        assert ctx.user_id == "u1"
        assert ctx.session_id == "s1"
        assert ctx.permissions == []
        assert ctx.rate_limit_tier == "standard"
        assert ctx.request_id  # auto-generated uuid string

    def test_request_id_is_unique_per_instance(self):
        a = SecurityContext(user_id="u1", session_id="s1")
        b = SecurityContext(user_id="u1", session_id="s1")
        assert a.request_id != b.request_id

    @pytest.mark.parametrize("missing", ["user_id", "session_id"])
    def test_missing_required_field_raises(self, missing):
        kwargs = {"user_id": "u1", "session_id": "s1"}
        del kwargs[missing]
        with pytest.raises(ValidationError):
            SecurityContext(**kwargs)

    def test_permissions_default_is_not_shared_between_instances(self):
        a = SecurityContext(user_id="u1", session_id="s1")
        b = SecurityContext(user_id="u2", session_id="s2")
        a.permissions.append("read")
        assert b.permissions == []


class TestAgentRequest:
    def test_defaults(self, security_context):
        req = AgentRequest(raw_input="hello", security_context=security_context)
        assert req.raw_input == "hello"
        assert req.security_context is security_context
        assert req.max_token == 1024
        assert req.temperature == 0.1
        assert req.metadata == {}

    def test_missing_security_context_raises(self):
        with pytest.raises(ValidationError):
            AgentRequest(raw_input="hello")


class TestAgentResponse:
    def test_defaults(self):
        resp = AgentResponse(request_id="r1", content="hi")
        assert resp.tool_calls == []
        assert isinstance(resp.tool_calls, list)
        assert resp.tokens_used == 0
        assert resp.cost_usd == 0.0
        assert resp.latency_ms == 0
        assert resp.layer_timings == {}
        assert resp.status == "ok"

    def test_tool_calls_default_is_not_shared_between_instances(self):
        a = AgentResponse(request_id="r1", content="hi")
        b = AgentResponse(request_id="r2", content="bye")
        a.tool_calls.append({"name": "search"})
        assert b.tool_calls == []

    def test_is_mutable_after_construction(self):
        """agent.agent.Agent.run relies on setting attributes post-construction."""
        resp = AgentResponse(request_id="r1", content="hi")
        resp.layer_timings = {"total_ms": 5}
        resp.status = "blocked"
        assert resp.layer_timings == {"total_ms": 5}
        assert resp.status == "blocked"
