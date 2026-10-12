# System Architecture & Technical Specifications — The Lenny Growth Assistant

**Document:** `architecture.md`  
**Application:** The Lenny Growth Assistant  
**Architecture Style:** Microservices & Modular Monolith via Docker Compose  

---

## 1. High-Level Architectural Topology

```
                                  +---------------------------------------+
                                  |            Client Browser             |
                                  |     React 19 + TypeScript (Vite)      |
                                  +-------------------+-------------------+
                                                      |
                                                      | HTTP / Reverse Proxy (:5173 / :80)
                                                      v
                                  +---------------------------------------+
                                  |           Nginx / Vite Proxy          |
                                  +-------------------+-------------------+
                                                      |
                                       +--------------+---------------+
                                       | /api/*                       | /pi-agent/*
                                       v                              v
+------------------------------------------+    HTTP RPC    +------------------------------------------+
|            FastAPI API Server            |<-------------->|          Pi Coding Agent Service         |
|  - Auth & Authoritative Settings         | (internal tool |  - Express.js + TypeScript               |
|  - Direct Conversational RAG Engine      |  callbacks)    |  - Multi-turn ReAct Loop                 |
|  - Writing Studio Job Dispatcher         |                |  - Tools: search_transcripts, context    |
|  - HTML Sanitization & Version API       |                +------------------------------------------+
+-------------------+----------------------+
                    |
          +---------+---------+
          |                   |
          v                   v
+-------------------+   +--------------------+
|   PostgreSQL 17   |   |   Redis 7 Alpine   |
|   + pgvector      |   |   - Durable Queue  |
| - 303 episodes    |   |   - Job Pub/Sub    |
| - 17,365 chunks   |   +---------+----------+
| - 768-dim vectors |             |
| - Writing Jobs    |             | BRPOP
| - Artifacts & vN  |             v
| - App Settings    |   +------------------------------------------+
+-------------------+   |          Writing Background Worker       |
                        |  - Standalone Python Process             |
                        |  - Durable Job Polling & Concurrency (2) |
                        |  - Heartbeat & Stale Job Recovery        |
                        |  - 4-Stage Research & Drafting Pipeline  |
                        |  - Mandatory Quality Evaluation Gate     |
                        +--------------------+---------------------+
                                             |
                         +-------------------+-------------------+
                         |                                       |
                         v                                       v
        +---------------------------------+     +---------------------------------+
        |          Local Ollama           |     |         NVIDIA NIM Cloud        |
        |  - Chat: qwen2.5:1.5b           |     |  - Model: openai/gpt-oss-20b    |
        |  - Embed: nomic-embed-text:v1.5 |     |  - Endpoint: api.nvidia.com/v1  |
        +---------------------------------+     +---------------------------------+
```

---

## 2. Core Subsystems & Boundaries

### 2.1 Storage & Vector Engine (PostgreSQL + pgvector)
- **Database Engine:** PostgreSQL 17 with `pgvector` v0.8.7.
- **Key Tables:**
  - `episodes`: Stores 303 transcribed podcast episodes, metadata, guest details, and YouTube IDs (non-unique constraint to accommodate multi-part uploads).
  - `transcript_chunks`: 17,365 text chunks with 768-dimensional vector embeddings, start/end timestamps, and foreign keys to `episodes`.
  - `chat_sessions` & `chat_messages`: Multi-turn conversational history with session isolation.
  - `writing_artifacts` & `writing_artifact_versions`: Immutable document versioning tree with Markdown and rendered HTML.
  - `writing_jobs`: Background job tracking with status (`queued`, `running`, `completed`, `failed`), heartbeats, and retry counters.
  - `app_settings`: Authoritative runtime model configuration (`active_provider`, `chat_model`, `embedding_model`).

### 2.2 Dual Orchestration Subsystem
1. **Direct Conversational RAG Engine (FastAPI):**
   - Sub-second conversational responses.
   - Embeds query using `nomic-embed-text:v1.5`, queries cosine distance against `transcript_chunks`, suppresses duplicates across identical episodes, and synthesizes answers with strict citation formatting.
2. **Autonomous Pi Coding Agent (Node.js/Express):**
   - Autonomous ReAct agent utilizing tool-calling loops.
   - Communicates back to FastAPI internal endpoints (`/api/v1/internal/retrieval/search`) using shared internal tokens.
   - Executes multi-step investigative search and transcript context inspection.

### 2.3 Durable Writing Background Worker Subsystem
- **Queue Coordination:** Primary queue via Redis list `lenny:writing:jobs` using `BRPOP`; automatic fallback to PostgreSQL polling (`status = 'queued'`) if Redis is unreachable.
- **Crash Recovery:** Worker startup initiates `recover_stale_jobs()` which scans for jobs abandoned in `running` status without recent heartbeats.
- **Snapshot Integrity:** Jobs snapshot the active provider and model at queue time without injecting execution fields into the validated user brief (`unpack_job_brief()`).
- **Ship 30 for 30 Pipeline:**
  1. `Research`: Multi-query semantic retrieval collecting grounded evidence chunks.
  2. `Drafting`: Prompt engineering enforcing Nicolas Cole & Dickie Bush Ship 30 for 30 structures (Hook, Thesis, Framework, Takeaway).
  3. `Quality Gate`: Deterministic checks measuring body word count tolerance, section presence, and citation integrity.
  4. `Bounded Revision`: If quality checks fail, a targeted length and structural correction is executed once. If still out-of-range, the draft is persisted and flagged with diagnostic metadata.
  5. `Persistence`: Writing artifact and initial immutable version created in PostgreSQL.

### 2.4 Asynchronous AI Revision Subsystem
- Revisions requested in the Artifact Viewer are submitted as non-blocking background jobs returning HTTP 202 with `job_id`.
- The worker executes the revision, verifies that the artifact version has not been concurrently mutated by the user, and commits the result as a new incremented version `vN`.
- The frontend polls the job until completion, avoiding HTTP client timeouts.

---

## 3. Security & Sandboxing Architecture

1. **HTML Preview Isolation:**
   - Server-side sanitization with `nh3` removes script tags, event handlers, and dangerous iframe attributes.
   - Client-side iframe rendering uses a restrictive sandbox (`sandbox=""` with no `allow-scripts` or `allow-same-origin`).
2. **Secret Governance:**
   - Server-side environment variables manage API keys (e.g. `NVIDIA_API_KEY`).
   - Secrets are excluded from client bundles, logs, and Git tracking.
3. **Citation Provenance:**
   - All citations displayed to the user must resolve to actual database `chunk_id` records. Hallucinated chunk IDs are rejected during evaluation.

---

## 4. Multi-Model Runtime Switching

- **Local Inference:** Ollama HTTP API (`http://host.docker.internal:11434`), running `qwen2.5:1.5b` for chat and `nomic-embed-text:v1.5` for vector embeddings.
- **Cloud Inference:** NVIDIA NIM OpenAI-compatible Chat Completions API (`https://integrate.api.nvidia.com/v1`), running `openai/gpt-oss-20b`.
- **Authoritative Synchronization:** Selecting a provider in the frontend updates the database settings table. Subsequent chat requests and background jobs inherit the selected provider snapshot.
