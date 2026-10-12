# Security Architecture and Secrets Management

This document defines the security posture, secrets management policies, network boundaries, and content sanitization practices for **The Lenny Growth Assistant**.

---

## 1. Secrets Management and Environment Separation

### 1.1 Local vs. Production Secrets
- **Local Development**: Configuration is loaded from `.env` (ignored by Git). Default development credentials in `.env.example` are non-sensitive placeholders.
- **Production Deployment**: Secrets must never be stored in files or baked into Docker images. Secrets should be injected dynamically via container runtime environment variables or a secrets manager (e.g., AWS Secrets Manager, HashiCorp Vault, Kubernetes Secrets).

### 1.2 Tracked File Hygiene
- `.env` and `.env.*` files are explicitly excluded in `.gitignore` (with `!.env.example` as a template).
- `.env.example` contains only non-sensitive placeholders.
- Secret audits run via automated scripts (`scripts/audit_security.py`) and CI secret scanning prevent accidental credential leaks.

---

## 2. Key Rotation Procedures

When rotating credentials, follow these zero-downtime procedures:

### 2.1 Internal Agent Service Token (`AGENT_INTERNAL_TOKEN`)
The internal token authenticates inter-service communication between the `pi-agent` (Node.js) and the `api` (FastAPI).
1. Generate a new high-entropy secret (e.g. `openssl rand -hex 32`).
2. Update the environment variables for both `api` and `pi-agent` services.
3. Perform a rolling restart (`docker compose up -d --no-deps api pi-agent`).

### 2.2 PostgreSQL Database Password (`POSTGRES_PASSWORD`)
1. Create a secondary database user or update the existing user's password in PostgreSQL:
   ```sql
   ALTER USER lenny_app WITH PASSWORD 'new_secure_password';
   ```
2. Update `DATABASE_URL` in `api` and `worker` configurations.
3. Restart backend services.

### 2.3 Cloud Model Provider Keys (`NVIDIA_API_KEY` / `LITELLM_API_KEY`)
1. Issue a new API key from the upstream provider (e.g., NVIDIA NIM API Key or LiteLLM proxy).
2. Update `NVIDIA_API_KEY` or `LITELLM_API_KEY` in the server environment.
3. Restart `api` and `worker`.
4. Revoke the old key in the provider console once traffic is verified.

---

## 3. Network Boundaries and Port Isolation

| Service | Intended Access | Network Binding (Dev) | Network Binding (Prod) | Authentication |
| :--- | :--- | :--- | :--- | :--- |
| **Frontend** | Public Internet | `127.0.0.1:5173` | Reverse proxy / 443 | Public |
| **FastAPI Backend** | Reverse proxy only | `127.0.0.1:8000` | Internal container network | Public `/api/v1/` routes; Auth on `/internal/v1/` |
| **Worker** | Internal Only | None (no exposed port) | None | Background process |
| **PostgreSQL** | Internal Only | `127.0.0.1:5435` | Internal container network (`5432`) | Password (`SCRAM-SHA-256`) |
| **Redis** | Internal Only | `127.0.0.1:6379` | Internal container network (`6379`) | Internal network isolation |
| **Pi Agent** | Internal Only | `127.0.0.1:3000` | Internal container network (`3000`) | Bearer token (`AGENT_INTERNAL_TOKEN`) |

In production deployments, **never bind database, Redis, or internal agent ports to `0.0.0.0`**. All inter-service communication is confined to the private Docker bridge network.

---

## 4. Agent Tool Sandboxing and Least Privilege

The Pi Coding Agent service (`agent-service/`) is strictly sandboxed:
- **Registered Tool Allowlist**: The Pi agent is exposed to only one registered tool: `search_transcripts`.
- **No Arbitrary Execution**: The agent has **no shell access**, **no filesystem write access**, and **no arbitrary outbound HTTP capability**.
- **Internal Authentication**: Calls from `pi-agent` to the internal API route (`/internal/v1/transcripts/search`) require a valid `Bearer ${AGENT_INTERNAL_TOKEN}` header.

---

## 5. Content Sanitization & Sandboxing
 
### 5.1 HTML Preview Sanitization
User-generated Markdown is converted to HTML and strictly sanitized on the backend using `nh3`:
- Only safe tags (`p`, `h1`-`h6`, `strong`, `em`, `ul`, `ol`, `li`, `blockquote`, `code`, `pre`, `cite`, `span`, `div`, `table`, `thead`, `tbody`, `tr`, `th`, `td`) are allowed.
- All `<script>`, `<iframe>`, `<object>`, `<embed>`, inline event handlers (`onclick`, `onerror`), and `javascript:` URIs are stripped.

### 5.2 Browser Iframe Sandboxing
The React Writing Studio renders the sanitized HTML inside an `iframe` with a restrictive sandbox attribute:
```html
<iframe sandbox="" srcDoc={sanitizedHtml} />
```
This strictly prohibits script execution, popups, and top-level navigation while permitting styling and clean document display.

---

## 6. Prompt Privacy and Sensitive Data Handling

- User queries and generated essays are stored locally in the PostgreSQL database.
- When running in local mode with Ollama (`CHAT_PROVIDER=ollama`), inference occurs entirely on the host machine without transmitting data to external third parties.
- When optional cloud inference (`CHAT_PROVIDER=litellm`) is configured, only the retrieved transcript excerpts and user brief are sent to the designated endpoint.
- Logging configurations (`backend/app/config.py`) explicitly redact authorization headers, bearer tokens, and connection strings from console output.
