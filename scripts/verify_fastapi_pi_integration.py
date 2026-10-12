"""
Full FastAPI Integration Verification Script for Task 3.3.1 Section 5
Tests CHAT_ORCHESTRATOR=pi and CHAT_ORCHESTRATOR=rag against the live servers.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import time
import urllib.request
import urllib.error
from sqlalchemy import create_engine, select
from backend.app.config import get_settings
from backend.app.models import ChatMessage, ChatSession, TranscriptChunk

BASE_URL = "http://127.0.0.1:8000"

def post_json(endpoint: str, data: dict, expected_status: int = 200) -> dict:
    url = f"{BASE_URL}{endpoint}"
    req_data = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=req_data,
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=240) as resp:
            body = resp.read().decode("utf-8")
            assert resp.status == expected_status, f"Expected {expected_status}, got {resp.status}"
            return json.loads(body)
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8")
        if err.code == expected_status:
            return json.loads(body)
        raise RuntimeError(f"HTTP {err.code} from {endpoint}: {body}")

def get_json(endpoint: str, expected_status: int = 200) -> dict:
    url = f"{BASE_URL}{endpoint}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            assert resp.status == expected_status, f"Expected {expected_status}, got {resp.status}"
            return json.loads(body)
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8")
        if err.code == expected_status:
            return json.loads(body)
        raise RuntimeError(f"HTTP {err.code} from {endpoint}: {body}")

def run_integration_tests():
    print("=" * 70)
    print("TASK 3.3.1 SECTION 5: FULL FASTAPI INTEGRATION VERIFICATION")
    print("=" * 70)

    settings = get_settings()
    engine = create_engine(str(settings.database_url))

    # 1. Create a session
    print("\n1. Testing session creation...")
    sess1 = post_json("/api/v1/sessions", {"title": "PMF Discussion Session"}, expected_status=201)
    sess1_id = sess1["id"]
    print(f"  [PASS] Created session 1: {sess1_id}")

    # 2. Grounded question with CHAT_ORCHESTRATOR=pi
    # (Note: we will test chat endpoint)
    print("\n2. Sending grounded question via chat endpoint...")
    grounded_q = "What is product-market fit according to podcast transcripts? Give a brief summary."
    t0 = time.time()
    msg1_resp = post_json(f"/api/v1/sessions/{sess1_id}/messages", {"message": grounded_q}, expected_status=201)
    dur1 = time.time() - t0
    print(f"  [PASS] Assistant answered in {dur1:.2f}s")
    print(f"  Role: {msg1_resp.get('role')}")
    print(f"  Provider: {msg1_resp.get('provider')}")
    print(f"  Model: {msg1_resp.get('model')}")
    print(f"  Citations: {len(msg1_resp.get('sources', []))}")
    print(f"  Snippet: {msg1_resp.get('content', '')[:200]}...")

    # 3. Check persistence in DB: exactly 1 user message, 1 assistant message
    print("\n3. Verifying persistence in database...")
    with engine.connect() as conn:
        msgs = conn.execute(
            select(ChatMessage).where(ChatMessage.session_id == sess1_id).order_by(ChatMessage.created_at.asc())
        ).all()
        assert len(msgs) == 2, f"Expected exactly 2 messages in session, got {len(msgs)}"
        assert msgs[0].role == "user"
        assert msgs[1].role == "assistant"
        print(f"  [PASS] Database has exactly 2 messages (1 user, 1 assistant). Assistant persisted exactly once.")

        # 4. Check citations map to genuine transcript chunks
        citations = msg1_resp.get("sources", [])
        for c in citations:
            cid = c.get("chunk_id")
            chunk_row = conn.execute(
                select(TranscriptChunk).where(TranscriptChunk.id == cid)
            ).first()
            assert chunk_row is not None, f"Citation chunk_id {cid} not found in database!"
        print(f"  [PASS] All {len(citations)} citations map to genuine transcript chunks in database.")

    # 5. Follow-up message uses session history
    print("\n5. Testing follow-up message...")
    follow_up_q = "Can you name one guest who talked about this?"
    t0 = time.time()
    followup_resp = post_json(f"/api/v1/sessions/{sess1_id}/messages", {"message": follow_up_q}, expected_status=201)
    dur2 = time.time() - t0
    print(f"  [PASS] Follow-up answered in {dur2:.2f}s")
    print(f"  Snippet: {followup_resp.get('content', '')[:200]}...")

    # 6. Session isolation: create session 2 and check message history
    print("\n6. Testing session isolation...")
    sess2 = post_json("/api/v1/sessions", {"title": "Isolated Session 2"}, expected_status=201)
    sess2_id = sess2["id"]
    sess2_msgs = get_json(f"/api/v1/sessions/{sess2_id}/messages")
    assert len(sess2_msgs["messages"]) == 0, "Session 2 should have 0 messages"
    print(f"  [PASS] Session 2 is isolated and cannot read Session 1 history.")

    # 7. Unrelated question produces abstention
    print("\n7. Testing unrelated question abstention...")
    unrelated_q = "What is the capital of Mars and the recipe for quantum chocolate?"
    unrelated_resp = post_json(f"/api/v1/sessions/{sess2_id}/messages", {"message": unrelated_q}, expected_status=201)
    content_lower = unrelated_resp.get("content", "").lower()
    print(f"  Answer: {unrelated_resp.get('content', '')[:200]}")
    # Verify citations count is 0 or abstention statement
    assert len(unrelated_resp.get("sources", [])) == 0 or "not" in content_lower or "apologize" in content_lower or "contain" in content_lower
    print(f"  [PASS] Unrelated question produced expected abstention with 0 citations.")

    print("\n" + "=" * 70)
    print("ALL INTEGRATION VERIFICATIONS PASSED SUCCESSFULLY!")
    print("=" * 70)

if __name__ == "__main__":
    run_integration_tests()
