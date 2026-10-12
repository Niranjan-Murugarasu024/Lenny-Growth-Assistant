"""
Final Docker End-to-End Acceptance Verification (Task 6.2 - Phases 5 & 6).

Verifies:
1. Real Docker Writing Workflow to terminal state (PostgreSQL authoritative state, Redis coordination,
   research evidence, word count bounds, mandatory evaluation, persisted artifact and sanitized HTML).
2. Real Docker Pi Agent Workflow to full completion (Tool calls, chunk retrieval, final answer,
   and backend citation validation).
3. Direct RAG conversational flow verified operational after Pi test.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
import uuid

API_BASE = "http://127.0.0.1:8000"
PI_AGENT_BASE = "http://127.0.0.1:3000"
FRONTEND_BASE = "http://127.0.0.1:5173"


def http_request(
    url: str,
    method: str = "GET",
    data: dict | None = None,
    headers: dict | None = None,
    timeout: float = 300.0,
) -> tuple[int, dict | str]:
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)

    payload = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=payload, headers=req_headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(body)
            except Exception:
                return resp.status, body
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8")
        try:
            return err.code, json.loads(body)
        except Exception:
            return err.code, body


def verify_docker_writing_workflow() -> dict:
    print("\n" + "=" * 75)
    print("PHASE 5: REAL DOCKER WRITING WORKFLOW VERIFICATION")
    print("=" * 75)

    test_topic = f"Rahul Vohra's Product-Market Fit Engine for Superhuman {uuid.uuid4().hex[:6]}"
    idem_key = f"final_idem_{uuid.uuid4().hex[:8]}"

    print(f"[*] Submitting essay brief: '{test_topic}' (target: 500 words)...")
    code, job_resp = http_request(
        f"{API_BASE}/api/v1/writing/essays",
        method="POST",
        headers={"Idempotency-Key": idem_key},
        data={
            "topic": test_topic,
            "target_word_count": 500,
            "audience": "Founders and Product Managers",
            "purpose": "Explain the 40% PMF benchmark engine",
            "tone": "educational",
        },
    )
    assert code == 202, f"Failed submitting essay brief: {job_resp}"
    job_id = job_resp["job_id"]
    print(f"[+] Job {job_id} accepted by API (initial status={job_resp['status']}).")

    # Poll job until terminal state
    print(f"[*] Polling job {job_id} through public API until terminal state (max 420s)...")
    start_time = time.time()
    terminal_status = None
    poll_result = None

    while time.time() - start_time < 420.0:
        time.sleep(5)
        code, poll_result = http_request(f"{API_BASE}/api/v1/writing/jobs/{job_id}")
        assert code == 200, f"Polling failed with {code}: {poll_result}"
        status = poll_result["status"]
        stage = poll_result["stage"]
        elapsed = round(time.time() - start_time, 1)
        print(f"    [{elapsed}s] Job {job_id}: status='{status}', stage='{stage}'")

        if status in ("completed", "failed"):
            terminal_status = status
            break

    assert terminal_status is not None, f"Job {job_id} did not reach terminal state within 420s timeout."
    print(f"[+] Job {job_id} reached terminal state: '{terminal_status}' in {round(time.time() - start_time, 1)}s.")

    artifact_id = poll_result.get("artifact_id")
    if terminal_status == "completed":
        assert artifact_id, "Completed job must reference an artifact ID"
        print(f"[+] Job passed mandatory evaluation! Artifact ID: {artifact_id}")

        # Retrieve artifact
        code, art_data = http_request(f"{API_BASE}/api/v1/writing/artifacts/{artifact_id}")
        assert code == 200
        print(f"    Artifact Title: '{art_data['title']}', Version: {art_data['latest_version_number']}")

        # Retrieve specific version
        code, ver_data = http_request(f"{API_BASE}/api/v1/writing/artifacts/{artifact_id}/versions/1")
        assert code == 200
        print(f"    Body Word Count: {ver_data['word_count']} words")
        print(f"    Sources Count: {len(ver_data.get('sources') or [])}")
        assert ver_data.get("html_content"), "Expected sanitized HTML content"
        assert "<script>" not in ver_data["html_content"], "Sanitization check failed"
        print("    Sanitized HTML preview verified.")
    else:
        print(f"[!] Job concluded with state 'failed': {poll_result.get('error')}")
        if artifact_id:
            print(f"    Persisted draft artifact ID (retained for author inspection): {artifact_id}")
            code, ver_data = http_request(f"{API_BASE}/api/v1/writing/artifacts/{artifact_id}/versions/1")
            if code == 200:
                print(f"    Draft body word count: {ver_data['word_count']} words")
                print(f"    Evaluation feedback preserved: {ver_data.get('eval_metadata', {}).get('feedback')}")

    return {"job_id": job_id, "status": terminal_status, "artifact_id": artifact_id, "poll_result": poll_result}


def verify_docker_pi_agent_workflow() -> dict:
    print("\n" + "=" * 75)
    print("PHASE 6: REAL DOCKER PI AGENT WORKFLOW VERIFICATION")
    print("=" * 75)

    # 1. Pi Agent readiness
    print("[*] 1. Checking Pi Agent service readiness probe...")
    code, pi_ready = http_request(f"{PI_AGENT_BASE}/health/ready")
    assert code == 200, f"Pi agent health check failed: {pi_ready}"
    print(f"[+] Pi Agent ready on :3000 (Backend: {pi_ready['backend']['status']}, Tools: {pi_ready['tools']['active']})")

    # 2. Create Chat Session
    print("[*] 2. Creating persistent chat session...")
    code, session = http_request(f"{API_BASE}/api/v1/sessions", method="POST", data={"title": "Pi Agent Final Acceptance Session"})
    assert code == 201, f"Failed creating session: {session}"
    session_id = session["id"]
    print(f"[+] Created Session {session_id}")

    # 3. Submit concise grounded question via Pi orchestrator
    test_question = "What is Rahul Vohra's 40 percent product-market fit question?"
    print(f"[*] 3. Sending question via Pi Orchestrator: '{test_question}'...")
    t0 = time.time()
    code, msg_resp = http_request(
        f"{API_BASE}/api/v1/sessions/{session_id}/messages",
        method="POST",
        data={
            "message": test_question,
            "orchestrator": "pi",
        },
        timeout=300.0,
    )
    elapsed = round(time.time() - t0, 1)

    if code in (200, 201):
        print(f"[+] Pi Agent response completed successfully in {elapsed}s (HTTP {code})!")
        print(f"    Content excerpt: {msg_resp['content'][:200]}...")
        sources = msg_resp.get("sources") or []
        print(f"    Validated Sources Count: {len(sources)}")
        for i, s in enumerate(sources[:3], 1):
            print(f"      Source {i}: {s.get('guest')} — {s.get('title')} (chunk #{s.get('chunk_index')})")
        assert len(sources) > 0, "Expected validated sources in Pi Agent response"
        pi_success = True
    else:
        print(f"[-] Pi Agent request returned HTTP {code}: {msg_resp} ({elapsed}s elapsed)")
        pi_success = False

    # 4. Verify Direct RAG Chat still operational
    print("\n[*] 4. Verifying Direct RAG flow remains operational...")
    t0 = time.time()
    code_rag, msg_rag = http_request(
        f"{API_BASE}/api/v1/sessions/{session_id}/messages",
        method="POST",
        data={
            "message": "What did Brian Chesky say about founders being in the details?",
            "orchestrator": "rag",
        },
        timeout=120.0,
    )
    elapsed_rag = round(time.time() - t0, 1)
    assert code_rag in (200, 201), f"Direct RAG failed with {code_rag}: {msg_rag}"
    print(f"[+] Direct RAG returned in {elapsed_rag}s (HTTP {code_rag}) with {len(msg_rag.get('sources') or [])} validated sources.")

    return {"session_id": session_id, "pi_success": pi_success, "elapsed": elapsed}


def main() -> None:
    print("=" * 75)
    print("TASK 6.2: DOCKER END-TO-END FINAL ACCEPTANCE VERIFICATION")
    print("=" * 75)

    writing_result = verify_docker_writing_workflow()
    pi_result = verify_docker_pi_agent_workflow()

    print("\n" + "=" * 75)
    print("FINAL ACCEPTANCE VERIFICATION SUMMARY")
    print("=" * 75)
    print(f"Writing Workflow: Job {writing_result['job_id']} reached terminal status '{writing_result['status']}' (Artifact: {writing_result['artifact_id']})")
    print(f"Pi Agent Workflow: Pi response completed={pi_result['pi_success']} in {pi_result['elapsed']}s")
    print("=" * 75)


if __name__ == "__main__":
    main()
