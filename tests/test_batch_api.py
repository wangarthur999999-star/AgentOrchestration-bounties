"""Tests for batch operations — atomicity, validation, and error handling."""

import pytest
from fastapi.testclient import TestClient

from src.agent.registry import AgentRegistry
from src.api.routes import router
from src.api.server import create_app


@pytest.fixture
def registry():
    reg = AgentRegistry()
    reg.register("alpha", "worker.test", {"key": "val1"})
    reg.register("beta", "worker.test", {"key": "val2"})
    reg.register("gamma", "scheduler.core", {"interval": 60})
    return reg


@pytest.fixture
def client(registry):
    app = create_app()
    app.dependency_overrides = {}
    from src.api import routes as rt
    rt.registry = registry
    return TestClient(app)


class TestBatchUpdateRegistry:
    def test_batch_update_status_atomic(self, registry):
        agent_ids = list(registry._agents.keys())
        updates = [
            {"agent_id": agent_ids[0], "status": "running"},
            {"agent_id": agent_ids[1], "status": "stopped"},
        ]
        results = registry.batch_update(updates, operation="update_status")
        assert len(results) == 2
        assert registry._agents[agent_ids[0]]["status"] == "running"
        assert registry._agents[agent_ids[1]]["status"] == "stopped"

    def test_batch_update_config_atomic(self, registry):
        agent_ids = list(registry._agents.keys())
        updates = [
            {"agent_id": agent_ids[0], "config": {"new_key": 42}},
            {"agent_id": agent_ids[1], "config": {"env": "prod"}},
        ]
        results = registry.batch_update(updates, operation="update_config")
        assert len(results) == 2
        assert registry._agents[agent_ids[0]]["config"]["new_key"] == 42
        assert registry._agents[agent_ids[1]]["config"]["env"] == "prod"
        assert registry._agents[agent_ids[0]]["config"]["key"] == "val1"  # preserved

    def test_batch_update_empty_raises(self, registry):
        with pytest.raises(ValueError, match="at least one entry"):
            registry.batch_update([], operation="update_status")

    def test_batch_update_unknown_agent_rejected(self, registry):
        updates = [
            {"agent_id": list(registry._agents.keys())[0], "status": "running"},
            {"agent_id": "nonexistent-12345", "status": "stopped"},
        ]
        with pytest.raises(ValueError, match="not found"):
            registry.batch_update(updates, operation="update_status")

    def test_partial_success_prevented(self, registry):
        """If any agent_id is invalid, NO agent should be updated."""
        agent_ids = list(registry._agents.keys())
        original_statuses = [registry._agents[aid]["status"] for aid in agent_ids]

        updates = [
            {"agent_id": agent_ids[0], "status": "running"},
            {"agent_id": "bogus-agent", "status": "stopped"},
        ]
        with pytest.raises(ValueError, match="not found"):
            registry.batch_update(updates, operation="update_status")

        for i, aid in enumerate(agent_ids):
            assert registry._agents[aid]["status"] == original_statuses[i]

    def test_batch_update_missing_agent_id(self, registry):
        updates = [{"status": "running"}]
        with pytest.raises(ValueError, match="not found"):
            registry.batch_update(updates, operation="update_status")

    def test_batch_update_custom_operation_no_changes(self, registry):
        agent_ids = list(registry._agents.keys())
        updates = [{"agent_id": agent_ids[0], "status": "running"}]
        results = registry.batch_update(updates, operation="unknown_op")
        assert len(results) == 1
        assert results[0]["status"] == "updated"


AUTH = {"Authorization": "Bearer test-token-12345"}


class TestBatchUpdateAPI:
    def test_batch_post_valid_request(self, client):
        registry = client.app.dependency_overrides.get("registry")
        from src.api import routes as rt
        ids = list(rt.registry._agents.keys())
        payload = {
            "operation": "update_status",
            "entries": [
                {"agent_id": ids[0], "status": "running"},
                {"agent_id": ids[1], "status": "stopped"},
            ],
        }
        resp = client.post("/api/v2/agents/batch", json=payload, headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["results"]) == 2

    def test_batch_post_empty_entries_rejected(self, client):
        resp = client.post("/api/v2/agents/batch", json={
            "operation": "update_status", "entries": [],
        }, headers=AUTH)
        assert resp.status_code == 422  # Pydantic validation

    def test_batch_post_unknown_agent_returns_422(self, client):
        payload = {
            "operation": "update_status",
            "entries": [
                {"agent_id": "nonexistent-999", "status": "running"},
            ],
        }
        resp = client.post("/api/v2/agents/batch", json=payload, headers=AUTH)
        assert resp.status_code == 422
        assert "not found" in resp.json()["detail"]

    def test_batch_post_missing_agent_id_rejected(self, client):
        resp = client.post("/api/v2/agents/batch", json={
            "operation": "update_status",
            "entries": [{"status": "running"}],
        }, headers=AUTH)
        assert resp.status_code == 422  # Pydantic validation for required field

    def test_batch_post_malformed_body_rejected(self, client):
        resp = client.post("/api/v2/agents/batch", json={"bad": "data"}, headers=AUTH)
        assert resp.status_code == 422

    def test_batch_post_unknown_operation_still_validates(self, client):
        """Operation type is validated at registry level, but agent IDs first."""
        payload = {
            "operation": "bogus_op",
            "entries": [{"agent_id": "nonexistent", "status": "running"}],
        }
        resp = client.post("/api/v2/agents/batch", json=payload, headers=AUTH)
        assert resp.status_code == 422
        assert "not found" in resp.json()["detail"]

    def test_batch_post_idempotent_no_changes_on_failure(self, client):
        from src.api import routes as rt
        ids = list(rt.registry._agents.keys())
        original = {aid: rt.registry._agents[aid]["status"] for aid in ids}

        payload = {
            "operation": "update_status",
            "entries": [
                {"agent_id": ids[0], "status": "running"},
                {"agent_id": "bad-id", "status": "stopped"},
            ],
        }
        resp = client.post("/api/v2/agents/batch", json=payload, headers=AUTH)
        assert resp.status_code == 422

        for aid in ids:
            assert rt.registry._agents[aid]["status"] == original[aid]


class TestBatchPydanticValidation:
    def test_entries_exceed_max_100(self):
        from src.api.routes import BatchUpdateRequest
        with pytest.raises(Exception):
            BatchUpdateRequest(
                operation="update_status",
                entries=[{"agent_id": "x"} for _ in range(101)],
            )

    def test_empty_agent_id_rejected(self):
        from src.api.routes import BatchUpdateEntry
        with pytest.raises(Exception):
            BatchUpdateEntry(agent_id="")

    def test_valid_entry_accepted(self):
        from src.api.routes import BatchUpdateEntry, BatchUpdateRequest
        entry = BatchUpdateEntry(agent_id="abc-123", status="running")
        assert entry.agent_id == "abc-123"
        assert entry.status == "running"

        req = BatchUpdateRequest(operation="update_status", entries=[entry])
        assert len(req.entries) == 1
