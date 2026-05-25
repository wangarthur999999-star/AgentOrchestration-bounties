"""Tests for exporter counter range limits in MetricsCollector."""

import pytest

from src.common.metrics import MetricsCollector, MAX_SAFE_COUNTER


@pytest.fixture
def collector():
    return MetricsCollector()


class TestIncrementValidation:
    def test_accepts_positive_value(self, collector):
        collector.increment("requests", 10)
        assert collector.snapshot()["counters"]["requests"] == 10

    def test_accepts_default_value(self, collector):
        collector.increment("requests")
        assert collector.snapshot()["counters"]["requests"] == 1

    def test_rejects_negative_value(self, collector):
        with pytest.raises(ValueError, match="non-negative"):
            collector.increment("bad", -1)

    def test_rejects_negative_value_message(self, collector):
        with pytest.raises(ValueError, match="-5"):
            collector.increment("bad", -5)


class TestCounterRangeClamping:
    def test_counter_clamped_at_max(self, collector):
        collector.increment("big", MAX_SAFE_COUNTER)
        collector.increment("big", 1)
        assert collector.snapshot()["counters"]["big"] == MAX_SAFE_COUNTER

    def test_counter_exactly_at_max(self, collector):
        collector.increment("big", MAX_SAFE_COUNTER)
        assert collector.snapshot()["counters"]["big"] == MAX_SAFE_COUNTER

    def test_counter_below_max(self, collector):
        collector.increment("small", MAX_SAFE_COUNTER - 1)
        collector.increment("small")
        assert collector.snapshot()["counters"]["small"] == MAX_SAFE_COUNTER

    def test_multiple_increments_clamp(self, collector):
        for _ in range(5):
            collector.increment("c", MAX_SAFE_COUNTER // 3)
        assert collector.snapshot()["counters"]["c"] <= MAX_SAFE_COUNTER

    def test_counter_does_not_wrap(self, collector):
        collector.increment("x", MAX_SAFE_COUNTER)
        collector.increment("x", 100)
        assert collector.snapshot()["counters"]["x"] == MAX_SAFE_COUNTER


class TestCounterSnapshot:
    def test_snapshot_includes_counters(self, collector):
        collector.increment("a", 5)
        collector.increment("b", 10)
        snap = collector.snapshot()
        assert snap["counters"]["a"] == 5
        assert snap["counters"]["b"] == 10

    def test_snapshot_returns_plain_dict(self, collector):
        collector.increment("x")
        snap = collector.snapshot()
        assert isinstance(snap["counters"], dict)
        assert isinstance(snap["gauges"], dict)
        assert isinstance(snap["histograms"], dict)

    def test_max_safe_counter_is_float64_safe(self):
        assert MAX_SAFE_COUNTER == 2**53
        # 2^53 and 2^53+1 are indistinguishable in float64
        assert float(MAX_SAFE_COUNTER) == float(MAX_SAFE_COUNTER + 1)


class TestCounterEdgeCases:
    def test_zero_increment_noop(self, collector):
        collector.increment("x", 0)
        assert collector.snapshot()["counters"]["x"] == 0

    def test_large_single_increment(self, collector):
        collector.increment("big", 10**12)
        assert collector.snapshot()["counters"]["big"] == 10**12

    def test_multiple_counters_independent(self, collector):
        collector.increment("a", MAX_SAFE_COUNTER)
        collector.increment("b", 1)
        assert collector.snapshot()["counters"]["a"] == MAX_SAFE_COUNTER
        assert collector.snapshot()["counters"]["b"] == 1

    def test_existing_counter_approaches_limit(self, collector):
        collector.increment("grow", MAX_SAFE_COUNTER - 10)
        collector.increment("grow", 5)
        assert collector.snapshot()["counters"]["grow"] == MAX_SAFE_COUNTER - 5
        collector.increment("grow", 5)
        assert collector.snapshot()["counters"]["grow"] == MAX_SAFE_COUNTER
