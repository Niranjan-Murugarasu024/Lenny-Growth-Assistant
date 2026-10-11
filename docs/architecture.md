# Architecture — The Lenny Growth Assistant

## 1. Intended Architecture

The application will consist of a React frontend, a FastAPI backend, PostgreSQL with pgvector, an application-controlled agent/tool layer, and configurable local and cloud inference providers.

## 2. Component Responsibilities

### Frontend

- Conversational chat interface.
- Independent chat sessions.
- Model/provider selection.
- Source citations and transcript references.
- Markdown and HTML/CSS artifact viewer.

### FastAPI Backend

- Validate incoming API requests.
- Manage session and message persistence.
- Coordinate retrieval, the selected model, and application skills.
- Expose health endpoints and structured errors.
- Enforce source and artifact-rendering policies.

### PostgreSQL and pgvector

- Store episode metadata and transcript chunks.
- Store chunk embeddings and provenance.
- Persist sessions and conversations.
- Store generated artifacts and their session references.

### Transcript Ingestion

- Discover transcript files.
- Parse YAML frontmatter.
- Preserve source hashes (`source_sha256` and `body_sha256`) and paths.
- Clean and chunk content.
- Generate embeddings and write records to PostgreSQL.

#### Schema & Ingestion Principles (Task 2 Readiness)

Audit findings dictate the following schema and ingestion rules:
- **Internal episode ID**: Generate a surrogate primary key independent of external IDs.
- **Transcript source path**: Required and traceable relative path.
- **Source platform**: Explicit enum/string (e.g. YouTube, Spotify) allowing non-YouTube episodes.
- **Source URL**: Nullable or represented in a separate source-links table.
- **YouTube video ID**: Nullable; no unique constraint on `video_id` (due to 31 upstream collisions and attribution errors).
- **Publication date**: Nullable when unavailable.
- **Source-file hash**: Retain for file integrity and change detection.
- **Dialogue-body hash**: Use to detect duplicated dialogue (6 identified pairs) without premature deletion.

### Model Configuration

- Support Ollama for the mandatory local demonstration.
- Support a verified cloud-model path through a configuration layer.
- Keep embedding-model configuration independent of the chat model.
- Handle provider failures and timeouts explicitly.

### Skills and Tools

- Transcript retrieval and grounded Q&A.
- Ship 30 for 30-style essay generation.
- Markdown and HTML/CSS artifact creation.

## 3. Current Milestone

Task 1 establishes the repository, audits the transcript source, and records corpus metadata in a generated manifest.

No vector database, embeddings, FastAPI endpoints, agents, or frontend features are implemented in this milestone.

## 4. Initial Security Principles

- Do not commit secrets or raw transcript files.
- Validate all incoming API requests.
- Only expose explicitly authorized application tools to the agent.
- Treat generated HTML as untrusted content and isolate its rendering.
- Validate citations against stored source records.
