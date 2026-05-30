"""E2E smoke test for the multi-agent customer service pipeline.

Uses FastAPI TestClient for reliable in-process testing of the full
Triage -> Specialist -> Synthesizer flow against the real DeepSeek API.
"""

import os

import pytest
from fastapi.testclient import TestClient

from src.api.server import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


def test_e2e_team_respond_smoke(client):
    """Full pipeline: send a booking request, verify 3-agent response."""
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("DEEPSEEK_API_KEY not set")

    resp = client.post(
        "/api/v2/teams/respond",
        json={
            "customer_message": (
                "Hi, I'd like to book a massage appointment for tomorrow "
                "afternoon. Do you have any slots available?"
            ),
            "business_context": {
                "name": "Serenity Spa",
                "services": ["Swedish Massage", "Deep Tissue", "Hot Stone", "Aromatherapy"],
                "language": "en",
            },
            "language": "en",
            "conversation_history": [],
        },
        headers={"Authorization": "Bearer e2e-test"},
    )

    data = resp.json()
    print(f"\nE2E: status={data.get('status')}, duration={data.get('duration')}s")
    print(f"  agents_used: {data.get('agents_used')}")
    print(f"  response_preview: {data.get('response', '')[:200]}")
    if data.get("error"):
        print(f"  error: {data.get('error', '')[:300]}")

    assert data["status"] == "completed", (
        f"Expected status=completed, got {data.get('status')}: {data.get('error', 'N/A')}"
    )
    assert data.get("response"), "Response should not be empty"
    assert data["duration"] > 0, "Duration should be > 0"
    assert len(data.get("agents_used", [])) >= 3, (
        f"Expected >= 3 agents used, got: {data.get('agents_used')}"
    )
    assert "synthesizer" in data.get("agents_used", []), (
        "Synthesizer must be in agents_used"
    )

    print(f"\n  FULL RESPONSE:\n{data['response']}")
