# AIOS-CRM-Copilot

An internal AI service for real estate sales teams:

- **Team-lead twin:** grounded answers on projects, units, prices and policies, with citations.
- **CRM Copilot:** a client context card shown before every call, plus handover summaries when a lead is reassigned.

Full design: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Code organization: [`docs/adr/0001-modular-monolith-hexagonal.md`](docs/adr/0001-modular-monolith-hexagonal.md).

## Layout

```
backend/src/aios/
  shared/          config, errors, logging, roles
  modules/<ctx>/   domain/ application/ ports/ adapters/ api/
  orchestration/   LangGraph router + answer composer
  entrypoints/     FastAPI app (composition root), worker, MCP servers
frontend/          Next.js chat + CRM widget (Phase 3)
evals/             gold Q&A set + eval runners
infra/             deployment config
```

## Status

| Module | State |
|---|---|
| pricing (installments, mortgage, discount policy) | done |
| knowledge (ingestion + hybrid RAG) | next |
| inventory, orchestration, crm_copilot, interactions, coaching, escalation, call_timing | planned |

## Run locally

```bash
cp .env.example .env
docker compose up -d postgres redis
cd backend && uv sync && uv run uvicorn aios.entrypoints.api:app --reload
```

API docs: http://localhost:8000/docs

## Checks

```bash
cd backend && uv run ruff check . && uv run mypy && uv run pytest
```
