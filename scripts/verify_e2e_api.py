import json
import sys
import httpx

BASE_URL = "http://127.0.0.1:8000"

def run_e2e_verification():
    print("=" * 75)
    print("THE LENNY GROWTH ASSISTANT — E2E LIVE API VERIFICATION")
    print("=" * 75)
    client = httpx.Client(base_url=BASE_URL, timeout=180.0)

    # 1. Health checks
    print("\n[Step 1] Checking /health/live...")
    resp = client.get("/health/live")
    print(f"Status: {resp.status_code} | Body: {resp.json()}")
    assert resp.status_code == 200

    print("\n[Step 2] Checking /health/ready...")
    resp = client.get("/health/ready")
    print(f"Status: {resp.status_code} | Body: {resp.json()}")
    assert resp.status_code == 200

    # 2. Create Session 1
    print("\n[Step 3] Creating Session 1...")
    resp = client.post("/api/v1/sessions", json={"title": "Session 1: Growth Strategy"})
    assert resp.status_code == 201
    session_1 = resp.json()
    s1_id = session_1["id"]
    print(f"Session 1 Created: id={s1_id} title={session_1['title']!r}")

    # 3. Question 1 in Session 1
    q1 = "What makes a growth team effective?"
    print(f"\n[Step 4] Asking Question 1 in Session 1: {q1!r}...")
    resp = client.post(f"/api/v1/sessions/{s1_id}/messages", json={"message": q1})
    if resp.status_code != 201:
        print(f"ERROR: {resp.status_code} - {resp.text}")
    assert resp.status_code == 201
    msg1 = resp.json()
    print(f"Response status: {resp.status_code} | Role: {msg1['role']} | Model: {msg1['model']}")
    print(f"Answer excerpt:\n{msg1['content'][:300]}...\n")
    print(f"Sources returned ({len(msg1['sources'])}):")
    for s in msg1["sources"]:
        print(f"  - [Source {s['citation_index']}] Guest: {s['guest']} | Ep: {s['title'][:40]} | dist={s['cosine_distance']:.4f}")
    assert len(msg1["sources"]) > 0

    # 4. Follow-up Question in Session 1
    q2 = "What specific metrics should the team track?"
    print(f"\n[Step 5] Asking Follow-up Question 2 in Session 1: {q2!r}...")
    resp = client.post(f"/api/v1/sessions/{s1_id}/messages", json={"message": q2})
    assert resp.status_code == 201
    msg2 = resp.json()
    print(f"Response status: {resp.status_code} | Role: {msg2['role']} | Model: {msg2['model']}")
    print(f"Answer excerpt:\n{msg2['content'][:300]}...\n")
    print(f"Sources returned ({len(msg2['sources'])}):")
    for s in msg2["sources"]:
        print(f"  - [Source {s['citation_index']}] Guest: {s['guest']} | Ep: {s['title'][:40]} | dist={s['cosine_distance']:.4f}")

    # 5. Create Session 2
    print("\n[Step 6] Creating Session 2 (Independent Session)...")
    resp = client.post("/api/v1/sessions", json={"title": "Session 2: Isolated Session"})
    assert resp.status_code == 201
    session_2 = resp.json()
    s2_id = session_2["id"]
    print(f"Session 2 Created: id={s2_id} title={session_2['title']!r}")

    # 6. Verify Session 2 isolation
    q_isolation = "What was the previous question I asked you?"
    print(f"\n[Step 7] Asking Isolation Probe in Session 2: {q_isolation!r}...")
    resp = client.post(f"/api/v1/sessions/{s2_id}/messages", json={"message": q_isolation})
    assert resp.status_code == 201
    msg_iso = resp.json()
    print(f"Session 2 Answer excerpt:\n{msg_iso['content'][:300]}...\n")

    # 7. Retrieve Session 1 Message History
    print(f"\n[Step 8] Retrieving complete message history for Session 1 ({s1_id})...")
    resp = client.get(f"/api/v1/sessions/{s1_id}/messages")
    assert resp.status_code == 200
    s1_history = resp.json()
    print(f"Total messages in Session 1: {len(s1_history['messages'])}")
    for i, m in enumerate(s1_history["messages"], 1):
        src_info = f"({len(m['sources'])} sources)" if m.get("sources") else ""
        print(f"  [{i}] {m['role'].upper()}: {m['content'][:80]}... {src_info}")
    assert len(s1_history["messages"]) == 4  # user1, asst1, user2, asst2

    # 8. Test Unsupported Question in Session 2
    q_unsupported = "What are the symptoms of quantum error correction failure in superconducting qubits?"
    print(f"\n[Step 9] Asking Unsupported Out-of-Domain Question in Session 2: {q_unsupported!r}...")
    resp = client.post(f"/api/v1/sessions/{s2_id}/messages", json={"message": q_unsupported})
    assert resp.status_code == 201
    msg_unsup = resp.json()
    print(f"Answer excerpt:\n{msg_unsup['content'][:300]}...\n")
    print(f"Sources returned count: {len(msg_unsup['sources'])} (Expect 0)")
    assert len(msg_unsup["sources"]) == 0

    print("\n" + "=" * 75)
    print("RESULT: ALL E2E LIVE API CHECKS COMPLETED SUCCESSFULLY!")
    print("=" * 75)

if __name__ == "__main__":
    run_e2e_verification()
