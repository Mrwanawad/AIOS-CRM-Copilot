# AIOS-CRM-Copilot

An internal AI service for real estate sales teams:

- **Team-lead twin:** grounded answers on projects, units, prices and policies, with citations.
- **CRM Copilot:** a client context card shown before every call, plus handover summaries when a lead is reassigned.

Full design: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Decisions: [`docs/adr/`](docs/adr/).

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
| knowledge: Gemini embedder adapter | done |
| synthetic corpus + gold Q&A set | done |
| knowledge: ingestion (manifest, versioning) + hybrid retrieval (pgvector + FTS, RRF) | done |
| knowledge: reranker + paraphrased eval set | next |
| inventory, orchestration, crm_copilot, interactions, coaching, escalation, call_timing | planned |

## Run locally

```bash
cp .env.example .env            # set AIOS_GEMINI_API_KEY
docker compose up -d postgres redis
cd backend && uv sync
uv run alembic upgrade head
uv run aios ingest ../data/synthetic/manifest.json
uv run aios search "المقدم كام في لازولي باي؟"
uv run aios eval-retrieval ../data/synthetic/eval/gold_qa.jsonl
uv run uvicorn aios.entrypoints.api:app --reload
```

No API key? Add `--offline` to the `aios` commands to use the lexical test embedder
(not semantic, and its index can't be mixed with a Gemini one).

API docs: http://localhost:8000/docs

## Checks

```bash
cd backend && uv run ruff check . && uv run mypy && uv run pytest
# DB integration tests (Postgres + pgvector):
AIOS_TEST_DATABASE_URL=postgresql+psycopg://aios:aios@localhost:5432/aios_test uv run pytest
```
