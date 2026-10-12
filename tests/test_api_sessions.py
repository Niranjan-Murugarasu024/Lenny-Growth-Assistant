from __future__ import annotations

import uuid
from fastapi import status


def test_create_session(api_client) -> None:
    payload = {
        "title": "Growth Strategy Session",
        "user_metadata": {"client": "test_suite", "env": "testing"},
    }
    resp = api_client.post("/api/v1/sessions", json=payload)
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()

    assert "id" in data
    assert data["title"] == "Growth Strategy Session"
    assert data["user_metadata"] == {"client": "test_suite", "env": "testing"}
    assert "created_at" in data
    assert "updated_at" in data


def test_create_session_empty_payload(api_client) -> None:
    resp = api_client.post("/api/v1/sessions", json={})
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    assert "id" in data
    assert data["title"] is None
    assert data["user_metadata"] is None


def test_list_sessions(api_client) -> None:
    # Create two sessions
    resp1 = api_client.post("/api/v1/sessions", json={"title": "Session 1"})
    resp2 = api_client.post("/api/v1/sessions", json={"title": "Session 2"})
    assert resp1.status_code == status.HTTP_201_CREATED
    assert resp2.status_code == status.HTTP_201_CREATED

    list_resp = api_client.get("/api/v1/sessions")
    assert list_resp.status_code == status.HTTP_200_OK
    data = list_resp.json()

    assert data["total"] >= 2
    session_ids = [s["id"] for s in data["sessions"]]
    assert resp1.json()["id"] in session_ids
    assert resp2.json()["id"] in session_ids


def test_get_session_messages_not_found(api_client) -> None:
    fake_id = str(uuid.uuid4())
    resp = api_client.get(f"/api/v1/sessions/{fake_id}/messages")
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    data = resp.json()
    assert data["error"]["code"] == "SESSION_NOT_FOUND"


def test_get_session_messages_empty(api_client) -> None:
    create_resp = api_client.post("/api/v1/sessions", json={"title": "Empty Session"})
    session_id = create_resp.json()["id"]

    resp = api_client.get(f"/api/v1/sessions/{session_id}/messages")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["session_id"] == session_id
    assert data["messages"] == []
