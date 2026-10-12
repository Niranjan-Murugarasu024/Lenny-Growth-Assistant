# The Lenny Growth Assistant

> **"Ask product, growth and startup questions. Get answers grounded in Lenny's Podcast, with traceable sources and reusable artifacts."**

A production-grade, source-grounded conversational AI assistant built on 303 episodes and 17,365 embedded transcript chunks from **Lenny's Podcast**. The platform enables founders, product leaders, and operators to ask strategic, tactical, and operational questions, receive answers grounded with backend-verified citations and YouTube timestamps, and contextually compose publication-grade **Ship 30 for 30** essays with deterministic quality evaluation and immutable versioning.

---

## Architecture Overview

```
                                ┌───────────────────────────────────────┐
                                │       Web Browser / Client UI         │
                                └───────────────────┬───────────────────┘
                                                    │
                                         HTTP / Port 5173 / 80
                                                    ▼
                                    ┌──────────────────────────────┐
                                    │    Frontend (Nginx / Vite)   │
                                    │   React 19 Chat-First App    │
                                    └───────────────┬──────────────┘
                                                    │ Proxies /api/ & /health/
                                                    ▼
                                    ┌──────────────────────────────┐
                                    │     FastAPI REST Backend     │
                                    │          (Port 8000)         │
                                    └───────┬───────┬───────┬──────┘
                                            │       │       │
                      SQL Queries /         │       │       │ Redis Enqueue /
                      pgvector Embeddings   │       │       │ Job Coordination
                                            ▼       │       ▼
       ┌────────────────────────────────────────┐   │   ┌────────────────────────┐
       │   PostgreSQL 17 + pgvector             │   │   │        Redis 7         │
       │   - 303 Podcast Episodes               │   │   │     Durable Queue      │
       │   - 17,365 Transcript Chunks           │   │   └───────────┬────────────┘
       │   - GIN Lexical tsvector Index         │   │               │
       │   - Sessions & Writing Artifacts       │   │               │ Consumes Jobs
       └────────────────────────────────────────┘   │               ▼
                                                    │   ┌────────────────────────┐
                         Internal Transcript Search │   │   Background Worker    │
                         (Bearer Token Auth)        │   │   - Essay Generator    │
                                                    │   │   - Quality Evaluator  │
                                                    │   └───────────┬────────────┘
                                                    ▼               │
                                        ┌────────────────────────┐  │
                                        │    Pi Coding Agent     │  │
                                        │   TypeScript Service   │  │
                                        │       (Port 3000)      │  │
                                        └───────────┬────────────┘  │
                                                    │               │
                                                    ▼               ▼
                                        ┌────────────────────────────────────────┐
                                        │           Inference Layer              │
                                        │   - Local: Ollama (qwen2.5:1.5b)       │
                                        │   - Cloud: NVIDIA NIM (gpt-oss-20b)    │
                                        └────────────────────────────────────────┘
```

---

## Key Features & Design Decisions

1. **Source Grounding & Provenance**: Every response and essay citation maps directly to real podcast dialogue with verified episode titles, guest names, timestamps, and database chunk IDs.
2. **Hybrid Retrieval with Reciprocal Rank Fusion (RRF)**: Combines dense vector embeddings (`nomic-embed-text:v1.5`, 768d) with PostgreSQL full-text search (`tsvector` + GIN index) to ensure precise discovery of named frameworks (e.g. Rahul Vohra's PMF engine, Brian Chesky's 11-star framework) alongside semantic concepts.
3. **Autonomous Pi Coding Agent SDK**: Autonomous multi-turn reasoning orchestrated by a dedicated Node.js microservice (`agent-service/`) utilizing the Pi Coding Agent SDK with strict tool allowlists (`search_transcripts`, `get_transcript_context`) and zero host OS/filesystem access.
4. **Durable Writing Infrastructure**: Asynchronous Ship 30 for 30 essay generation coordinated via Redis and persisted in PostgreSQL. Interrupted jobs are automatically recovered via stale-heartbeat detection with bounded retries.
5. **Deterministic Quality Gate**: Essays are accepted into a `completed` state only if they satisfy strict deterministic criteria: body word count within target tolerance (±10%), minimum 2 structural headings, identified thesis statement, and 100% verified citations in PostgreSQL.
6. **Immutable Versioning & Safe Preview**: Manually edited or AI-revised essays are saved as immutable versions. HTML previews are sanitized on the backend using Rust-powered `nh3` and rendered in sandboxed iframes.
7. **Impeccable Design System**: Built following [Impeccable.style](https://impeccable.style) guidelines for editorial typography, 68ch reading measure, calm color palette, high-contrast focus rings, and zero AI-card visual clutter.

---

## Service Port Allocation

| Service | Port | Description | Internal / Public |
| :--- | :---: | :--- | :--- |
| **Frontend** | `5173` (or `80`) | React 19 Writing Studio served by Nginx | Public entrypoint |
| **FastAPI Backend** | `8000` | REST API, chat, internal tools, and jobs | Loopback / Reverse proxy |
| **Worker** | None | Standalone Python background worker | Internal background process |
| **PostgreSQL 17** | `5435` (or `5432`) | Relational store, pgvector, full-text indexes | Loopback / Internal network |
| **Redis 7** | `6379` | Queue and job state coordination | Loopback / Internal network |
| **Pi Agent Service** | `3000` | Node.js Pi Coding Agent SDK microservice | Internal network / Token auth |

---

## Prerequisites

- **Docker & Docker Compose** (v2.20+ recommended)
- **Node.js** 22 LTS or newer
- **Python** 3.11+
- **Inference Engine**:
  - **Local (Default)**: Ollama with models `qwen2.5:1.5b` and `nomic-embed-text:v1.5`.
  - **Cloud (Optional)**: NVIDIA NIM API key (`openai/gpt-oss-20b`) via `NVIDIA_API_KEY`.

---

## Quickstart: Docker Compose (Recommended)

1. **Clone the repository and copy environment configuration**:
   ```bash
   cp .env.example .env
   ```
2. **Start all 6 services**:
   ```bash
   docker compose up -d --build
   ```
3. **Verify service health**:
   ```bash
   docker compose ps
   curl -f http://127.0.0.1:8000/health/ready
   ```
4. **Open the Writing Studio**:
   Navigate to `http://localhost:5173` in your browser.

---

## Local Development Setup

### 1. Python Backend & Background Worker
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt

# Run database migrations
alembic upgrade head

# Start API server (Terminal 1)
uvicorn backend.app.api.main:app --host 127.0.0.1 --port 8000 --reload

# Start Background Worker (Terminal 2)
python -m backend.app.writing.worker
```

### 2. Frontend (Writing Studio)
```bash
cd frontend
npm ci
npm run dev
# Dev server starts at http://localhost:5173
```

### 3. Pi Coding Agent Service
```bash
cd agent-service
npm ci
npm run build
npm start
# Agent service starts at http://localhost:3000
```

---

## Automated Testing & Quality Verification

Run all test suites across Python, Frontend, and Pi Agent:

```bash
# 1. Python Backend Test Suite (212 tests)
.\.venv\Scripts\python.exe -m pytest

# 2. Frontend Component & Client Test Suite (22 tests)
cd frontend
npm test
npm run build
cd ..

# 3. Pi Coding Agent Test Suite (7 tests)
cd agent-service
npm test
npm run build
cd ..

# 4. End-to-End Release Smoke Test (Exercises entire containerized stack)
.\.venv\Scripts\python.exe scripts/release_smoke_test.py
```

---

## Impeccable Design System Workflow

The project incorporates [Impeccable.style](https://impeccable.style) tools and guidelines directly:
- **`PRODUCT.md`**: Defines target personas, positioning, capabilities, brand commitments, and principles.
- **`DESIGN.md`**: Encodes design tokens (colors, typography, layout, elevations, shapes, components) and rules.

### Running Impeccable Workflows
```bash
# Display loaded session context and token definitions
.\.agents\skills\impeccable\scripts\impeccable.cmd context

# Run mechanical anti-pattern detection over frontend code
.\.agents\skills\impeccable\scripts\impeccable.cmd detect frontend/src/

# Run critique storage helper to record or view trend scores
.\.agents\skills\impeccable\scripts\impeccable.cmd critique-storage trend "frontend/src" 5
```

---

## Inference Configuration: Runtime Model Switcher & NVIDIA NIM

The Lenny Growth Assistant supports real-time, runtime switching between local Ollama and cloud NVIDIA NIM models directly through the UI header—with zero code edits and zero application restarts.

### Supported Models

| Option | Provider | Model Identifier | Endpoint | Category |
| :--- | :--- | :--- | :--- | :---: |
| **Local Model** | Ollama | `qwen2.5:1.5b` | `http://localhost:11434` | `Local` |
| **Cloud Model** | NVIDIA NIM | `openai/gpt-oss-20b` | `https://integrate.api.nvidia.com/v1` | `Cloud` |

---

### 1. Configuring NVIDIA NIM Locally

To enable the cloud model, add your NVIDIA API key to your local, Git-ignored `.env` file:

```dotenv
# NVIDIA NIM Cloud Inference Configuration
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_MODEL=openai/gpt-oss-20b
NVIDIA_API_KEY=nvapi-your-actual-api-key-here
NVIDIA_TIMEOUT_SECONDS=120.0
```

> [!NOTE]
> `NVIDIA_API_KEY` is kept blank in `.env.example` and is strictly loaded from the backend environment. The key is never logged, never returned in API payloads, never stored in the database, and never bundled into the browser frontend.

---

### 2. Runtime Model Switcher in the UI

The application header features an authoritative **Model Selector**:
- **Ollama · qwen2.5:1.5b** — Badge: `[LOCAL]`
- **NVIDIA NIM · openai/gpt-oss-20b** — Badge: `[CLOUD]`

When you select a model in the dropdown:
1. The frontend dispatches a `PUT /api/v1/settings/llm` request to the backend.
2. The backend validates the provider against an explicit allowlist and confirms credentials are configured.
3. The selection is authoritatively persisted in the PostgreSQL `app_settings` table.
4. Both the **FastAPI process** and the **asynchronous background writing worker** immediately read the updated setting.
5. In-flight writing jobs snapshot their model selection deterministically so jobs are not corrupted mid-flight.
6. The UI updates its badges and status indicators upon backend confirmation.

---

### 3. Live Provider Connectivity Testing

Next to the model selector in the header, click the **⚡ Test** button (or call `POST /api/v1/settings/llm/test`):
- Executes a safe, minimal completion request (`max_tokens=5`) against the selected endpoint.
- Displays immediate live status:
  - `✓ Connected (0.35s)`: Upstream inference endpoint reachable and credentials valid.
  - `✕ Not Configured`: `NVIDIA_API_KEY` is not present in `.env`.
  - `✕ Unavailable`: Upstream service unreachable or returned an actionable error (e.g. 401 Unauthorized, 429 Quota Exceeded).

---

### 4. Explicit Fallback & Safe Error Behavior

- **No Silent Fallback**: When the selected cloud model fails, the system returns an explicit, actionable error rather than silently falling back to a local model or claiming the cloud model answered.
- **Error Preservation**: Cloud authentication errors (401), rate limits (429), timeouts, and network issues are mapped to clear application errors and displayed to the user.
- **Ollama Remains Operational**: Even if NVIDIA NIM is unconfigured or unreachable, the mandatory local Ollama option remains 100% operational.

---

### 5. Running the Mandatory Local Ollama Demo

1. Verify that Ollama has the required models installed:
   ```powershell
   ollama list
   ```
   Confirm `qwen2.5:1.5b` and `nomic-embed-text:v1.5` are listed. (If needed: `ollama pull qwen2.5:1.5b` and `ollama pull nomic-embed-text:v1.5`).
2. Start the application:
   ```bash
   docker compose up -d
   ```
3. Open `http://localhost:5173`.
4. Ensure the header selector shows **Ollama · qwen2.5:1.5b** `[Local]`.
5. Ask any product question in chat or generate a Ship 30 for 30 essay. All inference runs entirely on your local machine with full RAG grounding, citations, and quality validation.

---

## HTML Security and Sandbox Architecture

Model-generated documents and HTML/CSS snippets are strictly treated as **untrusted user input**. To enable rich, visually expressive artifacts while providing defense-in-depth against Cross-Site Scripting (XSS) and credential exfiltration, the platform implements a dual-layer security boundary:

### 1. Server-Side HTML Sanitization (`nh3` / Rust Ammonia)
All generated Markdown documents and direct HTML snippets pass through `backend/app/writing/html_renderer.py` before persistence in PostgreSQL:
- **Permitted Elements**: Semantic typographical and layout tags: `h1`–`h6`, `p`, `b`, `strong`, `i`, `em`, `u`, `s`, `del`, `blockquote`, `pre`, `code`, `ul`, `ol`, `li`, `table`, `thead`, `tbody`, `tr`, `th`, `td`, `a`, `hr`, `br`, `span`, `div`.
- **Permitted Attributes**: Global `class` and `id`; `href`, `title`, `target` on `<a>`; `align` on `<th>`/`<td>`.
- **Permitted URL Schemes**: Strictly `http`, `https`, and `mailto`.
- **Automatic Hardening**: All hyperlinks automatically receive `rel="noopener noreferrer"`.
- **Blocked Active Content**:
  - Script execution: `<script>` tags, inline scripts, and dynamic code evaluation are completely stripped.
  - Event handlers: All `on*` attributes (`onerror`, `onclick`, `onload`, `onmouseover`, etc.) are stripped.
  - Unsafe schemes: `javascript:`, `data:`, `vbscript:`, and `file:` schemes are blocked.
  - Embedded objects: `<iframe>`, `<object>`, `<embed>`, `<svg>`, and external tracking embeds are blocked.

### 2. Client-Side Iframe Sandbox Isolation
The in-app viewer (`frontend/src/components/HtmlPreview.tsx`) renders sanitized HTML within a sandboxed `<iframe>`:
- **Sandbox Attribute**: `sandbox="allow-popups"` (strictly **omitting** `allow-scripts` and **omitting** `allow-same-origin`).
- **Opaque Origin**: Omitting `allow-same-origin` enforces a unique `null` origin, physically preventing the iframe from accessing the parent window's DOM (`window.parent.document`), cookies, `localStorage`, session history, or API tokens.
- **Zero Script Execution**: Omitting `allow-scripts` guarantees the browser will not execute any script inside the preview under any circumstance.
- **Safe Outbound Links**: `allow-popups` allows legitimate external reference links to open in a separate tab without granting script permissions.

### 3. Why This Design Works
Operators need publication-grade essays, formatted tables, and styled cards. By pairing deterministic backend sanitization via Rust-based `nh3` with an opaque, script-disabled frontend sandbox, the Lenny Growth Assistant safely delivers visually rich artifacts without exposing the host application to prompt injection or malicious payloads.

---

## Troubleshooting Guide

| Issue | Root Cause | Solution |
| :--- | :--- | :--- |
| **`LLM_SERVICE_UNAVAILABLE` (502)** | Ollama server is not running or unreachable from container. | Check `docker compose logs api`. Ensure `extra_hosts` resolves `host.docker.internal` to host gateway. |
| **`LLM_GENERATION_TIMEOUT` (504)** | Local model token generation exceeded timeout on CPU. | Increase `CHAT_TIMEOUT_SECONDS` (e.g. 240s) or switch to cloud model (`CHAT_PROVIDER=litellm`). |
| **Database connection refused** | PostgreSQL container is starting up or port collision. | Verify `docker compose ps db`. Use port `5435` on host to avoid local port 5432 conflicts. |
| **Redis connection failed** | Redis container stopped or queue unreachable. | Worker automatically falls back to in-memory queue; restart Redis with `docker compose restart redis`. |
| **Quality Evaluation Rejected Essay** | Draft body word count outside target tolerance window. | Diagnostic error is preserved in `writing_jobs.error` and draft version is saved for inspection. |

---

## Documentation Index

- [`PRD.md`](./PRD.md): Product Requirements Document, success metrics, user workflows, and scope.
- [`design.md`](./design.md): Design system, typography hierarchy, visual tokens, and responsive layouts.
- [`architecture.md`](./architecture.md): Microservices topology, background workers, and security model.
- [`PRODUCT.md`](./PRODUCT.md): Product vision, positioning, user personas, and principles.
- [`DESIGN.md`](./DESIGN.md): Machine-readable design tokens, component specifications, and Do's/Don'ts.
- [`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md): Production deployment guide, network isolation, backups, and disaster recovery.
- [`docs/SECURITY.md`](./docs/SECURITY.md): Secrets management, rotation procedures, tool sandboxing, and HTML sanitization.
- [`docs/DEMO.md`](./docs/DEMO.md): 2–3 minute repeatable product demonstration guide.
- [`docs/PRODUCT_AUDIT_REPORT.md`](./docs/PRODUCT_AUDIT_REPORT.md): Comprehensive architectural, UX, and reliability audit report.
- [`CONTRIBUTING.md`](./CONTRIBUTING.md): Coding guidelines, testing procedures, and pull request hygiene.
- [`LICENSE`](./LICENSE): MIT License and third-party podcast transcript copyright notice.
