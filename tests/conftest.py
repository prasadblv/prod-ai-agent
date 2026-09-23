import pytest

from agent.metrics.metrics import MetricStore


@pytest.fixture
def security_context():
    from agent.types.types import SecurityContext

    return SecurityContext(user_id="u1", session_id="s1")


@pytest.fixture
def fresh_metric_store():
    """A clean MetricStore instance, isolated from the process-wide METRICS singleton."""
    return MetricStore()
