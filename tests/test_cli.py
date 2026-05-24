"""Tests for CLI argument validation."""

import argparse
import pytest

from src.cli.main import validate_nonnegative


class TestValidateNonnegative:
    def test_accepts_zero(self):
        assert validate_nonnegative("0") == 0

    def test_accepts_positive(self):
        assert validate_nonnegative("42") == 42

    def test_accepts_large_value(self):
        assert validate_nonnegative("999999") == 999999

    def test_rejects_negative(self):
        with pytest.raises(argparse.ArgumentTypeError, match="non-negative"):
            validate_nonnegative("-1")

    def test_rejects_negative_five(self):
        with pytest.raises(argparse.ArgumentTypeError, match="non-negative"):
            validate_nonnegative("-5")

    def test_rejects_non_integer(self):
        with pytest.raises(ValueError):
            validate_nonnegative("abc")

    def test_rejects_empty_string(self):
        with pytest.raises(ValueError):
            validate_nonnegative("")


class TestLogsTailArgparseIntegration:
    def test_nonnegative_tail_accepted(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        logs_parser = subparsers.add_parser("logs")
        logs_parser.add_argument("agent_id")
        logs_parser.add_argument(
            "--tail", "-t", type=validate_nonnegative, default=50
        )
        args = parser.parse_args(["logs", "agent1", "--tail", "100"])
        assert args.tail == 100

    def test_zero_tail_accepted(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        logs_parser = subparsers.add_parser("logs")
        logs_parser.add_argument("agent_id")
        logs_parser.add_argument(
            "--tail", "-t", type=validate_nonnegative, default=50
        )
        args = parser.parse_args(["logs", "agent1", "--tail", "0"])
        assert args.tail == 0

    def test_default_tail_when_omitted(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        logs_parser = subparsers.add_parser("logs")
        logs_parser.add_argument("agent_id")
        logs_parser.add_argument(
            "--tail", "-t", type=validate_nonnegative, default=50
        )
        args = parser.parse_args(["logs", "agent1"])
        assert args.tail == 50

    def test_negative_tail_rejected_by_argparse(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        logs_parser = subparsers.add_parser("logs")
        logs_parser.add_argument("agent_id")
        logs_parser.add_argument(
            "--tail", "-t", type=validate_nonnegative, default=50
        )
        with pytest.raises(SystemExit):
            parser.parse_args(["logs", "agent1", "--tail", "-5"])
