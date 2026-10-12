from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import status
from sqlalchemy.exc import OperationalError

from backend.app.api.deps import get_db, get_ollama_client
from backend.app.api.main import app
from backend.app.rag.ollama_client import OllamaChatClient


def test_health_live(api_client) -> None:
    resp = api_client.get("/health/live")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "lenny-growth-assistant"


def test_health_ready_success(api_client) -> None:
    resp = api_client.get("/health/ready")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["status"] == "ready"
    assert data["database"]["status"] == "connected"
    assert data["inference"]["provider"] == "ollama"
    assert data["inference"]["configured_model"] in ("qwen2.5:1.5b", "qwen3.5:9b")
    assert data["inference"]["status"] == "available"


def test_health_ready_ollama_unavailable(api_client) -> None:
    mock_client = MagicMock(spec=OllamaChatClient)
    mock_client.check_server_health.return_value = {
        "available": False,
        "error": "connection_refused",
        "models": [],
        "model_available": False,
    }

    app.dependency_overrides[get_ollama_client] = lambda: mock_client
    try:
        resp = api_client.get("/health/ready")
        assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        data = resp.json()
        assert data["error"]["code"] == "HTTP_ERROR" or "status" in data["error"]
    finally:
        app.dependency_overrides.pop(get_ollama_client, None)


def test_health_ready_db_failure(api_client) -> None:
    def _failing_db():
        mock_session = MagicMock()
        mock_session.execute.side_effect = OperationalError("connection failure", {}, Exception())
        yield mock_session

    app.dependency_overrides[get_db] = _failing_db
    try:
        resp = api_client.get("/health/ready")
        assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    finally:
        app.dependency_overrides.pop(get_db, None)
