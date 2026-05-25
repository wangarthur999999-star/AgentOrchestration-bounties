"""Tests for CLI exit code propagation — bounty #3584."""

import sys

import pytest

from src.cli.main import cli


class TestCLIExitCodes:
    def test_init_returns_zero(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["ao-cli", "init", "test-project"])
        result = cli()
        assert result == 0

    def test_deploy_returns_zero(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["ao-cli", "deploy", "manifest.yaml"])
        result = cli()
        assert result == 0

    def test_status_returns_zero(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["ao-cli", "status"])
        result = cli()
        assert result == 0

    def test_logs_returns_zero(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["ao-cli", "logs", "agent-1"])
        result = cli()
        assert result == 0

    def test_no_command_returns_one(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["ao-cli"])
        result = cli()
        assert result == 1

    def test_deploy_returns_int(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["ao-cli", "deploy", "test.yaml"])
        result = cli()
        assert isinstance(result, int)
        assert result == 0

    def test_init_returns_int(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["ao-cli", "init", "proj"])
        result = cli()
        assert isinstance(result, int)
        assert result == 0

    def test_verbose_flag_works(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["ao-cli", "--verbose", "status"])
        result = cli()
        assert result == 0
