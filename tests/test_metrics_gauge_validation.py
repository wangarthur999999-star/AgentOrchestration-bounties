"""Tests for non-finite gauge value rejection in MetricsCollector."""

import math
import pytest

from src.common.metrics import MetricsCollector


@pytest.fixture
def collector():
    return MetricsCollector()


class TestGaugeFiniteValues:
    def test_accepts_zero(self, collector):
        collector.gauge("test", 0.0)
        assert collector.snapshot()["gauges"]["test"] == 0.0

    def test_accepts_positive(self, collector):
        collector.gauge("cpu", 42.5)
        assert collector.snapshot()["gauges"]["cpu"] == 42.5

    def test_accepts_negative(self, collector):
        collector.gauge("temp", -15.0)
        assert collector.snapshot()["gauges"]["temp"] == -15.0

    def test_accepts_large_value(self, collector):
        collector.gauge("big", 1e308)
        assert collector.snapshot()["gauges"]["big"] == 1e308

    def test_accepts_small_value(self, collector):
        collector.gauge("tiny", -1e308)
        assert collector.snapshot()["gauges"]["tiny"] == -1e308


class TestGaugeNonFiniteRejection:
    def test_rejects_nan(self, collector):
        with pytest.raises(ValueError, match="finite"):
            collector.gauge("bad", float("nan"))

    def test_rejects_positive_inf(self, collector):
        with pytest.raises(ValueError, match="finite"):
            collector.gauge("bad", float("inf"))

    def test_rejects_negative_inf(self, collector):
        with pytest.raises(ValueError, match="finite"):
            collector.gauge("bad", float("-inf"))

    def test_nan_does_not_alter_state(self, collector):
        collector.gauge("clean", 1.0)
        try:
            collector.gauge("bad", float("nan"))
        except ValueError:
            pass
        assert collector.snapshot()["gauges"]["clean"] == 1.0
        assert "bad" not in collector.snapshot()["gauges"]

    def test_inf_does_not_alter_state(self, collector):
        collector.gauge("clean", 1.0)
        try:
            collector.gauge("bad", float("inf"))
        except ValueError:
            pass
        assert collector.snapshot()["gauges"]["clean"] == 1.0
        assert "bad" not in collector.snapshot()["gauges"]


class TestGaugeOverwrite:
    def test_overwrites_existing_value(self, collector):
        collector.gauge("mem", 100.0)
        collector.gauge("mem", 200.0)
        assert collector.snapshot()["gauges"]["mem"] == 200.0

    def test_rejects_overwrite_with_nan(self, collector):
        collector.gauge("mem", 100.0)
        with pytest.raises(ValueError):
            collector.gauge("mem", float("nan"))
        assert collector.snapshot()["gauges"]["mem"] == 100.0


class TestGaugeEdgeCases:
    def test_accepts_negative_zero(self, collector):
        collector.gauge("neg_zero", -0.0)
        assert collector.snapshot()["gauges"]["neg_zero"] == 0.0

    def test_accepts_min_subnormal(self, collector):
        collector.gauge("sub", 5e-324)
        assert collector.snapshot()["gauges"]["sub"] == 5e-324

    def test_error_message_includes_value(self, collector):
        with pytest.raises(ValueError, match="nan"):
            collector.gauge("x", float("nan"))

    def test_error_message_includes_inf(self, collector):
        with pytest.raises(ValueError, match="inf"):
            collector.gauge("x", float("inf"))
