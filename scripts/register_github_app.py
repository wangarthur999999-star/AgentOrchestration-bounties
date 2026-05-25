"""GitHub App registration helper — creates the CodeSage GitHub App."""

import os
import sys


APP_MANIFEST = {
    "name": "CodeSage AI Review",
    "url": "https://github.com/apps/codesage-ai",
    "hook_attributes": {"url": os.environ.get("CODESAGE_WEBHOOK_URL", "http://localhost:8000/webhook")},
    "redirect_url": "",
    "description": "AI-powered automated code review for every pull request. "
    "Multi-perspective analysis: security, bugs, performance, maintainability.",
    "public": True,
    "default_events": ["pull_request"],
    "default_permissions": {
        "pull_requests": "write",
        "contents": "read",
        "metadata": "read",
    },
}


def main():
    print("=" * 60)
    print("  CodeSage — GitHub App Registration")
    print("=" * 60)
    print()
    print("To register the GitHub App, you have two options:")
    print()
    print("Option 1 (Recommended): Manual registration")
    print("  1. Go to: https://github.com/settings/apps/new")
    print("  2. Set the following:")
    print("     - GitHub App name: CodeSage AI Review")
    print("     - Homepage URL: (your landing page)")
    print("     - Webhook URL: (your server URL)/webhook")
    print("     - Webhook secret: (generate a random string)")
    print("  3. Permissions needed:")
    print("     - Pull requests: Read & Write")
    print("     - Contents: Read-only")
    print("     - Metadata: Read-only")
    print("  4. Subscribe to events:")
    print("     - Pull request")
    print("  5. After creation, set these env vars:")
    print("     CODESAGE_APP_ID=<app_id>")
    print("     CODESAGE_WEBHOOK_SECRET=<webhook_secret>")
    print("     CODESAGE_PRIVATE_KEY=<path_to_pem>")
    print()
    print("Option 2: Manifest flow")
    print("  Use the manifest below at:")
    print("  https://github.com/settings/apps/new?manifest_flow=1")
    print()
    print("Manifest JSON:")
    import json
    print(json.dumps(APP_MANIFEST, indent=2))
    print()
    print("After registration, set the env vars above and start the server.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
