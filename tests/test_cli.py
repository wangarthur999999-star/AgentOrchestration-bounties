import subprocess
import sys

import pytest
import src.cli.main as cli_main


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "src.cli.main"] + list(args),
        capture_output=True, text=True,
    )


class TestCliDeployExitCode:
    def test_deploy_without_backend_exits_nonzero(self, tmp_path):
        """End-to-end: deploy fails when orchestrator backend is not installed."""
        manifest = tmp_path / "agent.yaml"
        manifest.write_text("name: test-agent")
        result = _run_cli("deploy", str(manifest))
        assert result.returncode == 3, (
            f"expected exit 3 (backend not found), got {result.returncode}"
        )

    def test_init_returns_zero(self):
        result = _run_cli("init", "my-project")
        assert result.returncode == 0

    def test_no_command_exits_nonzero(self):
        result = _run_cli()
        assert result.returncode != 0

    def test_unknown_command_exits_nonzero(self):
        result = _run_cli("nonexistent-command")
        assert result.returncode != 0


class TestCliDeployHandler:
    def test_deploy_success_returns_zero(self, tmp_path, monkeypatch):
        manifest = tmp_path / "agent.yaml"
        manifest.write_text("name: test-agent")

        def fake_run(cmd, **_):
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="ok\n", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        args = type("Args", (), {"manifest": str(manifest), "verbose": False})()
        assert cli_main._handle_deploy(args) == 0

    def test_deploy_backend_unavailable_returns_3(self, tmp_path, monkeypatch):
        manifest = tmp_path / "agent.yaml"
        manifest.write_text("name: test-agent")

        def fake_run(cmd, **_):
            raise FileNotFoundError("orchestrator")

        monkeypatch.setattr(subprocess, "run", fake_run)
        args = type("Args", (), {"manifest": str(manifest), "verbose": False})()
        assert cli_main._handle_deploy(args) == 3

    def test_deploy_backend_failure_returns_backend_exit_code(self, tmp_path, monkeypatch):
        manifest = tmp_path / "agent.yaml"
        manifest.write_text("name: test-agent")

        def fake_run(cmd, **_):
            return subprocess.CompletedProcess(cmd, returncode=5, stdout="", stderr="failed")

        monkeypatch.setattr(subprocess, "run", fake_run)
        args = type("Args", (), {"manifest": str(manifest), "verbose": False})()
        assert cli_main._handle_deploy(args) == 5
