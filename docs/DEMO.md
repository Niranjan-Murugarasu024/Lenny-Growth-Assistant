# 2–3 Minute Product Demonstration Guide

This guide provides a structured, repeatable 2–3 minute walkthrough of **The Lenny Growth Assistant** for reviewers, evaluators, and stakeholders.

---

## 1. Demo Overview & Strategy

- **Duration**: ~2.5–3.0 minutes.
- **Workflow Highlights**:
  1. Multi-turn Grounded Chat with authoritative citation verification.
  2. Model Switching: Local Ollama (`qwen2.5:1.5b`) vs Cloud NVIDIA NIM (`openai/gpt-oss-20b`).
  3. Generating a Ship 30 for 30 essay from chat insights with durable background jobs.
  4. Workspace editing, HTML preview toggle, immutable version saving, and asynchronous AI revisions.

---

## 2. Step-by-Step Walkthrough

### Part 1: Starting the Stack & Opening the Product (0:00 - 0:30)
1. **Show running containers**:
   ```bash
   docker compose ps
   ```
   Point out that all 6 services are active: `api`, `db` (PostgreSQL + pgvector with 17,365 chunks across 303 episodes), `redis` (durable queue), `worker` (durable essay writer), `pi-agent` (Node.js agent), and `frontend` (Nginx + React SPA).
2. **Open the browser**:
   Navigate to `http://localhost:5173/`.
   - Point out the clean editorial layout: navigation bar, model selector, sidebar with sessions and essay library, and the central chat interface.

### Part 2: Grounded Chat & Model Switching (0:30 - 1:15)
1. Ask a product leadership question in chat:
   *"What is Brian Chesky's perspective on founders being involved in details?"*
2. Observe the sub-second response with explicit citations:
   - Click the citation pill `[Source 1: Brian Chesky]` to view the slide-over Sources drawer displaying the exact excerpt, episode title, and YouTube timestamp link.
3. Ask a contextual follow-up:
   *"How does he contrast this with standard division of labor?"*
   - Show that session context is preserved.
4. Show the **Model Selector** in the header:
   - Switch from `Ollama (qwen2.5:1.5b)` to `NVIDIA NIM (openai/gpt-oss-20b)`.
   - Point out that subsequent inference routes to NVIDIA's high-speed cloud endpoint.

### Part 3: Essay Composer & Durable Background Generation (1:15 - 2:00)
1. In the chat response, click **"Create Essay from this Answer"** (or click **"New Essay"** in the top navigation).
2. The Ship 30 for 30 Brief Form opens pre-populated with:
   - Topic: *"Brian Chesky on Founder-Led Product Management"*
   - Target Word Count: `650`
   - Audience: *"Product Managers and Founders"*
   - Tone: *"Analytical"*
3. Click **"Generate Essay"**:
   - The job is dispatched to Redis with snapshot metadata.
   - The UI shows real-time progress stages: *Researching transcript sources*, *Drafting and evaluating essay*, *Saving artifact*.

### Part 4: Artifact Workspace, Versioning, HTML Preview & AI Revisions (2:00 - 3:00)
1. Open the essay in the **Workspace**:
   - Point out the word count pill, version indicator (`v1`), and quality evaluation badge.
   - If word count falls outside strict bounds, show the transparent diagnostics banner (target range, body words, missing criteria) and explain that drafts remain fully editable rather than failing silently.
2. Toggle the **View Mode**:
   - Click **"Split"** for side-by-side editing and live preview.
   - Click **"HTML Preview"** to view typography-rendered output inside an isolated sandboxed iframe.
3. Edit the markdown text and click **"Save Version"**:
   - Confirm that version 2 (`v2`) is created immediately while preserving version 1 in the History drawer.
4. Test the **Asynchronous Revision Bar**:
   - Enter revision instruction: *"Add an actionable 3-step checklist for product founders at the end."*
   - Submit: Notice the revision runs asynchronously via the background worker without HTTP timeouts, automatically committing version 3 (`v3`) upon completion.

---

## 3. How the AI Subsystems Support the Experience

- **Hybrid Vector Retrieval**: PostgreSQL executes cosine similarity search over 17,365 chunks across 303 podcast episodes with `nomic-embed-text:v1.5` embeddings.
- **Autonomous Pi Coding Agent**: Runs in a sandboxed microservice (`agent-service/`) executing ReAct multi-turn tool loops with strict token authentication.
- **Backend-Authoritative Validation**: Citations are not trusted blindly; every cited chunk is matched against database records before saving.
- **Durable Worker Queue**: Redis coordinates jobs with database heartbeat tracking and bounded retries.

---

## 4. Known Limitations & Operating Notes

1. **Local Model Latency**: On consumer CPUs without GPU offload, generating a full 1,250-word essay with local Ollama (`qwen2.5:1.5b`) can take 60–120 seconds. Using the cloud NVIDIA NIM model (`openai/gpt-oss-20b`) generates complete drafts in under 10 seconds.
2. **Context Window Limits**: When querying broad topics with dozens of potential chunks, retrieval is bounded to top-k (5 chunks) to fit local context windows.
3. **Third-Party Content**: Podcast transcripts remain the intellectual property of Lenny Rachitsky.
