"""CodeSage startup script for Windows — starts the webhook server with ngrok tunnel."""

import subprocess
import sys
import time
import os


def check_prerequisites() -> bool:
    checks = []

    if not os.environ.get("DEEPSEEK_API_KEY"):
        checks.append("DEEPSEEK_API_KEY not set")
    if not os.environ.get("GITHUB_TOKEN"):
        checks.append("GITHUB_TOKEN not set")

    if checks:
        print("Missing prerequisites:")
        for c in checks:
            print(f"  - {c}")
        return False
    return True


def start_ngrok(port: int = 8000) -> subprocess.Popen | None:
    try:
        proc = subprocess.Popen(
            ["ngrok", "http", str(port), "--log=stdout"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"[OK] ngrok started on port {port}")
        return proc
    except FileNotFoundError:
        print("[WARN] ngrok not found — webhook URL not publicly accessible")
        print("  Install: https://ngrok.com/download")
        return None


def main():
    print("=" * 50)
    print("  CodeSage — AI Code Review GitHub App")
    print("=" * 50)

    if not check_prerequisites():
        sys.exit(1)

    port = int(os.environ.get("CODESAGE_PORT", "8000"))

    ngrok_proc = start_ngrok(port)
    time.sleep(2)

    print(f"\n[OK] Starting CodeSage on port {port}...")
    print(f"[INFO] Webhook URL: http://localhost:{port}/webhook")
    if ngrok_proc:
        print("[INFO] ngrok tunnel active — configure GitHub App webhook to your ngrok URL")
    print("\nPress Ctrl+C to stop\n")

    try:
        from src.codesage.main import main as run_server
        sys.exit(run_server())
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        if ngrok_proc:
            ngrok_proc.kill()
            print("[OK] ngrok stopped")


if __name__ == "__main__":
    main()
