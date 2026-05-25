"""Tests for registry locality filtering — bounty #3933."""

import pytest

from src.agent.registry import AgentRegistry, AgentStatus


@pytest.fixture
def registry():
    return AgentRegistry()


class TestLocalityRegistration:
    def test_register_with_locality(self, registry):
        agent_id = registry.register("worker-1", "worker.cpu", locality="us-east-1")
        agent = registry.get(agent_id)
        assert agent["locality"] == "us-east-1"

    def test_register_without_locality(self, registry):
        agent_id = registry.register("worker-2", "worker.gpu")
        agent = registry.get(agent_id)
        assert agent["locality"] is None

    def test_locality_index_populated(self, registry):
        registry.register("w1", "worker.cpu", locality="us-east-1")
        registry.register("w2", "worker.cpu", locality="us-east-1")
        assert len(registry._locality_index["us-east-1"]) == 2

    def test_locality_not_in_index_when_none(self, registry):
        registry.register("w1", "worker.cpu")
        assert "None" not in registry._locality_index
        assert None not in registry._locality_index


class TestListByLocality:
    def test_list_filters_by_locality(self, registry):
        registry.register("east-1", "worker.cpu", locality="us-east-1")
        registry.register("west-1", "worker.cpu", locality="us-west-1")

        east = registry.list(locality="us-east-1")
        assert len(east) == 1
        assert east[0]["name"] == "east-1"

        west = registry.list(locality="us-west-1")
        assert len(west) == 1
        assert west[0]["name"] == "west-1"

    def test_list_unknown_locality_returns_empty(self, registry):
        registry.register("w1", "worker.cpu", locality="us-east-1")
        result = registry.list(locality="eu-west-1")
        assert result == []

    def test_list_combines_locality_and_status(self, registry):
        rid1 = registry.register("w1", "worker.cpu", locality="us-east-1")
        registry.register("w2", "worker.cpu", locality="us-east-1")
        registry.update_status(rid1, AgentStatus.RUNNING)

        result = registry.list(status=AgentStatus.RUNNING, locality="us-east-1")
        assert len(result) == 1
        assert result[0]["name"] == "w1"

    def test_list_combines_locality_and_group(self, registry):
        registry.register("w1", "worker.cpu", locality="us-east-1")
        registry.register("w2", "worker.gpu", locality="us-east-1")

        result = registry.list(group="worker", locality="us-east-1")
        assert len(result) == 2


class TestFilterByLocality:
    def test_filter_returns_matching_agents(self, registry):
        registry.register("e1", "worker.cpu", locality="us-east-1")
        registry.register("e2", "worker.gpu", locality="us-east-1")
        registry.register("w1", "worker.cpu", locality="us-west-1")

        east = registry.filter_by_locality("us-east-1")
        assert len(east) == 2
        names = {a["name"] for a in east}
        assert names == {"e1", "e2"}

    def test_filter_unknown_locality_returns_empty(self, registry):
        assert registry.filter_by_locality("nonexistent") == []

    def test_filter_excludes_deleted_agents(self, registry):
        aid = registry.register("temp", "worker.cpu", locality="us-east-1")
        registry.delete(aid)
        assert registry.filter_by_locality("us-east-1") == []


class TestResolveLocality:
    def test_resolve_matching_locality(self, registry):
        aid = registry.register("w1", "worker.cpu", locality="us-east-1")
        assert registry.resolve_locality(aid, "us-east-1") is True

    def test_resolve_mismatched_locality(self, registry):
        aid = registry.register("w1", "worker.cpu", locality="us-east-1")
        assert registry.resolve_locality(aid, "us-west-1") is False

    def test_resolve_none_locality_agent(self, registry):
        aid = registry.register("w1", "worker.cpu")
        assert registry.resolve_locality(aid, "us-east-1") is False

    def test_resolve_nonexistent_agent(self, registry):
        assert registry.resolve_locality("fake-id", "us-east-1") is False


class TestSetLocality:
    def test_set_locality_updates_agent(self, registry):
        aid = registry.register("w1", "worker.cpu")
        assert registry.set_locality(aid, "us-east-1") is True
        assert registry.get(aid)["locality"] == "us-east-1"

    def test_set_locality_updates_index(self, registry):
        aid = registry.register("w1", "worker.cpu")
        registry.set_locality(aid, "us-east-1")
        assert aid in registry._locality_index["us-east-1"]

    def test_set_locality_invalidates_old_index(self, registry):
        aid = registry.register("w1", "worker.cpu", locality="us-east-1")
        registry.set_locality(aid, "us-west-1")
        assert aid not in registry._locality_index.get("us-east-1", [])
        assert aid in registry._locality_index["us-west-1"]

    def test_set_locality_idempotent(self, registry):
        aid = registry.register("w1", "worker.cpu", locality="us-east-1")
        assert registry.set_locality(aid, "us-east-1") is True
        assert len(registry._locality_index["us-east-1"]) == 1

    def test_set_locality_nonexistent_agent(self, registry):
        assert registry.set_locality("fake-id", "us-east-1") is False


class TestDeleteLocalityCleanup:
    def test_delete_removes_from_locality_index(self, registry):
        aid = registry.register("w1", "worker.cpu", locality="us-east-1")
        registry.delete(aid)
        assert aid not in registry._locality_index.get("us-east-1", [])

    def test_delete_agent_without_locality(self, registry):
        aid = registry.register("w1", "worker.cpu")
        assert registry.delete(aid) is True
