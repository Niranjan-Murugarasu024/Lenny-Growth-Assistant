"""
API integration tests for writing essay endpoints, artifacts, versions, and revisions.
"""
from __future__ import annotations

from unittest.mock import MagicMock
import uuid
from fastapi import status
import pytest

from backend.app.api.deps import get_app_settings
from backend.app.api.main import app
from backend.app.api.routes.writing import get_writing_service
from backend.app.config import load_settings
from backend.app.models import (
    ChatSession,
    Episode,
    TranscriptChunk,
    WritingArtifact,
    WritingArtifactVersion,
    WritingJob,
)

from backend.app.rag.provider_base import ChatProvider
from backend.app.retrieval.search import SearchResult
from backend.app.writing.job_runner import DurableEssayJobManager
from backend.app.writing.schemas import WritingBriefRequest
from backend.app.writing.service import WritingService



def test_brief_validation_rejects_empty_or_invalid_fields(api_client):
    # Blank topic -> 422
    resp1 = api_client.post("/api/v1/writing/essays", json={"topic": "   "})
    assert resp1.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Unsupported word count (too low) -> 422
    resp2 = api_client.post(
        "/api/v1/writing/essays",
        json={"topic": "Good Topic", "target_word_count": 200},
    )
    assert resp2.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Unsupported word count (too high) -> 422
    resp3 = api_client.post(
        "/api/v1/writing/essays",
        json={"topic": "Good Topic", "target_word_count": 5000},
    )
    assert resp3.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Invalid tone -> 422
    resp4 = api_client.post(
        "/api/v1/writing/essays",
        json={"topic": "Good Topic", "tone": "sarcastic"},
    )
    assert resp4.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_brief_rejects_nonexistent_session_id(api_client):
    fake_session_id = str(uuid.uuid4())
    resp = api_client.post(
        "/api/v1/writing/essays",
        json={"topic": "Valid Topic Here", "session_id": fake_session_id},
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_submit_async_essay_job_and_poll_status(api_client):
    mock_ws = MagicMock(spec=WritingService)
    app.dependency_overrides[get_writing_service] = lambda: mock_ws
    try:
        resp = api_client.post(
            "/api/v1/writing/essays",
            json={"topic": f"How to scale sales engineering {uuid.uuid4().hex[:6]}"},
        )
        assert resp.status_code == status.HTTP_202_ACCEPTED
        data = resp.json()
        job_id = data["job_id"]
        assert job_id.startswith("job_")
        assert data["status"] in ("queued", "running")

        # Poll status
        poll_resp = api_client.get(f"/api/v1/writing/jobs/{job_id}")
        assert poll_resp.status_code == status.HTTP_200_OK
        assert poll_resp.json()["job_id"] == job_id
    finally:
        app.dependency_overrides.pop(get_writing_service, None)


def test_poll_unknown_job_returns_404(api_client):
    resp = api_client.get("/api/v1/writing/jobs/job_unknown_12345")
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_sync_essay_generation_and_full_crud(api_client, db_session_factory):
    # 1. Seed DB with an episode and chunk
    with db_session_factory() as session:
        ep = Episode(
            source_path="episodes/brian-chesky/transcript.md",
            guest="Brian Chesky",
            title="Design and Crisis",
            source_sha256="sha_bc1",
            body_sha256="sha_bc2",
        )
        session.add(ep)
        session.commit()
        session.refresh(ep)

        chunk = TranscriptChunk(
            episode_id=ep.id,
            chunk_index=1,
            chunk_text="You must focus on the 11-star experience and design backwards.",
            chunk_sha256="c_sha_bc1",
            token_count=12,
            character_count=65,
        )
        session.add(chunk)
        session.commit()
        session.refresh(chunk)
        chunk_id = chunk.id

    # 2. Mock ChatProvider
    mock_chat = MagicMock(spec=ChatProvider)
    mock_chat.name = "mock-ollama"
    mock_chat.model = "qwen3.5:9b"

    def _build_test_doc(title: str, cid: int, target_wc: int = 500) -> str:
        intro = (
            f"# {title}\n\n"
            "At its core, the argument is that crafting an extreme product experience unlocks non-linear growth [Source 1].\n\n"
            "## 1. The 11-Star Mindset\n"
            "Brian Chesky describes building a customer experience so transcendent that users cannot stop talking about it.\n\n"
            "## 2. Customer Co-Creation\n"
            "Direct observation of customer pain points reveals structural opportunities.\n\n"
            "## Conclusion and Key Takeaways\n"
            "Exceptional products win through organic word-of-mouth.\n\n"
        )
        body = intro + " ".join(["retention"] * (target_wc - 60))
        refs = f"\n\n## References\n[Source 1] Brian Chesky - Design and Crisis (Chunk #{cid})"
        return body + refs

    mock_essay_content = _build_test_doc("Designing Exceptional Experiences", chunk_id, target_wc=500)
    mock_chat.generate_chat_response.return_value = {
        "content": mock_essay_content,
        "provider": "mock-ollama",
        "model": "qwen3.5:9b",
    }

    # Custom writing service with mock provider
    custom_ws = WritingService(
        session_factory=db_session_factory,
        chat_client=mock_chat,
    )
    # Also mock research to return our seeded chunk
    custom_ws.research = MagicMock(return_value=([
        SearchResult(
            chunk_id=chunk_id,
            chunk_index=1,
            chunk_text="You must focus on the 11-star experience and design backwards.",
            cosine_distance=0.15,
            guest="Brian Chesky",
            title="Design and Crisis",
            source_path="episodes/brian-chesky/transcript.md",
            speaker="Brian",
            start_time_seconds=120.0,
            timestamp="00:02:00",
            embedding_model="nomic-embed-text:v1.5",
        )
    ], True))

    app.dependency_overrides[get_writing_service] = lambda: custom_ws

    try:
        # Submit synchronous generation targeting 500 words
        resp = api_client.post(
            "/api/v1/writing/essays?sync=true",
            json={"topic": "Designing Exceptional Experiences", "target_word_count": 500},
        )
        assert resp.status_code == status.HTTP_202_ACCEPTED
        job_data = resp.json()
        assert job_data["status"] == "completed"
        artifact_id = job_data["artifact_id"]
        assert artifact_id is not None

        # Retrieve artifact
        art_resp = api_client.get(f"/api/v1/writing/artifacts/{artifact_id}")
        assert art_resp.status_code == status.HTTP_200_OK
        art_data = art_resp.json()
        assert art_data["title"] == "Designing Exceptional Experiences"
        assert art_data["status"] == "completed"
        latest = art_data["latest_version"]
        assert latest["version_number"] == 1
        assert "Designing Exceptional Experiences" in latest["markdown_content"]
        assert "<h1>Designing Exceptional Experiences</h1>" in latest["html_content"]
        assert latest["eval_metadata"]["checks"]["citations"]["all_verified"] is True
        assert chunk_id in latest["eval_metadata"]["checks"]["citations"]["verified_chunk_ids"]

        # Retrieve versions list
        vers_resp = api_client.get(f"/api/v1/writing/artifacts/{artifact_id}/versions")
        assert vers_resp.status_code == status.HTTP_200_OK
        v_list = vers_resp.json()["versions"]
        assert len(v_list) == 1
        assert v_list[0]["version_number"] == 1

        # Retrieve specific version 1
        v1_resp = api_client.get(f"/api/v1/writing/artifacts/{artifact_id}/versions/1")
        assert v1_resp.status_code == status.HTTP_200_OK
        assert v1_resp.json()["version_number"] == 1

        # Test revision
        mock_revision_content = _build_test_doc("Designing Exceptional Experiences (Revised)", chunk_id, target_wc=500)
        mock_chat.generate_chat_response.return_value = {
            "content": mock_revision_content,
            "provider": "mock-ollama",
            "model": "qwen3.5:9b",
        }

        rev_resp = api_client.post(
            f"/api/v1/writing/artifacts/{artifact_id}/revisions?sync=true",
            json={"instructions": "Add more tactical examples to section 2", "target_word_count": 500},
        )
        assert rev_resp.status_code == status.HTTP_201_CREATED
        rev_data = rev_resp.json()
        assert rev_data["latest_version"]["version_number"] == 2
        assert "Revised" in rev_data["latest_version"]["markdown_content"]

        # Check versions list now has 2 versions
        vers2_resp = api_client.get(f"/api/v1/writing/artifacts/{artifact_id}/versions")
        assert len(vers2_resp.json()["versions"]) == 2

    finally:
        app.dependency_overrides.pop(get_writing_service, None)


def test_essay_generation_fails_when_word_count_out_of_range(api_client, db_session_factory):
    """
    Test that an initial draft with 1,722 words for target 1,250 fails acceptance,
    triggers bounded revision which also fails, and marks the job failed.
    Never returns completed for an essay that fails a mandatory criterion!
    """
    with db_session_factory() as session:
        ep = Episode(
            source_path="episodes/brian/test.md",
            guest="Brian",
            title="Design",
            source_sha256="s1",
            body_sha256="s2",
        )
        session.add(ep)
        session.commit()
        session.refresh(ep)
        chunk = TranscriptChunk(
            episode_id=ep.id,
            chunk_index=0,
            chunk_text="Insight here.",
            chunk_sha256="c1",
            token_count=5,
            character_count=20,
        )
        session.add(chunk)
        session.commit()
        session.refresh(chunk)
        chunk_id = chunk.id

    mock_chat = MagicMock(spec=ChatProvider)
    mock_chat.name = "mock-ollama"
    mock_chat.model = "qwen3.5:9b"
    # Output 1,722 words (body)
    intro = (
        "# 11-Star Product Framework\n\n"
        "At its core, the argument is that customer delight drives non-linear growth [Source 1].\n\n"
        "## 1. First Section\n\n## 2. Second Section\n\n"
    )
    long_body = intro + " ".join(["expansion"] * 1680)
    out_of_range_doc = long_body + f"\n\n## References\n[Source 1] Brian - Design (Chunk #{chunk_id})"

    mock_chat.generate_chat_response.return_value = {
        "content": out_of_range_doc,
        "provider": "mock-ollama",
        "model": "qwen3.5:9b",
    }

    custom_ws = WritingService(
        session_factory=db_session_factory,
        chat_client=mock_chat,
    )
    custom_ws.research = MagicMock(return_value=([
        SearchResult(
            chunk_id=chunk_id,
            chunk_index=0,
            chunk_text="Insight here.",
            cosine_distance=0.10,
            guest="Brian",
            title="Design",
            source_path="episodes/brian/test.md",
            speaker="Brian",
            start_time_seconds=0.0,
            timestamp="00:00:00",
            embedding_model="nomic",
        )
    ], True))

    app.dependency_overrides[get_writing_service] = lambda: custom_ws
    try:
        resp = api_client.post(
            "/api/v1/writing/essays?sync=true",
            json={"topic": "11-Star Product Framework", "target_word_count": 1250},
        )
        assert resp.status_code == status.HTTP_202_ACCEPTED
        data = resp.json()
        assert data["status"] == "failed"
        assert "outside acceptable target range [1125, 1375]" in data["error"]
        artifact_id = data["artifact_id"]

        # Confirm artifact is preserved in failed state
        art_resp = api_client.get(f"/api/v1/writing/artifacts/{artifact_id}")
        assert art_resp.status_code == status.HTTP_200_OK
        art_data = art_resp.json()
        assert art_data["status"] == "failed"
        assert art_data["latest_version"]["eval_metadata"]["passed"] is False
        assert art_data["latest_version"]["eval_metadata"]["word_count_in_range"] is False
    finally:
        app.dependency_overrides.pop(get_writing_service, None)


def test_essay_generation_bounded_revision_recovers_to_target_range(api_client, db_session_factory):
    """
    Test that when initial draft is out of range, bounded revision produces
    a compliant draft, which is accepted and marked completed.
    """
    with db_session_factory() as session:
        ep = Episode(source_path="episodes/e/t.md", guest="G", title="T", source_sha256="s3", body_sha256="s4")
        session.add(ep)
        session.commit()
        session.refresh(ep)
        chunk = TranscriptChunk(episode_id=ep.id, chunk_index=0, chunk_text="Text", chunk_sha256="c2", token_count=4, character_count=10)
        session.add(chunk)
        session.commit()
        session.refresh(chunk)
        chunk_id = chunk.id

    mock_chat = MagicMock(spec=ChatProvider)
    mock_chat.name = "mock-ollama"
    mock_chat.model = "qwen3.5:9b"
    # Draft 1: 1,722 words (fails)
    intro = "# Framework\n\nAt its core, the argument is simple [Source 1].\n\n## 1. S1\n\n## 2. S2\n\n"
    d1 = intro + " ".join(["repeat"] * 1680) + f"\n\n## References\n[Source 1] G - T (Chunk #{chunk_id})"

    # Draft 2 (Revision): 1,250 words (passes)
    d2 = intro + " ".join(["good"] * 1200) + f"\n\n## References\n[Source 1] G - T (Chunk #{chunk_id})"

    mock_chat.generate_chat_response.side_effect = [
        {"content": d1, "provider": "mock", "model": "qwen"},
        {"content": d2, "provider": "mock", "model": "qwen"},
    ]

    custom_ws = WritingService(session_factory=db_session_factory, chat_client=mock_chat)
    custom_ws.research = MagicMock(return_value=([
        SearchResult(chunk_id=chunk_id, chunk_index=0, chunk_text="Text", cosine_distance=0.1, guest="G", title="T", source_path="episodes/e/t.md", speaker="G", start_time_seconds=0.0, timestamp="00:00", embedding_model="nomic")
    ], True))

    app.dependency_overrides[get_writing_service] = lambda: custom_ws
    try:
        resp = api_client.post(
            "/api/v1/writing/essays?sync=true",
            json={"topic": "Framework", "target_word_count": 1250},
        )
        assert resp.status_code == status.HTTP_202_ACCEPTED
        data = resp.json()
        assert data["status"] == "completed"
        assert data["artifact_id"] is not None

        art_resp = api_client.get(f"/api/v1/writing/artifacts/{data['artifact_id']}")
        assert art_resp.json()["status"] == "completed"
        assert art_resp.json()["latest_version"]["eval_metadata"]["passed"] is True
    finally:
        app.dependency_overrides.pop(get_writing_service, None)


def test_essay_generation_fails_on_fabricated_citation(api_client, db_session_factory):
    """
    Test that an essay citing fake uncollected [Source 999] fails evaluation
    and cannot be marked completed.
    """
    with db_session_factory() as session:
        ep = Episode(source_path="episodes/e/f.md", guest="G", title="T", source_sha256="s5", body_sha256="s6")
        session.add(ep)
        session.commit()
        session.refresh(ep)
        chunk = TranscriptChunk(episode_id=ep.id, chunk_index=0, chunk_text="Text", chunk_sha256="c3", token_count=4, character_count=10)
        session.add(chunk)
        session.commit()
        session.refresh(chunk)
        chunk_id = chunk.id

    mock_chat = MagicMock(spec=ChatProvider)
    mock_chat.name = "mock-ollama"
    mock_chat.model = "qwen3.5:9b"
    # Draft with [Source 999]
    intro = "# Fabricated\n\nAt its core, the argument relies on a fake claim [Source 999].\n\n## 1. S1\n\n## 2. S2\n\n"
    d = intro + " ".join(["words"] * 450) + f"\n\n## References\n[Source 999] Fake (Chunk #999)"
    mock_chat.generate_chat_response.return_value = {"content": d, "provider": "mock", "model": "qwen"}

    custom_ws = WritingService(session_factory=db_session_factory, chat_client=mock_chat)
    custom_ws.research = MagicMock(return_value=([
        SearchResult(chunk_id=chunk_id, chunk_index=0, chunk_text="Text", cosine_distance=0.1, guest="G", title="T", source_path="episodes/e/f.md", speaker="G", start_time_seconds=0.0, timestamp="00:00", embedding_model="nomic")
    ], True))

    app.dependency_overrides[get_writing_service] = lambda: custom_ws
    try:
        resp = api_client.post(
            "/api/v1/writing/essays?sync=true",
            json={"topic": "Fabricated", "target_word_count": 500},
        )
        assert resp.status_code == status.HTTP_202_ACCEPTED
        data = resp.json()
        assert data["status"] == "failed"
        assert "Unverified or untraced citations detected" in data["error"]
    finally:
        app.dependency_overrides.pop(get_writing_service, None)


def test_manual_edit_54_words_maintains_version_integrity(api_client, db_session_factory):
    """
    Test that saving a 54-word manual edit on a long-form essay creates v2
    with word_count=54 and word_count_in_range=False, while v1 retains its
    original word count and criteria without misleading the user.
    """
    with db_session_factory() as session:
        art = WritingArtifact(title="Long Form Essay", status="completed")
        session.add(art)
        session.flush()

        v1_text = (
            "# Long Form Essay\n\n"
            "At its core, the argument is that viral loops scale companies.\n\n"
            "## 1. Foundation\n\n## 2. Metrics\n\n"
            + " ".join(["scale"] * 450)
            + "\n\n## References\nNone"
        )
        v1 = WritingArtifactVersion(
            artifact_id=art.id,
            version_number=1,
            markdown_content=v1_text,
            html_content="<h1>Long Form Essay</h1>",
            word_count=480,
            writing_brief={"topic": "Long Form Essay", "target_word_count": 500},
            sources=[],
            eval_metadata={"passed": True, "word_count_in_range": True, "body_word_count": 480},
            model_metadata={"provider": "test"},
        )
        session.add(v1)
        session.commit()
        session.refresh(art)
        art_id = str(art.id)

    # Save a 54-word manual edit as v2
    v2_text = (
        "# Short Edit\n\n"
        "Here is a brief summary consisting of only fifty-four words. "
        "We are deliberately saving a concise summary note instead of a full long-form essay.\n\n"
        "## 1. Quick Takeaway\n"
        "Editorial flexibility allows saving quick scratch thoughts.\n\n"
        "## Conclusion\n"
        "Done.\n\n"
        "## References\n"
        "None"
    )
    resp = api_client.post(
        f"/api/v1/writing/artifacts/{art_id}/versions",
        json={"markdown_content": v2_text, "note": "Brief draft summary"},
    )
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    assert data["latest_version"]["version_number"] == 2
    assert data["latest_version"]["word_count"] < 100
    # Mandatory word count check for 500-word target is False for 54 words
    assert data["latest_version"]["eval_metadata"]["word_count_in_range"] is False

    # Historical version 1 remains unchanged with its original 480 words
    v1_resp = api_client.get(f"/api/v1/writing/artifacts/{art_id}/versions/1")
    assert v1_resp.status_code == status.HTTP_200_OK
    assert v1_resp.json()["word_count"] == 480
    assert v1_resp.json()["eval_metadata"]["word_count_in_range"] is True



def test_get_unknown_artifact_returns_404(api_client):
    fake_id = str(uuid.uuid4())
    resp = api_client.get(f"/api/v1/writing/artifacts/{fake_id}")
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json()["error"]["code"] == "ARTIFACT_NOT_FOUND"


def test_get_unknown_version_returns_404(api_client, db_session_factory):
    with db_session_factory() as session:
        art = WritingArtifact(title="Test Artifact")
        session.add(art)
        session.commit()
        session.refresh(art)
        art_id = str(art.id)

    resp = api_client.get(f"/api/v1/writing/artifacts/{art_id}/versions/99")
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json()["error"]["code"] == "VERSION_NOT_FOUND"


def test_preview_markdown_endpoint(api_client):
    md = (
        "# Preview Header\n\n"
        "This is a paragraph with **bold** and *italic* text.\n\n"
        "<script>alert('xss')</script>\n\n"
        "## References\n"
        "[Source 1] Some guest"
    )
    resp = api_client.post("/api/v1/writing/preview", json={"markdown_content": md})
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert "html_content" in data
    assert "Preview Header" in data["html_content"]
    assert "<script>" not in data["html_content"]
    assert "alert" not in data["html_content"]
    assert data["word_count"] > 0


def test_list_artifacts_and_save_manual_version(api_client, db_session_factory):
    # 1. Seed artifact and version 1
    with db_session_factory() as session:
        art = WritingArtifact(title="Manual Edit Test", status="completed")
        session.add(art)
        session.flush()

        ver1 = WritingArtifactVersion(
            artifact_id=art.id,
            version_number=1,
            markdown_content="# Initial Title\n\nIntroductory text for the article.\n\n## References\nNone",
            html_content="<h1>Initial Title</h1>",
            word_count=5,
            writing_brief={"topic": "Manual Edit Test", "target_word_count": 1250},
            sources=[],
            eval_metadata={},
            model_metadata={"provider": "test"},
        )
        session.add(ver1)
        session.commit()
        session.refresh(art)
        art_id = str(art.id)

    # 2. Test list artifacts
    list_resp = api_client.get("/api/v1/writing/artifacts")
    assert list_resp.status_code == status.HTTP_200_OK
    list_data = list_resp.json()
    assert list_data["total"] >= 1
    found = next((a for a in list_data["artifacts"] if a["id"] == art_id), None)
    assert found is not None
    assert found["title"] == "Manual Edit Test"
    assert found["latest_version_number"] == 1
    assert found["latest_word_count"] == 5

    # 3. Test save manual version (creates v2)
    new_md = (
        "# Manual Edit Title (Updated)\n\n"
        "We argue that manual editing gives writers fine-grained precision over their prose.\n\n"
        "## 1. Deep Craft\n"
        "Writers refine nuance and cadence.\n\n"
        "## 2. Iteration Speed\n"
        "Fast feedback loops empower creation.\n\n"
        "## Conclusion\n"
        "Manual refinement produces timeless clarity.\n\n"
        "## References\n"
        "None"
    )
    save_resp = api_client.post(
        f"/api/v1/writing/artifacts/{art_id}/versions",
        json={"markdown_content": new_md, "note": "Polished section headings"},
    )
    assert save_resp.status_code == status.HTTP_201_CREATED
    save_data = save_resp.json()
    assert save_data["latest_version"]["version_number"] == 2
    assert "Updated" in save_data["latest_version"]["markdown_content"]
    assert save_data["latest_version"]["model_metadata"]["author"] == "manual_edit"
    assert save_data["latest_version"]["model_metadata"]["note"] == "Polished section headings"

    # 4. Confirm versions list has 2 entries
    hist_resp = api_client.get(f"/api/v1/writing/artifacts/{art_id}/versions")
    assert len(hist_resp.json()["versions"]) == 2


def test_durable_job_idempotency_deduplication(db_session_factory) -> None:
    settings = load_settings(worker_concurrency=1)
    mgr = DurableEssayJobManager(settings=settings, session_factory=db_session_factory)
    mock_service = MagicMock(spec=WritingService)

    brief = WritingBriefRequest(topic="Durable Idempotency Test Topic", target_word_count=1250)
    key = "idem_test_key_123"

    job1 = mgr.submit_job(brief, mock_service, idempotency_key=key)
    job2 = mgr.submit_job(brief, mock_service, idempotency_key=key)

    assert job1.job_id == job2.job_id
    assert job1.idempotency_key == key


def test_durable_job_stale_recovery_requeues(db_session_factory) -> None:
    settings = load_settings(worker_concurrency=1, max_job_retries=2)
    mgr = DurableEssayJobManager(settings=settings, session_factory=db_session_factory)

    # Insert a stale running job directly in PostgreSQL
    with db_session_factory() as session:
        stale_job = WritingJob(
            id="job_stale_restart_test",
            topic="Stale Topic",
            status="running",
            stage="Drafting interrupted",
            target_word_count=1250,
            brief={"topic": "Stale Topic", "target_word_count": 1250},
            retry_count=0,
            max_retries=2,
        )
        session.add(stale_job)
        session.commit()

    recovered = mgr.recover_stale_jobs()
    assert recovered >= 1

    with db_session_factory() as session:
        job = session.get(WritingJob, "job_stale_restart_test")
        assert job is not None
        assert job.status == "queued"
        assert job.retry_count == 1
        assert "Recovered from restart" in job.stage


def test_durable_job_stale_recovery_exhausted_fails(db_session_factory) -> None:
    settings = load_settings(worker_concurrency=1, max_job_retries=2)
    mgr = DurableEssayJobManager(settings=settings, session_factory=db_session_factory)

    # Insert a running job that has already used all retries
    with db_session_factory() as session:
        exhausted_job = WritingJob(
            id="job_exhausted_restart_test",
            topic="Exhausted Topic",
            status="running",
            stage="Drafting crashed again",
            target_word_count=1250,
            brief={"topic": "Exhausted Topic", "target_word_count": 1250},
            retry_count=2,
            max_retries=2,
        )
        session.add(exhausted_job)
        session.commit()

    recovered = mgr.recover_stale_jobs()
    assert recovered >= 1

    with db_session_factory() as session:
        job = session.get(WritingJob, "job_exhausted_restart_test")
        assert job is not None
        assert job.status == "failed"
        assert "exceeded retry limit" in (job.error or "")


def test_durable_job_mandatory_evaluation_failure_never_completed(db_session_factory) -> None:
    from backend.app.writing.evaluator import EssayEvaluation

    settings = load_settings(worker_concurrency=1)
    mgr = DurableEssayJobManager(settings=settings, session_factory=db_session_factory)

    # Create mock service returning failed evaluation
    mock_service = MagicMock(spec=WritingService)
    mock_art = MagicMock()
    mock_art.id = uuid.uuid4()
    mock_ver = MagicMock()
    mock_ver.version_number = 1
    mock_ver.word_count = 800

    failed_eval = MagicMock(
        passed=False,
        checks={"word_count": False, "headings": True},
        feedback=["Word count 800 is below minimum 1000 threshold"],
    )
    mock_service.generate_and_persist_essay.return_value = (mock_art, mock_ver, failed_eval)


    brief = WritingBriefRequest(topic="Evaluation Failure Job Test", target_word_count=1250)
    job = mgr.submit_job(brief, mock_service, idempotency_key="eval_fail_test_key")

    # Directly execute job runner
    mgr._execute_job(job.job_id, brief, mock_service)

    updated_job = mgr.get_job(job.job_id)
    assert updated_job is not None
    assert updated_job.status == "failed"
    assert "Mandatory quality evaluation failed" in (updated_job.error or "")


def test_create_markdown_artifact_endpoint(api_client, db_session_factory):
    """Test directly persisting a Markdown artifact via POST /api/v1/writing/artifacts."""
    payload = {
        "title": "Onboarding Best Practices",
        "content": "# Onboarding Best Practices\n\n- Step 1: Clarify value proposition\n- Step 2: Minimize time to 'Aha!'",
        "artifact_type": "document",
    }
    resp = api_client.post("/api/v1/writing/artifacts", json=payload)
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    assert data["title"] == "Onboarding Best Practices"
    assert data["artifact_type"] == "document"
    assert data["status"] == "completed"
    assert data["latest_version"]["version_number"] == 1
    assert "Clarify value proposition" in data["latest_version"]["markdown_content"]
    assert "<h1>Onboarding Best Practices</h1>" in data["latest_version"]["html_content"]


def test_create_html_artifact_endpoint_with_sanitization(api_client, db_session_factory):
    """Test directly persisting an HTML artifact via POST /api/v1/writing/artifacts with server-side sanitization."""
    payload = {
        "title": "Interactive Metric Card",
        "content": (
            "<div class=\"metric-card\">"
            "<h2>Monthly Active Users</h2>"
            "<p>125,000</p>"
            "<script>alert('pwned')</script>"
            "<button onclick=\"stealData()\">Click me</button>"
            "<a href=\"javascript:alert(1)\">Evil Link</a>"
            "<a href=\"https://metrics.io\" title=\"Dashboard\">Dashboard</a>"
            "</div>"
        ),
        "artifact_type": "html",
    }
    resp = api_client.post("/api/v1/writing/artifacts", json=payload)
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    assert data["title"] == "Interactive Metric Card"
    assert data["artifact_type"] == "html"
    assert data["status"] == "completed"

    html_out = data["latest_version"]["html_content"]
    assert "<h2>Monthly Active Users</h2>" in html_out
    assert "<p>125,000</p>" in html_out
    assert "<script" not in html_out
    assert "onclick" not in html_out
    assert "javascript:" not in html_out
    assert '<a href="https://metrics.io"' in html_out
    assert 'rel="noopener noreferrer"' in html_out


def test_generate_markdown_artifact_from_conversation(api_client, db_session_factory):
    """Test generating a Markdown document from conversation context via POST /api/v1/writing/artifacts/generate."""
    from backend.app.models import ChatMessage

    # 1. Create a session with chat messages
    session_id = uuid.uuid4()
    with db_session_factory() as db:
        chat_sess = ChatSession(id=session_id)
        db.add(chat_sess)
        db.flush()

        m1 = ChatMessage(
            session_id=session_id,
            role="user",
            content="How do retention loops compare with traditional acquisition funnels?",
        )
        m2 = ChatMessage(
            session_id=session_id,
            role="assistant",
            content="Retention loops compound user growth by re-engaging users through habitual cycles. [Source 1]",
            model="test-chat-model",
            sources=[{"chunk_id": "chunk-101", "title": "Elena Verna on PLG"}],
        )
        db.add_all([m1, m2])
        db.commit()

    # 2. Mock WritingService's generate_artifact_from_conversation
    mock_ws = MagicMock(spec=WritingService)
    mock_art = MagicMock()
    mock_art.id = uuid.uuid4()
    mock_art.session_id = session_id
    mock_art.title = "Retention Loops vs Traditional Funnels"
    mock_art.artifact_type = "document"
    mock_art.status = "completed"
    mock_art.created_at = "2026-10-12T00:00:00Z"
    mock_art.updated_at = "2026-10-12T00:00:00Z"

    mock_ver = MagicMock()
    mock_ver.id = uuid.uuid4()
    mock_ver.artifact_id = mock_art.id
    mock_ver.version_number = 1
    mock_ver.markdown_content = "# Retention Loops vs Traditional Funnels\n\nCompounding growth beats linear funnels."
    mock_ver.html_content = "<div class=\"lenny-essay-preview\"><h1>Retention Loops vs Traditional Funnels</h1></div>"
    mock_ver.word_count = 120
    mock_ver.writing_brief = {"topic": "Retention"}
    mock_ver.sources = [{"chunk_id": "chunk-101", "title": "Elena Verna on PLG"}]
    mock_ver.eval_metadata = {"passed": True}
    mock_ver.model_metadata = {"model": "test-chat-model"}
    mock_ver.created_at = "2026-10-12T00:00:00Z"

    mock_ws.generate_artifact_from_conversation.return_value = (mock_art, mock_ver)
    app.dependency_overrides[get_writing_service] = lambda: mock_ws

    try:
        resp = api_client.post(
            "/api/v1/writing/artifacts/generate",
            json={
                "session_id": str(session_id),
                "prompt": "Create a Markdown summary document of our discussion on retention loops",
                "artifact_type": "document",
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data["title"] == "Retention Loops vs Traditional Funnels"
        assert data["artifact_type"] == "document"
        assert data["latest_version"]["version_number"] == 1
        assert "Compounding growth" in data["latest_version"]["markdown_content"]
        assert data["latest_version"]["sources"][0]["chunk_id"] == "chunk-101"
    finally:
        app.dependency_overrides.pop(get_writing_service, None)


def test_generate_html_artifact_from_conversation(api_client, db_session_factory):
    """Test generating an HTML/CSS snippet from conversation context via POST /api/v1/writing/artifacts/generate."""
    session_id = uuid.uuid4()
    with db_session_factory() as db:
        chat_sess = ChatSession(id=session_id)
        db.add(chat_sess)
        db.commit()

    mock_ws = MagicMock(spec=WritingService)
    mock_art = MagicMock()
    mock_art.id = uuid.uuid4()
    mock_art.session_id = session_id
    mock_art.title = "Growth Loop Flow Diagram"
    mock_art.artifact_type = "html"
    mock_art.status = "completed"
    mock_art.created_at = "2026-10-12T00:00:00Z"
    mock_art.updated_at = "2026-10-12T00:00:00Z"

    mock_ver = MagicMock()
    mock_ver.id = uuid.uuid4()
    mock_ver.artifact_id = mock_art.id
    mock_ver.version_number = 1
    mock_ver.markdown_content = "# Growth Loop Flow Diagram\n\n```html\n<div class=\"loop-card\">...</div>\n```"
    mock_ver.html_content = "<div class=\"lenny-essay-preview\"><div class=\"loop-card\"><h2>Loop Flow</h2></div></div>"
    mock_ver.word_count = 45
    mock_ver.writing_brief = {"topic": "Loop Flow"}
    mock_ver.sources = []
    mock_ver.eval_metadata = {"passed": True}
    mock_ver.model_metadata = {"model": "test-chat-model"}
    mock_ver.created_at = "2026-10-12T00:00:00Z"

    mock_ws.generate_artifact_from_conversation.return_value = (mock_art, mock_ver)
    app.dependency_overrides[get_writing_service] = lambda: mock_ws

    try:
        resp = api_client.post(
            "/api/v1/writing/artifacts/generate",
            json={
                "session_id": str(session_id),
                "prompt": "Generate an HTML snippet illustrating the loop",
                "artifact_type": "html",
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data["title"] == "Growth Loop Flow Diagram"
        assert data["artifact_type"] == "html"
        assert "Loop Flow" in data["latest_version"]["html_content"]
    finally:
        app.dependency_overrides.pop(get_writing_service, None)



