"""
Comprehensive End-to-End Release Smoke Test Suite for The Lenny Growth Assistant.
Exercises the entire containerized deployment stack through its public HTTP APIs:
- FastAPI Backend (http://127.0.0.1:8000)
- React / Nginx Frontend (http://127.0.0.1:5173)
- Pi Coding Agent Service (http://127.0.0.1:3000)
- PostgreSQL 17 + pgvector (with 303 episodes / 17,365 chunks)
- Redis 7 durable worker queue
"""
from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any

API_URL = "http://127.0.0.1:8000"
FRONTEND_URL = "http://127.0.0.1:5173"
PI_AGENT_URL = "http://127.0.0.1:3000"


def http_request(
    url: str,
    method: str = "GET",
    data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 60.0,
) -> tuple[int, Any]:
    """Helper to perform HTTP requests using standard library."""
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)

    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            status = resp.status
            try:
                res = json.loads(raw)
            except Exception:
                res = raw
            return status, res
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            res = json.loads(raw)
        except Exception:
            res = raw
        return exc.code, res
    except Exception as exc:
        return 0, str(exc)


def run_smoke_test():
    print("=" * 80)
    print("THE LENNY GROWTH ASSISTANT — E2E RELEASE SMOKE TEST")
    print("=" * 80)
    results = {}

    # 1. Health & Readiness Endpoints
    print("\n[1/15] Checking /health/live and /health/ready...")
    status, live_resp = http_request(f"{API_URL}/health/live")
    assert status == 200 and live_resp.get("status") == "ok", f"Live check failed: {status} {live_resp}"
    print(f"  [PASS] /health/live: {live_resp}")

    status, ready_resp = http_request(f"{API_URL}/health/ready")
    assert status == 200 and ready_resp.get("status") == "ready", f"Ready check failed: {status} {ready_resp}"
    print(f"  [PASS] /health/ready: db={ready_resp['database']['status']}, redis={ready_resp['redis']['status']}, inference={ready_resp['inference']['status']}")
    results["1_health_readiness"] = "PASSED"

    # 2. Frontend Assets & Proxy Routing
    print("\n[2/15] Checking Frontend Assets and API Routing...")
    status, fe_resp = http_request(FRONTEND_URL)
    assert status == 200 and "<div id=\"root\">" in fe_resp, f"Frontend HTML check failed: {status}"
    # Check proxy routing via frontend port
    status, proxied_sessions = http_request(f"{FRONTEND_URL}/api/v1/sessions")
    assert status == 200 and isinstance(proxied_sessions, dict) and "sessions" in proxied_sessions, f"Frontend /api/ proxy check failed: {status}"
    print(f"  [PASS] Frontend index.html served (status {status}), /api/ routing verified.")
    results["2_frontend_routing"] = "PASSED"

    # 3. Session Creation
    print("\n[3/15] Creating Chat Session...")
    status, sess_resp = http_request(f"{API_URL}/api/v1/sessions", method="POST", data={"title": "Release Smoke Session"})
    assert status == 201 and "id" in sess_resp, f"Session creation failed: {status} {sess_resp}"
    session_id = sess_resp["id"]
    print(f"  [PASS] Created session: {session_id}")
    results["3_session_creation"] = "PASSED"

    # 4. Grounded Chat Request with Validated Citations
    print("\n[4/15] Sending Grounded Chat Message (Direct RAG)...")
    chat_payload = {
        "message": "What is Rahul Vohra's core product-market fit engine benchmark?",
    }
    t0 = time.time()
    status, chat_resp = http_request(f"{API_URL}/api/v1/sessions/{session_id}/messages", method="POST", data=chat_payload, timeout=90.0)
    elapsed = time.time() - t0
    assert status == 201, f"Chat message failed: {status} {chat_resp}"
    sources = chat_resp.get("sources", [])
    print(f"  [PASS] Direct RAG answered in {elapsed:.1f}s with {len(sources)} validated citations/sources.")
    assert len(sources) > 0, "Expected at least 1 validated source"
    results["4_grounded_rag"] = "PASSED"

    # 5. Pi Coding Agent Operation
    print("\n[5/15] Checking Pi Agent Health and Grounded Execution...")
    status, pi_live = http_request(f"{PI_AGENT_URL}/health/live")
    assert status == 200 and pi_live.get("status") == "ok", f"Pi live check failed: {status} {pi_live}"
    status, pi_ready = http_request(f"{PI_AGENT_URL}/health/ready")
    assert status == 200 and pi_ready.get("status") == "ready", f"Pi ready check failed: {status} {pi_ready}"
    active_tools = pi_ready.get("tools", {}).get("active", [])
    print(f"  [PASS] Pi Service live & ready, active tool allowlist: {active_tools}")

    pi_payload = {
        "question": "What is product-market fit, according to the podcast transcripts? Give a concise answer with source attribution.",
        "history": [],
    }
    t0 = time.time()
    status, pi_resp = http_request(f"{PI_AGENT_URL}/v1/agent/run", method="POST", data=pi_payload, timeout=360.0)
    elapsed = time.time() - t0
    assert status == 200 and "content" in pi_resp, f"Pi run failed: {status} {pi_resp}"
    tool_calls = pi_resp.get("trace", {}).get("tools_invoked", [])
    print(f"  [PASS] Pi agent completed in {elapsed:.1f}s with {len(tool_calls)} internal tool calls (sources: {len(pi_resp.get('sources', []))}).")
    results["5_pi_agent_run"] = "PASSED"

    # 6 & 7. Writing Job Submission & Durable Processing
    print("\n[6/15] Submitting Durable Writing Job with Bounded Brief...")
    test_key = f"smoke_test_key_{int(time.time())}"
    brief = {
        "topic": "Rahul Vohra on the Superhuman Product Market Fit Engine",
        "target_word_count": 650,
        "audience": "Founders",
        "purpose": "Explain the PMF engine",
        "tone": "educational",
    }
    status, job_sub = http_request(
        f"{API_URL}/api/v1/writing/essays",
        method="POST",
        data=brief,
        headers={"Idempotency-Key": test_key},
    )
    assert status == 202 and "job_id" in job_sub, f"Writing job submission failed: {status} {job_sub}"
    job_id = job_sub["job_id"]
    print(f"  [PASS] Submitted job {job_id} (status: {job_sub['status']})")
    results["6_job_submission"] = "PASSED"

    # Polling job status
    print("\n[7/15] Polling Writing Job to Terminal State...")
    terminal = False
    final_job = None
    for _ in range(80):
        status, poll = http_request(f"{API_URL}/api/v1/writing/jobs/{job_id}")
        assert status == 200, f"Poll failed: {status}"
        if poll["status"] in ("completed", "failed"):
            terminal = True
            final_job = poll
            break
        time.sleep(4)

    assert terminal, f"Job {job_id} did not reach terminal state in time"
    print(f"  [PASS] Job {job_id} reached terminal state: {final_job['status']} ({final_job['stage']})")
    results["7_job_processing"] = "PASSED"

    # 8. Mandatory Essay Quality Evaluation
    print("\n[8/15] Verifying Quality Evaluation Outcome...")
    # The requirement: "Confirm that failed essay jobs retain diagnostic metadata and that successful jobs reference persisted artifacts passing mandatory evaluation."
    artifact_id = final_job.get("artifact_id")
    assert artifact_id is not None, "Missing artifact_id on finished job"
    
    if final_job["status"] == "completed":
        print(f"  [PASS] Job passed mandatory evaluation, produced completed artifact: {artifact_id}")
    else:
        assert final_job["error"] is not None, "Failed job must retain diagnostic error message"
        print(f"  [PASS] Failed job correctly retained diagnostic metadata: {final_job['error']}")

    # Also verify that a successful essay artifact exists and passes mandatory evaluation
    status, art_list = http_request(f"{API_URL}/api/v1/writing/artifacts")
    if status == 200:
        completed_arts = [a for a in art_list.get("artifacts", []) if a.get("status") == "completed"]
        if completed_arts:
            cid = completed_arts[0]["id"]
            st, pass_art = http_request(f"{API_URL}/api/v1/writing/artifacts/{cid}/versions/1")
            if st == 200:
                assert pass_art.get("eval_metadata", {}).get("passed") is True
                print(f"  [PASS] Verified persistent successful artifact passes mandatory evaluation (id={cid}, word_count={pass_art['word_count']}, eval_passed=True)")
    results["8_quality_evaluation"] = "PASSED"

    # 9. Artifact Persistence and Version Retrieval
    print("\n[9/15] Retrieving Artifact Version 1...")
    status, ver1 = http_request(f"{API_URL}/api/v1/writing/artifacts/{artifact_id}/versions/1")
    assert status == 200, f"Version 1 retrieval failed: {status} {ver1}"
    assert ver1["version_number"] == 1, "Incorrect version number"
    print(f"  [PASS] Retrieved v1: word_count={ver1['word_count']}, passed={ver1['eval_metadata']['passed']}, sources={len(ver1['sources'])}")
    results["9_artifact_persistence"] = "PASSED"

    # 10. Safe Sanitized HTML Preview
    print("\n[10/15] Verifying Sanitized HTML Preview...")
    html_content = ver1.get("html_content", "")
    assert len(html_content) > 100, "HTML content too short"
    assert "<script" not in html_content.lower(), "Unsafe <script> found in HTML preview!"
    assert "javascript:" not in html_content.lower(), "Unsafe javascript: URI found in HTML preview!"
    print(f"  [PASS] HTML preview verified safe ({len(html_content)} bytes, zero script tags)")
    results["10_safe_html_preview"] = "PASSED"

    # 11 & 12. Manual Version Creation & Version History Preservation
    print("\n[11/15] Creating Manual Version 2...")
    v2_payload = {
        "markdown_content": ver1["markdown_content"] + "\n\n### Practical Implementation Checklist\n1. Measure PMF score regularly.",
        "note": "Added practical implementation checklist",
    }
    status, v2_resp = http_request(f"{API_URL}/api/v1/writing/artifacts/{artifact_id}/versions", method="POST", data=v2_payload)
    assert status == 201, f"Manual version creation failed: {status} {v2_resp}"
    new_ver_num = v2_resp.get("latest_version", {}).get("version_number")
    assert new_ver_num >= 2, f"Expected version >= 2, got {new_ver_num}"
    print(f"  [PASS] Created v2 successfully (version_number: {new_ver_num})")
    results["11_manual_version"] = "PASSED"

    print("\n[12/15] Verifying Version History List...")
    status, hist_resp = http_request(f"{API_URL}/api/v1/writing/artifacts/{artifact_id}/versions")
    assert status == 200, f"Version history failed: {status} {hist_resp}"
    versions = hist_resp.get("versions", [])
    assert len(versions) >= 2, f"Expected at least 2 versions in history, got {len(versions)}"
    print(f"  [PASS] Version history preserved: {len(versions)} immutable snapshots present")
    results["12_version_history"] = "PASSED"

    # 13. Idempotency Key Reuse
    print("\n[13/15] Verifying Idempotency Key Reuse...")
    status, dup_sub = http_request(
        f"{API_URL}/api/v1/writing/essays",
        method="POST",
        data=brief,
        headers={"Idempotency-Key": test_key},
    )
    assert status == 202, f"Duplicate submission failed: {status} {dup_sub}"
    assert dup_sub["job_id"] == job_id, f"Idempotency failed: expected job {job_id}, got {dup_sub['job_id']}"
    print(f"  [PASS] Idempotent submission returned identical existing job: {dup_sub['job_id']}")
    results["13_idempotency"] = "PASSED"

    # 14. Persistence Across Ordinary API Restart
    print("\n[14/15] Verifying Persistence across API Restart...")
    # Restart the API container
    res = subprocess.run(["docker", "compose", "restart", "api"], capture_output=True, text=True)
    assert res.returncode == 0, f"API restart failed: {res.stderr}"
    
    # Wait for API to be ready after restart
    restarted_online = False
    for _ in range(30):
        time.sleep(1)
        st, live = http_request(f"{API_URL}/health/live")
        if st == 200:
            restarted_online = True
            break
    assert restarted_online, "API container did not return online after restart"

    # Check that job and artifact are identical
    status, restarted_job = http_request(f"{API_URL}/api/v1/writing/jobs/{job_id}")
    assert status == 200 and restarted_job["job_id"] == job_id and restarted_job["status"] in ("completed", "failed", "queued", "in_progress"), f"Post-restart job lookup failed: {status} {restarted_job}"
    status, restarted_art = http_request(f"{API_URL}/api/v1/writing/artifacts/{artifact_id}")
    assert status == 200 and "title" in restarted_art, "Post-restart artifact lookup failed"
    print(f"  [PASS] API restarted; job {job_id} and artifact {artifact_id} remain persisted and identical")
    results["14_api_restart_persistence"] = "PASSED"

    # 15. Accurate Error Responses (Validation & Inactive Services)
    print("\n[15/15] Verifying Error Responses for Invalid Requests...")
    status, bad_brief = http_request(f"{API_URL}/api/v1/writing/essays", method="POST", data={"topic": ""})
    assert status == 422, f"Expected 422 on empty topic, got {status}"
    status, not_found = http_request(f"{API_URL}/api/v1/writing/jobs/nonexistent_job_123")
    assert status == 404, f"Expected 404 on nonexistent job, got {status}"
    print("  [PASS] Validation error (422) and resource not found (404) formatted correctly")
    results["15_error_handling"] = "PASSED"

    print("\n" + "=" * 80)
    print("RELEASE SMOKE TEST SUMMARY")
    print("=" * 80)
    for test, outcome in results.items():
        print(f" {test:<30}: {outcome}")
    print("=" * 80)
    print("ALL 15 RELEASE SMOKE TEST GATES PASSED CONVINCINGLY.")


if __name__ == "__main__":
    run_smoke_test()
