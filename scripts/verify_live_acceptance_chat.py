import json
import httpx

client = httpx.Client(base_url="http://localhost:8000", timeout=240.0)

# Use the active session from Question 1
session_id = "720d7540-86cb-4bf1-addd-9f3cbf791d33"

print("=" * 60)
print(f"CONTINUING CONVERSATION IN SESSION: {session_id}")
print("=" * 60)

# Question 2: "How can I measure it in practice?"
print("\n>>> Asking Question 2: 'How can I measure it in practice?'")
r2 = client.post(
    f"/api/v1/sessions/{session_id}/messages",
    json={"message": "How can I measure it in practice?"},
)
print("Q2 Status:", r2.status_code)
d2 = r2.json()
print("Q2 Provider:", d2.get("provider"), "| Model:", d2.get("model"))
print("Q2 Sources Count:", len(d2.get("sources") or []))
print("Q2 Excerpt:\n", d2.get("content", "")[:500])
if d2.get("sources"):
    for s in d2["sources"][:2]:
        print(f"  - Source {s['citation_index']}: Guest={s['guest']}, Title={s['title']}, YouTube={s['youtube_url']}")

# Question 3: "Which guest or framework supports that recommendation?"
print("\n>>> Asking Question 3: 'Which guest or framework supports that recommendation?'")
r3 = client.post(
    f"/api/v1/sessions/{session_id}/messages",
    json={"message": "Which guest or framework supports that recommendation?"},
)
print("Q3 Status:", r3.status_code)
d3 = r3.json()
print("Q3 Provider:", d3.get("provider"), "| Model:", d3.get("model"))
print("Q3 Sources Count:", len(d3.get("sources") or []))
print("Q3 Excerpt:\n", d3.get("content", "")[:500])
if d3.get("sources"):
    for s in d3["sources"][:2]:
        print(f"  - Source {s['citation_index']}: Guest={s['guest']}, Title={s['title']}, YouTube={s['youtube_url']}")

# Now verify Session Isolation: Create a completely new session
print("\n" + "=" * 60)
print("TESTING SESSION ISOLATION (NEW SESSION)")
print("=" * 60)
r_new_sess = client.post("/api/v1/sessions", json={"title": "Session Isolation Check"})
new_session_id = r_new_sess.json()["id"]
print("Created New Session ID:", new_session_id)

print("\n>>> Asking in New Session: 'What did I ask you in my previous session?'")
r_leak = client.post(
    f"/api/v1/sessions/{new_session_id}/messages",
    json={"message": "What did I ask you in my previous session?"},
)
print("Leak Check Status:", r_leak.status_code)
d_leak = r_leak.json()
print("Leak Check Content:\n", d_leak.get("content", ""))

# Verify Abstention on unsupported question
print("\n" + "=" * 60)
print("TESTING ABSTENTION ON UNSUPPORTED TOPIC")
print("=" * 60)
print(">>> Asking: 'What is the exact population of a fictional planet called Zorblax?'")
r_unsupported = client.post(
    f"/api/v1/sessions/{new_session_id}/messages",
    json={"message": "What is the exact population of a fictional planet called Zorblax?"},
)
print("Unsupported Question Status:", r_unsupported.status_code)
d_unsupported = r_unsupported.json()
print("Sources Count (should be 0 or empty):", len(d_unsupported.get("sources") or []))
print("Unsupported Answer Content:\n", d_unsupported.get("content", ""))

print("\nAll conversational criteria checks completed.")
