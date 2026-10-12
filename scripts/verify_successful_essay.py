"""
Verification script for submitting an essay targeting 650 words
to achieve a passing quality evaluation in Docker Compose.
"""
import json
import time
import urllib.request

API = "http://127.0.0.1:8000"

def main():
    brief = {
        "topic": "Rahul Vohra on the Superhuman Product Market Fit Engine",
        "target_word_count": 650,
        "audience": "Founders and Product Managers",
        "purpose": "Explain the 40% PMF benchmark engine",
        "tone": "educational",
    }
    req = urllib.request.Request(
        f"{API}/api/v1/writing/essays",
        data=json.dumps(brief).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read())
    job_id = res["job_id"]
    print(f"Submitted {job_id}")

    for i in range(70):
        time.sleep(5)
        with urllib.request.urlopen(f"{API}/api/v1/writing/jobs/{job_id}") as resp:
            poll = json.loads(resp.read())
        print(f"[{i*5}s] Status: {poll['status']} ({poll['stage']})")
        if poll["status"] in ("completed", "failed"):
            print("Final Result:", json.dumps(poll, indent=2))
            if poll["status"] == "completed":
                art_id = poll["artifact_id"]
                with urllib.request.urlopen(f"{API}/api/v1/writing/artifacts/{art_id}/versions/1") as aresp:
                    ver = json.loads(aresp.read())
                print(f"Verified Artifact {art_id}: word_count={ver['word_count']}, passed={ver.get('eval_metadata', {}).get('passed')}")
            break

if __name__ == "__main__":
    main()
