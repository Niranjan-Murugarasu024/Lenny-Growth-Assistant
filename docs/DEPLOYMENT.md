# Production Deployment Guide

This guide describes how to deploy **The Lenny Growth Assistant** in production environments using Docker Compose, container registries, and cloud infrastructure.

---

## 1. Architecture and Services

The application consists of 6 coordinated services:

```
                  ┌──────────────────────────────┐
                  │    Public Client / Browser   │
                  └──────────────┬───────────────┘
                                 │
                     HTTP / HTTPS (Port 80/443)
                                 ▼
                    ┌──────────────────────────┐
                    │    Frontend (Nginx)      │
                    │   React 19 / Vite SPA    │
                    └────────────┬─────────────┘
                                 │ Proxies /api/ & /health/
                                 ▼
                    ┌──────────────────────────┐
                    │      FastAPI Backend     │
                    │         (Port 8000)      │
                    └──────┬──────┬──────┬─────┘
                           │      │      │
            SQL Queries /  │      │      │ Redis Queue /
            Embeddings     │      │      │ Job Coordination
                           ▼      │      ▼
      ┌───────────────────────┐   │   ┌─────────────────────┐
      │  PostgreSQL 17 +      │   │   │       Redis 7       │
      │  pgvector (303 eps)   │   │   │    Durable Queue    │
      └───────────────────────┘   │   └──────────┬──────────┘
                                  │              │
        Internal Transcript Search│              │ Consumes Jobs
        (Token Auth: Bearer)      │              ▼
                                  │   ┌─────────────────────┐
                                  │   │  Background Worker  │
                                  │   │  (Durable Writing)  │
                                  │   └──────────┬──────────┘
                                  ▼              │
                      ┌───────────────────────┐  │
                      │    Pi Coding Agent    │  │
                      │  TypeScript Service   │  │
                      └───────────┬───────────┘  │
                                  │              │
                                  ▼              ▼
                      ┌─────────────────────────────────────┐
                      │    Inference Provider (Ollama or    │
                      │    LiteLLM / OpenAI / Anthropic)    │
                      └─────────────────────────────────────┘
```

---

## 2. Prerequisites

- **Docker Engine** 24.0+ and **Docker Compose** v2.20+.
- Recommended hardware:
  - **Local inference (Ollama)**: Minimum 16GB RAM and GPU (Apple Silicon or NVIDIA 8GB+ VRAM).
  - **Cloud inference (LiteLLM)**: Minimum 4GB RAM (CPU-only).
- Outbound network access for cloud inference if LiteLLM is configured.

---

## 3. Configuration & Environment Variables

Copy `.env.example` to `.env` on your deployment server:
```bash
cp .env.example .env
chmod 600 .env
```

### Critical Production Settings
| Variable | Description | Example / Default |
| :--- | :--- | :--- |
| `POSTGRES_DB` | PostgreSQL database name | `lenny_growth` |
| `POSTGRES_USER` | PostgreSQL user | `lenny_app` |
| `POSTGRES_PASSWORD` | Strong database password | `generate-random-secret` |
| `DATABASE_URL` | SQLAlchemy connection string | `postgresql+psycopg://lenny_app:...@db:5432/lenny_growth` |
| `REDIS_URL` | Redis connection string | `redis://redis:6379/0` |
| `AGENT_INTERNAL_TOKEN` | Secret bearer token between services | `generate-random-secret` |
| `CHAT_PROVIDER` | Initial default inference provider (`ollama` or `nvidia`) | `ollama` (demo) / `nvidia` (cloud) |
| `OLLAMA_CHAT_MODEL` | Local chat model identifier | `qwen2.5:1.5b` |
| `NVIDIA_BASE_URL` | NVIDIA NIM OpenAI-compatible endpoint | `https://integrate.api.nvidia.com/v1` |
| `NVIDIA_MODEL` | Cloud model identifier | `openai/gpt-oss-20b` |
| `NVIDIA_API_KEY` | Upstream NVIDIA NIM API key (keep confidential) | `nvapi-...` |
| `NVIDIA_TIMEOUT_SECONDS`| Connection & read timeout | `120.0` |

---

## 4. Model Connectivity & Runtime Switching

### 4.1 NVIDIA NIM Cloud Inference (`openai/gpt-oss-20b`)
Configure upstream credentials in `.env`:
```env
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_MODEL=openai/gpt-oss-20b
NVIDIA_API_KEY=nvapi-your-key-here
NVIDIA_TIMEOUT_SECONDS=120.0
```

### 4.2 Local Inference (Ollama `qwen2.5:1.5b`)
Mandatory local option:
```env
CHAT_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_CHAT_MODEL=qwen2.5:1.5b
EMBEDDING_MODEL=nomic-embed-text:v1.5
```

### 4.3 Runtime Provider Switching via API / UI
The active model can be inspected and switched without redeployment or editing `.env`:
- **Read Active Configuration**:
  ```bash
  curl -s http://127.0.0.1:8000/api/v1/settings/llm
  ```
- **Switch Provider to NVIDIA NIM**:
  ```bash
  curl -X PUT http://127.0.0.1:8000/api/v1/settings/llm \
    -H "Content-Type: application/json" \
    -d '{"provider": "nvidia"}'
  ```
- **Switch Provider to Ollama**:
  ```bash
  curl -X PUT http://127.0.0.1:8000/api/v1/settings/llm \
    -H "Content-Type: application/json" \
    -d '{"provider": "ollama"}'
  ```
- **Perform Live Connection Test**:
  ```bash
  curl -X POST http://127.0.0.1:8000/api/v1/settings/llm/test \
    -H "Content-Type: application/json" \
    -d '{"provider": "nvidia"}'
  ```

Selection is authoritatively stored in PostgreSQL `app_settings` and automatically respected across both FastAPI workers and background writing worker processes.

---

## 5. Deployment Commands

### Step 1: Pre-Release Database Migration
Always run Alembic migrations before starting traffic:
```bash
docker compose run --rm api alembic upgrade head
```

### Step 2: Launch Production Stack
```bash
# Launch with production isolation overrides
docker compose -f compose.yaml -f compose.prod.yaml up -d --build
```

### Step 3: Verify Health Probes
```bash
# Check liveness
curl -f http://127.0.0.1:8000/health/live

# Check readiness (verifies DB, Redis, and inference connectivity)
curl -f http://127.0.0.1:8000/health/ready
```

---

## 6. Database Backup & Disaster Recovery

### 6.1 Backing up PostgreSQL
To create a compressed custom-format backup of the database:
```bash
# Snapshot to local timestamped file
docker compose exec db pg_dump -U lenny_app -d lenny_growth -F c -f /tmp/backup.dump
docker compose cp db:/tmp/backup.dump ./backups/lenny_growth_$(date +%Y%m%d_%H%M%S).dump
docker compose exec db rm /tmp/backup.dump
```

### 6.2 Restoring PostgreSQL
```bash
# Copy backup into container and restore cleanly
docker compose cp ./backups/your_backup.dump db:/tmp/restore.dump
docker compose exec db pg_restore -U lenny_app -d lenny_growth --clean --if-exists /tmp/restore.dump
docker compose exec db rm /tmp/restore.dump
```

### 6.3 Redis Recovery
Redis state in production is persisted via append-only files in volume `lenny_growth_redisdata`. If Redis crashes or restarts, jobs in-flight are automatically detected by the background worker as stale heartbeats and requeued according to the bounded retry policy (`MAX_JOB_RETRIES=2`).

---

## 7. Operational Runbook & Recovery

| Failure Mode | Symptoms | Automated Behavior | Operator Remediation |
| :--- | :--- | :--- | :--- |
| **Worker Crash** | Job in `running` state with stopped worker | On worker boot, stale heartbeats (>300s) are re-queued up to retry limit. | Restart worker container (`docker compose restart worker`). |
| **API Restart** | In-flight requests drop | Completed jobs and artifact versions remain saved in PostgreSQL. | Client retries idempotent requests; jobs resume polling. |
| **Redis Crash** | Worker queue unavailable | Worker reconnects with exponential backoff; PostgreSQL remains source of truth. | Restart Redis (`docker compose restart redis`). |
| **Model Timeout** | Essay draft generation exceeds timeout | Job marked `failed` with diagnostic timeout message; draft attempt preserved. | Verify provider quota, API key validity, or model latency. |
