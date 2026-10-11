# The Lenny Growth Assistant

A source-grounded conversational assistant for product management and growth knowledge from Lenny's Podcast transcripts.

## Current Milestone

Task 1: repository bootstrap and transcript corpus audit.

## Prerequisites

- Git
- Python 3.12
- PowerShell on Windows

## Local Setup

Clone the transcript source into:

`data/raw/lennys-podcast-transcripts`

Create and activate a virtual environment:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install development dependencies:

```powershell
python -m pip install -r requirements-dev.txt
```

Run the corpus audit:

```powershell
python scripts/audit_corpus.py
```

This generates `data/manifest.json`.

Run tests:

```powershell
python -m pytest -q
```

## Data Handling

The raw transcript repository and local environment configuration are excluded from Git. The manifest records source paths, selected metadata, hashes, and audit statistics.

## Planned Components

- FastAPI backend
- PostgreSQL and pgvector
- Ollama and configurable cloud inference
- Transcript-grounded RAG
- Writing and artifact skills
- React frontend and artifact viewer

See `docs/PRD.md` and `docs/architecture.md` for the product and architecture plans.