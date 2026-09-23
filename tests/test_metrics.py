from agent.metrics.metrics import MetricStore


class TestMetricStoreSnapshot:
    def test_initial_snapshot(self, fresh_metric_store):
        snap = fresh_metric_store.snapshot()
        assert snap["requests_total"] == 0
        assert snap["last_status"] == "idle"
        assert snap["recent_events"] == []

    def test_snapshot_is_a_copy(self, fresh_metric_store):
        snap = fresh_metric_store.snapshot()
        snap["requests_total"] = 999
        assert fresh_metric_store.snapshot()["requests_total"] == 0


class TestMetricStoreRecord:
    def test_record_ok_increments_totals(self, fresh_metric_store):
        fresh_metric_store.record(status="ok", tokens=10, cost_usd=0.01, latency_ms=100)
        snap = fresh_metric_store.snapshot()
        assert snap["requests_total"] == 1
        assert snap["requests_ok"] == 1
        assert snap["requests_blocked"] == 0
        assert snap["requests_rejected"] == 0
        assert snap["tokens_total"] == 10
        assert snap["latency_ms_total"] == 100
        assert snap["last_status"] == "ok"

    def test_record_blocked_increments_blocked_bucket(self, fresh_metric_store):
        fresh_metric_store.record(status="blocked")
        snap = fresh_metric_store.snapshot()
        assert snap["requests_total"] == 1
        assert snap["requests_blocked"] == 1
        assert snap["requests_ok"] == 0

    def test_record_rejected_increments_rejected_bucket(self, fresh_metric_store):
        fresh_metric_store.record(status="rejected")
        snap = fresh_metric_store.snapshot()
        assert snap["requests_total"] == 1
        assert snap["requests_rejected"] == 1

    def test_cost_usd_total_accumulates_additively(self, fresh_metric_store):
        """Recording two $0.01 requests should leave a $0.02 running total."""
        fresh_metric_store.record(status="ok", cost_usd=0.01)
        fresh_metric_store.record(status="ok", cost_usd=0.01)
        assert fresh_metric_store.snapshot()["cost_usd_total"] == 0.02

    def test_negative_cost_is_floored_at_zero_contribution(self, fresh_metric_store):
        fresh_metric_store.record(status="ok", cost_usd=-5.0)
        assert fresh_metric_store.snapshot()["cost_usd_total"] == 0.0

    def test_negative_latency_is_floored_at_zero_contribution(self, fresh_metric_store):
        fresh_metric_store.record(status="ok", latency_ms=-100)
        assert fresh_metric_store.snapshot()["latency_ms_total"] == 0

    def test_latency_ms_avg_computed_over_all_requests(self, fresh_metric_store):
        fresh_metric_store.record(status="ok", latency_ms=100)
        fresh_metric_store.record(status="ok", latency_ms=200)
        assert fresh_metric_store.snapshot()["latency_ms_avg"] == 150.0

    def test_layer_timings_accumulate_per_layer(self, fresh_metric_store):
        fresh_metric_store.record(
            status="ok",
            layer_timings={"l4_security_ms": 1, "l2_memory_ms": 2, "l1_llm_ms": 3},
        )
        fresh_metric_store.record(
            status="ok",
            layer_timings={"l4_security_ms": 10, "l2_memory_ms": 20, "l1_llm_ms": 30},
        )
        snap = fresh_metric_store.snapshot()
        assert snap["l4_security_ms_total"] == 11
        assert snap["l2_memory_ms_total"] == 22
        assert snap["l1_llm_ms_total"] == 33

    def test_missing_layer_timings_defaults_to_zero_contribution(self, fresh_metric_store):
        fresh_metric_store.record(status="ok")
        snap = fresh_metric_store.snapshot()
        assert snap["l4_security_ms_total"] == 0
        assert snap["l2_memory_ms_total"] == 0
        assert snap["l1_llm_ms_total"] == 0

    def test_last_content_is_truncated_to_200_chars(self, fresh_metric_store):
        fresh_metric_store.record(status="ok", content="x" * 500)
        assert len(fresh_metric_store.snapshot()["last_content"]) == 200

    def test_recent_events_ordered_most_recent_first(self, fresh_metric_store):
        fresh_metric_store.record(status="ok", label="first")
        fresh_metric_store.record(status="ok", label="second")
        events = fresh_metric_store.snapshot()["recent_events"]
        assert events[0]["label"] == "second"
        assert events[1]["label"] == "first"

    def test_recent_events_label_defaults_to_status(self, fresh_metric_store):
        fresh_metric_store.record(status="blocked")
        assert fresh_metric_store.snapshot()["recent_events"][0]["label"] == "blocked"

    def test_recent_events_capped_at_ten(self, fresh_metric_store):
        for i in range(15):
            fresh_metric_store.record(status="ok", label=f"evt{i}")
        events = fresh_metric_store.snapshot()["recent_events"]
        assert len(events) == 10
        assert events[0]["label"] == "evt14"
        assert events[-1]["label"] == "evt5"


class TestMetricStoreBumpDemo:
    def test_bump_demo_increments_counter(self, fresh_metric_store):
        fresh_metric_store.bump_demo()
        fresh_metric_store.bump_demo()
        assert fresh_metric_store.snapshot()["demo_runs"] == 2

    def test_bump_demo_does_not_affect_requests_total(self, fresh_metric_store):
        fresh_metric_store.bump_demo()
        assert fresh_metric_store.snapshot()["requests_total"] == 0


def test_module_level_singleton_exists():
    from agent.metrics.metrics import METRICS

    assert isinstance(METRICS, MetricStore)
