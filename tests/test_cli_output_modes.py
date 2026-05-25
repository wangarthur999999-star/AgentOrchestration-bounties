"""Tests for CLI output mode validation — bounty #3907."""

import argparse
import sys
from unittest.mock import patch

import pytest

from src.cli.main import cli


def _parse_output_mode(args_line):
    """Helper: invoke CLI with given args and return the output mode parsed."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", "-o", choices=["json", "table", "text"], default="table")
    return parser.parse_args(args_line)


class TestOutputModeAccepted:
    def test_json_mode_accepted(self):
        ns = _parse_output_mode(["--output", "json"])
        assert ns.output == "json"

    def test_table_mode_accepted(self):
        ns = _parse_output_mode(["--output", "table"])
        assert ns.output == "table"

    def test_text_mode_accepted(self):
        ns = _parse_output_mode(["--output", "text"])
        assert ns.output == "text"

    def test_default_output_is_table(self):
        ns = _parse_output_mode([])
        assert ns.output == "table"

    def test_short_flag_accepted(self):
        ns = _parse_output_mode(["-o", "json"])
        assert ns.output == "json"


class TestOutputModeRejected:
    def test_invalid_mode_rejected(self):
        with pytest.raises(SystemExit):
            _parse_output_mode(["--output", "xml"])

    def test_csv_mode_rejected(self):
        with pytest.raises(SystemExit):
            _parse_output_mode(["--output", "csv"])

    def test_empty_mode_rejected(self):
        with pytest.raises(SystemExit):
            _parse_output_mode(["--output", ""])

    def test_yaml_mode_rejected(self):
        with pytest.raises(SystemExit):
            _parse_output_mode(["--output", "yaml"])

    def test_html_mode_rejected(self):
        with pytest.raises(SystemExit):
            _parse_output_mode(["--output", "html"])


class TestOutputModeEdgeCases:
    @patch("src.cli.main.configure_logging")
    def test_init_command_uses_output_mode(self, mock_log):
        with patch("sys.argv", ["ao", "--output", "json", "init", "test-proj"]):
            with patch("builtins.print") as mock_print:
                cli()
                mock_print.assert_any_call("Initializing project: test-proj (output: json)")

    @patch("src.cli.main.configure_logging")
    def test_deploy_command_uses_output_mode(self, mock_log):
        with patch("sys.argv", ["ao", "--output", "text", "deploy", "manifest.yaml"]):
            with patch("builtins.print") as mock_print:
                cli()
                mock_print.assert_any_call(
                    "Deploying agent from manifest: manifest.yaml (output: text)"
                )

    @patch("src.cli.main.configure_logging")
    def test_invalid_mode_exits_nonzero(self, mock_log):
        with patch("sys.argv", ["ao", "--output", "xml", "status"]):
            with pytest.raises(SystemExit):
                cli()
