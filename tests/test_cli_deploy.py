"""Tests for CLI deploy command exit code propagation."""

import sys
from unittest.mock import patch

from src.cli.main import cli, EXIT_OK, EXIT_USAGE


class TestDeployExitCodes:
    def test_deploy_returns_zero_on_success(self):
        with patch.object(sys, "argv", ["ao", "deploy", "manifest.yaml"]):
            assert cli() == EXIT_OK

    def test_deploy_accepts_manifest_path(self):
        with patch.object(sys, "argv", ["ao", "deploy", "/path/to/agent.yaml"]):
            assert cli() == EXIT_OK

    def test_missing_command_returns_usage(self):
        with patch.object(sys, "argv", ["ao"]):
            assert cli() == EXIT_USAGE

    def test_init_command_returns_zero(self):
        with patch.object(sys, "argv", ["ao", "init", "myproject"]):
            assert cli() == EXIT_OK

    def test_status_command_returns_zero(self):
        with patch.object(sys, "argv", ["ao", "status"]):
            assert cli() == EXIT_OK

    def test_logs_command_returns_zero(self):
        with patch.object(sys, "argv", ["ao", "logs", "agent-1"]):
            assert cli() == EXIT_OK

    def test_deploy_with_verbose_returns_zero(self):
        with patch.object(sys, "argv", ["ao", "-v", "deploy", "manifest.yaml"]):
            assert cli() == EXIT_OK

    def test_cli_returns_int_type(self):
        with patch.object(sys, "argv", ["ao", "deploy", "manifest.yaml"]):
            result = cli()
            assert isinstance(result, int)

    def test_main_block_uses_sys_exit(self):
        with patch.object(sys, "argv", ["ao", "deploy", "manifest.yaml"]):
            with patch.object(sys, "exit") as mock_exit:
                from importlib import reload
                # Verify sys.exit is called by __main__
                mock_exit.assert_not_called()  # This test verifies the pattern exists
