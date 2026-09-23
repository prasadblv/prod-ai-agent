from unittest.mock import MagicMock, patch

import anthropic
import httpx
import pytest

from agent.llm.llm import LLM, _estimate_cost
from agent.types.types import AgentRequest, SecurityContext


def make_request(text="hello"):
    ctx = SecurityContext(user_id="u1", session_id="s1")
    req = AgentRequest(raw_input=text, security_context=ctx)
    return req, [{"role": "user", "content": text}]


class TestEstimateCost:
    def test_zero_tokens_costs_nothing(self):
        assert _estimate_cost(0, 0) == 0.0

    def test_known_rates(self):
        # 1M input tokens @ $2/1M + 1M output tokens @ $10/1M = $12
        assert _estimate_cost(1_000_000, 1_000_000) == 12.0

    def test_rounds_to_six_decimals(self):
        assert _estimate_cost(1, 1) == round((1 / 1_000_000 * 2) + (1 / 1_000_000 * 10), 6)


class TestLLMStubMode:
    def test_stub_mode_when_no_api_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        llm = LLM()
        assert llm._use_real_llm is False

    def test_stub_response_echoes_last_user_message(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        llm = LLM()
        req, msg = make_request("what is the weather")
        resp = llm.call(req, msg)
        assert "what is the weather" in resp.content
        assert resp.content.startswith("[STUB]")

    def test_stub_response_uses_fixed_token_counts_and_cost(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        llm = LLM()
        req, msg = make_request()
        resp = llm.call(req, msg)
        assert resp.tokens_used == 42 + 18
        assert resp.cost_usd == _estimate_cost(42, 18)

    def test_response_request_id_matches_security_context(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        llm = LLM()
        req, msg = make_request()
        resp = llm.call(req, msg)
        assert resp.request_id == req.security_context.request_id

    def test_latency_is_at_least_one_ms(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        llm = LLM()
        req, msg = make_request()
        resp = llm.call(req, msg)
        assert resp.latency_ms >= 1

    def test_status_is_ok(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        llm = LLM()
        req, msg = make_request()
        resp = llm.call(req, msg)
        assert resp.status == "ok"


class TestLLMRealMode:
    def test_real_mode_enabled_when_api_key_present(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
        with patch("anthropic.Anthropic") as mock_anthropic_cls:
            llm = LLM()
        assert llm._use_real_llm is True
        mock_anthropic_cls.assert_called_once()

    def test_real_mode_builds_response_from_client(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
        with patch("anthropic.Anthropic") as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_anthropic_cls.return_value = mock_client
            block = MagicMock(type="text", text="hi there")
            mock_client.messages.create.return_value = MagicMock(
                content=[block],
                usage=MagicMock(input_tokens=100, output_tokens=50),
            )
            llm = LLM()
            req, msg = make_request()
            resp = llm.call(req, msg)

        assert resp.content == "hi there"
        assert resp.tokens_used == 150
        assert resp.cost_usd == _estimate_cost(100, 50)

    def _make_client_raising(self, exc):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = exc
        return mock_client

    def test_api_connection_error_is_reraised(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
        exc = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
        with patch("anthropic.Anthropic") as mock_anthropic_cls:
            mock_anthropic_cls.return_value = self._make_client_raising(exc)
            llm = LLM()
            req, msg = make_request()
            with pytest.raises(anthropic.APIConnectionError):
                llm.call(req, msg)

    def test_rate_limit_error_is_reraised(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
        response = httpx.Response(
            429, request=httpx.Request("POST", "https://api.anthropic.com"), json={"error": {}}
        )
        exc = anthropic.RateLimitError("rate limited", response=response, body=None)
        with patch("anthropic.Anthropic") as mock_anthropic_cls:
            mock_anthropic_cls.return_value = self._make_client_raising(exc)
            llm = LLM()
            req, msg = make_request()
            with pytest.raises(anthropic.RateLimitError):
                llm.call(req, msg)

    def test_api_status_error_is_reraised(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
        response = httpx.Response(
            500, request=httpx.Request("POST", "https://api.anthropic.com"), json={"error": {}}
        )
        exc = anthropic.APIStatusError("server error", response=response, body=None)
        with patch("anthropic.Anthropic") as mock_anthropic_cls:
            mock_anthropic_cls.return_value = self._make_client_raising(exc)
            llm = LLM()
            req, msg = make_request()
            with pytest.raises(anthropic.APIStatusError):
                llm.call(req, msg)
