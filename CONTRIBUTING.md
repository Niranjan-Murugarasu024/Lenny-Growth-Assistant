# Contributing to The Lenny Growth Assistant

We welcome contributions to **The Lenny Growth Assistant**. This document provides guidelines for development setup, testing, coding standards, and design workflows.

---

## 1. Development Environment Setup

### 1.1 Python Backend
- Python 3.11+ required.
```bash
python -m venv .venv
source .venv/bin/activate  # Or .\.venv\Scripts\Activate.ps1 on Windows
pip install -r requirements.txt -r requirements-dev.txt
```

### 1.2 Frontend (Writing Studio)
- Node.js 22 LTS required.
```bash
cd frontend
npm ci
npm run dev
```

### 1.3 Pi Coding Agent Service
- Node.js 22 LTS required.
```bash
cd agent-service
npm ci
npm run dev
```

---

## 2. Automated Testing

Before submitting a pull request, all test suites must pass:

### 2.1 Backend Tests
```bash
python -m pytest
```

### 2.2 Frontend Tests & Type Checking
```bash
cd frontend
npm test
npm run build
```

### 2.3 Pi Agent Tests & Build
```bash
cd agent-service
npm test
npm run build
```

---

## 3. Database Migrations

When modifying database models:
1. Update models in `backend/app/models.py`.
2. Generate an Alembic migration:
   ```bash
   alembic revision --autogenerate -m "describe_changes"
   ```
3. Inspect and verify the migration in `alembic/versions/`.
4. Apply the migration:
   ```bash
   alembic upgrade head
   ```

---

## 4. Impeccable Design Workflow

The project follows the [Impeccable.style](https://impeccable.style) design principles recorded in `PRODUCT.md` and `DESIGN.md`.

When modifying frontend components:
1. Review [`DESIGN.md`](./DESIGN.md) for approved typography, colors, layout rules, and component patterns.
2. Run the mechanical design anti-pattern detector:
   ```bash
   .\.agents\skills\impeccable\scripts\impeccable.cmd detect frontend/src/
   ```
3. Ensure zero anti-patterns are introduced.

---

## 5. Security & Secret Protection

- Never commit `.env` or files containing live credentials.
- Verify exclusions before committing:
   ```bash
   git status --ignored
   python scripts/audit_security.py
   ```
- Ensure any public API responses do not expose internal bearer tokens or private database connection details.
