import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import json
import time
import urllib.request
import urllib.error
from sqlalchemy import create_engine, select
from backend.app.config import get_settings
from backend.app.models import TranscriptChunk

def run_agent_verification():
    prompt = "What is product-market fit, according to the podcast transcripts? Give a concise answer with source attribution."
    print("=" * 60)
    print("TASK 3.3.1 LIVE AGENT VERIFICATION: /v1/agent/run")
    print(f"Prompt: {prompt}")
    print("=" * 60)

    url = "http://127.0.0.1:3000/v1/agent/run"
    req_data = json.dumps({
        "question": prompt,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=req_data,
        headers={"Content-Type": "application/json"}
    )

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=240) as resp:
            elapsed = time.time() - t0
            status_code = resp.status
            body = resp.read().decode("utf-8")
            data = json.loads(body)
    except Exception as e:
        print(f"Agent run failed: {e}")
        return False

    print(f"HTTP Status: {status_code} in {elapsed:.2f}s")
    print("\n--- AGENT RESPONSE ---")
    print(f"Status: {data.get('status')}")
    print(f"Turns: {data.get('turns')}")
    print(f"Content Length: {len(data.get('content', ''))}")
    print(f"Content:\n{data.get('content')}\n")

    print("\n--- EXECUTION TRACE ---")
    trace = data.get("trace", {})
    print(f"Total Elapsed Time (s): {trace.get('elapsed_seconds')}s")
    print(f"Turns Executed: {trace.get('turns_count')}")
    print(f"Final Text Length: {trace.get('final_text_length')}")
    print(f"Sources Count: {trace.get('sources_count')}")
    print("Tools Executed:")
    for t in trace.get("tools_invoked", []):
        print(f"  - Tool: {t.get('tool_name')} | Duration: {t.get('duration_ms')}ms | Status: {t.get('status')}")

    print("\n--- SOURCE REFERENCES ---")
    sources = data.get("sources", [])
    print(f"Number of sources returned: {len(sources)}")
    for s in sources:
        print(f"  - Chunk ID: {s.get('chunk_id')}")
        print(f"    Episode Title: {s.get('title')}")
        print(f"    Guest: {s.get('guest')}")
        print(f"    Episode ID: {s.get('episode_id')}")
        print(f"    Chunk Index: {s.get('chunk_index')}")

    print("\n--- INDEPENDENT BACKEND DATABASE VALIDATION ---")
    settings = get_settings()
    engine = create_engine(str(settings.database_url))
    with engine.connect() as conn:
        for s in sources:
            cid = s.get("chunk_id")
            if not cid:
                print("  [FAIL] Missing chunk_id in source")
                continue
            row = conn.execute(
                select(TranscriptChunk).where(TranscriptChunk.id == cid)
            ).first()
            if row:
                print(f"  [PASS] Verified chunk_id {cid} exists in PostgreSQL database (lenny_growth).")
            else:
                print(f"  [FAIL] Chunk ID {cid} NOT found in database!")

    return True

if __name__ == "__main__":
    run_agent_verification()
