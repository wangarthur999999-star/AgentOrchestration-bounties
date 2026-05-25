"""Tests for SDK client 204 No Content response handling."""

import json
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError

import pytest

from src.sdk.client import OrchestratorClient


def _http_error(code=500):
    return HTTPError("url", code, "Error", {}, None)


class Test204ResponseHandling:
    def test_delete_returns_success_on_204(self):
        client = OrchestratorClient()
        mock_resp = MagicMock()
        mock_resp.status = 204
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("src.sdk.client.urlopen", return_value=mock_resp):
            result = client.delete_agent("agent-123")
        assert result == {"success": True}

    def test_204_no_json_decode_attempted(self):
        client = OrchestratorClient()
        mock_resp = MagicMock()
        mock_resp.status = 204
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("src.sdk.client.urlopen", return_value=mock_resp):
            client.delete_agent("agent-123")
        mock_resp.read.assert_not_called()

    def test_non_204_still_decodes_json(self):
        client = OrchestratorClient()
        expected = {"id": "agent-1", "name": "test"}
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps(expected).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("src.sdk.client.urlopen", return_value=mock_resp):
            result = client.get_agent("agent-1")
        assert result == expected

    def test_200_response_decoded_correctly(self):
        client = OrchestratorClient()
        expected = {"agents": [], "count": 0}
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps(expected).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("src.sdk.client.urlopen", return_value=mock_resp):
            result = client.list_agents()
        assert result == expected


class TestHTTPErrorHandling:
    def test_404_returns_error_dict(self):
        client = OrchestratorClient()

        with patch("src.sdk.client.urlopen", side_effect=_http_error(404)):
            result = client.get_agent("nonexistent")
        assert result == {"error": 404, "message": "Error"}

    def test_500_returns_error_dict(self):
        client = OrchestratorClient()

        with patch("src.sdk.client.urlopen", side_effect=_http_error(500)):
            result = client.list_agents()
        assert result == {"error": 500, "message": "Error"}


class TestDeleteEndToEnd:
    def test_delete_uses_delete_method(self):
        client = OrchestratorClient()
        mock_resp = MagicMock()
        mock_resp.status = 204
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("src.sdk.client.urlopen", return_value=mock_resp) as mock_urlopen:
            client.delete_agent("agent-xyz")

        call_args = mock_urlopen.call_args[0][0]
        assert call_args.method == "DELETE"
        assert "/agents/agent-xyz" in call_args.full_url

    def test_201_still_decodes_json(self):
        client = OrchestratorClient()
        expected = {"id": "new-agent", "name": "created"}
        mock_resp = MagicMock()
        mock_resp.status = 201
        mock_resp.read.return_value = json.dumps(expected).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("src.sdk.client.urlopen", return_value=mock_resp):
            result = client.register_agent("created", "type")
        assert result == expected


class Test204EdgeCases:
    def test_multiple_deletes_all_return_success(self):
        client = OrchestratorClient()
        mock_resp = MagicMock()
        mock_resp.status = 204
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("src.sdk.client.urlopen", return_value=mock_resp):
            for agent_id in ["a", "b", "c"]:
                result = client.delete_agent(agent_id)
                assert result == {"success": True}

    def test_204_response_is_plain_dict(self):
        client = OrchestratorClient()
        mock_resp = MagicMock()
        mock_resp.status = 204
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("src.sdk.client.urlopen", return_value=mock_resp):
            result = client.delete_agent("x")
        assert isinstance(result, dict)
        assert "success" in result
        assert result["success"] is True
