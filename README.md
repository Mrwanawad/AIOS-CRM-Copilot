<div align="center">

# AIOS CRM Copilot

**The foundation of an AI team lead for real estate sales reps: bilingual (English and Egyptian
Arabic) hybrid retrieval over versioned sales documents, and an exact `Decimal` pricing engine
the LLM must call instead of doing arithmetic.**

[![CI](https://github.com/Mrwanawad/AIOS-CRM-Copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/Mrwanawad/AIOS-CRM-Copilot/actions/workflows/ci.yml)
[![Commit guard](https://github.com/Mrwanawad/AIOS-CRM-Copilot/actions/workflows/commit-guard.yml/badge.svg)](https://github.com/Mrwanawad/AIOS-CRM-Copilot/actions/workflows/commit-guard.yml)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL%2016%20%2B%20pgvector-4169E1?logo=postgresql&logoColor=white)
![Gemini](https://img.shields.io/badge/Gemini%20embeddings-8E75B2?logo=googlegemini&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy%202%20async-D71F00)
![mypy](https://img.shields.io/badge/mypy-strict-2A6DB2)
![ruff](https://img.shields.io/badge/lint-ruff-D7FF64)
![Tests](https://img.shields.io/badge/tests-68%20passing-brightgreen)

</div>

<p align="center"><img src="docs/demo.gif" width="100%" alt="Swagger UI of the AIOS API: the installment-plan request is filled in, executed, and returns an exact 32-installment schedule whose total equals the net price to the cent"/></p>

---

## Contents

- [The problem](#the-problem)
- [What is built today](#what-is-built-today)
- [Architecture](#architecture)
- [Knowledge ingestion](#knowledge-ingestion)
- [Hybrid retrieval](#hybrid-retrieval)
- [Pricing engine](#pricing-engine)
- [Design rules that keep answers safe](#design-rules-that-keep-answers-safe)
- [Synthetic demo corpus](#synthetic-demo-corpus)
- [Evaluation](#evaluation)
- [Testing and CI gates](#testing-and-ci-gates)
- [Tech stack](#tech-stack)
- [Methodologies](#methodologies)
- [Run it locally](#run-it-locally)
- [Configuration](#configuration)
- [Project structure](#project-structure)
- [Decision records](#decision-records)
- [Roadmap](#roadmap)
- [Honest limits](#honest-limits)

## The problem

New reps at a real estate brokerage take 5 to 6 months to close their first deal. They are new
to the compounds, developers, payment plans and objections, so they keep interrupting the team
lead and dig through dozens of PDFs and Excel price sheets. When a lead is reassigned, the new
rep calls the client with no context.

**AIOS** is planned as one internal AI service for the whole sales floor:

- a **team-lead twin** that answers reps with citations from brochures, price sheets, policies
  and the team lead's playbook, in English or Egyptian Arabic;
- a **CRM Copilot** that shows a client context card before every call and writes a handover
  summary when a lead changes hands.

This repository is the first, production-grade slice of that system: the knowledge base and the
pricing engine every later agent depends on. The full target design is in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## What is built today

| Area | What exists | Where |
|---|---|---|
| **Pricing engine** | Developer installment plans (down payment, delivery payment, equal installments, cash discount), fixed-rate mortgage annuity, and discount approval routing by role. Exact `Decimal` money, half-up rounding, schedules that always sum to the cent. | `modules/pricing/` |
| **Pricing API** | `POST /pricing/installments`, `POST /pricing/mortgage`, strict Pydantic contracts (`extra="forbid"`, money as strings), domain errors mapped to 422 / 404 / 502. | `modules/pricing/api/` |
| **Embeddings** | `Embedder` port with a Gemini adapter (`gemini-embedding-001`, 1536-dim Matryoshka truncation, L2-normalized, asymmetric document/query task types, exponential backoff on 429/5xx, response-count check) and an offline `HashingEmbedder` for tests. | `modules/knowledge/adapters/` |
| **Ingestion** | Manifest-driven pipeline: parse, section-aware chunk, embed, store, retire superseded versions. Idempotent by content hash and embedding model. Markdown and `.xlsx` price-sheet parsers. | `modules/knowledge/application/ingest.py` |
| **Hybrid retrieval** | pgvector HNSW (cosine) + Postgres full-text search (`english` + `arabic` configs) fused with Reciprocal Rank Fusion. Falls back to keyword-only when the embedding API is down. | `modules/knowledge/application/retrieve.py` |
| **Arabic search** | Normalization of alef / ya / ta-marbuta variants, hamza carriers, diacritics, tatweel and Eastern Arabic digits, applied the same way at index and query time. | `shared/text.py` |
| **Retrieval eval** | recall@k, MRR and per-language recall over a bilingual gold set. | `modules/knowledge/application/evaluation.py` |
| **Synthetic corpus** | Seeded generator for 4 fictional compounds, 240 units, versioned price sheets, 7 bilingual documents and 49 gold Q&A items. | `backend/tools/synthetic_data.py`, `data/` |
| **Operator CLI** | `aios ingest`, `aios search`, `aios eval-retrieval`, each with `--offline`. | `entrypoints/cli.py` |
| **Delivery** | Multi-stage non-root Docker image, Docker Compose (Postgres + pgvector, Redis, API), GitHub Actions CI with a real pgvector service, commit-authorship guard. | `backend/Dockerfile`, `.github/workflows/` |

## Architecture

A **modular monolith** made of **hexagonal (ports and adapters)** modules, chosen over MVC so one
feature lives in one place and vendors stay at the edges ([ADR 0001](docs/adr/0001-modular-monolith-hexagonal.md)).

```mermaid
flowchart TB
    subgraph Entry["entrypoints/ (only composition root)"]
        API[FastAPI app]
        CLI[aios CLI]
    end

    subgraph Pricing["modules/pricing"]
        PAPI[api: router + schemas] --> PAPP[application: PricingService]
        PAPP --> PDOM[domain: Decimal money,<br/>installments, mortgage, discounts]
        PAPP --> PPORT[[port: DiscountLimits]]
        PADP[adapter: settings limits] -.implements.-> PPORT
    end

    subgraph Knowledge["modules/knowledge"]
        ING[application: IngestService] --> KDOM[domain: chunking, RRF fusion, models]
        RET[application: HybridRetriever] --> KDOM
        EVAL[application: retrieval eval] --> RET
        ING & RET --> EMB[[port: Embedder]]
        ING & RET --> REPO[[port: KnowledgeRepository]]
        ING --> PARSE[[port: DocumentParser]]
        GEM[Gemini adapter] -.-> EMB
        HASH[Hashing adapter, offline] -.-> EMB
        PG[pgvector + FTS adapter] -.-> REPO
        MD[Markdown parser] -.-> PARSE
        XL[Price-sheet parser] -.-> PARSE
    end

    API --> PAPI
    CLI --> ING & RET & EVAL
    PG --> DB[(PostgreSQL 16<br/>pgvector HNSW + GIN tsvector)]
    GEM --> GAPI{{Google Gemini API}}
```

**Rules every module follows**

- `domain/` is pure Python: no IO, no framework or vendor imports. Pricing and chunking logic are
  tested without a database or network.
- `ports/` are `typing.Protocol` interfaces. Swapping a vendor means writing one adapter.
- `application/` holds use cases that talk to the outside world only through ports.
- `entrypoints/` is the only place adapters are wired to ports (API, CLI, later the worker and
  MCP servers).
- Modules talk to each other only through `application` services, never through another
  module's tables or domain internals.

## Knowledge ingestion

Every file arrives with explicit metadata in a manifest. Nothing about version or status is
guessed from file content ([ADR 0003](docs/adr/0003-knowledge-ingestion-and-hybrid-retrieval.md)).

```mermaid
flowchart LR
    M[manifest.json<br/>source_id, series, version,<br/>effective_date, status, compound] --> L[Load + validate<br/>path traversal check]
    L --> S[Sort oldest first<br/>per series]
    S --> H{Same content hash<br/>and same embedder?}
    H -- yes --> U[Skip: unchanged]
    H -- no --> P[Parser by file type<br/>Markdown / xlsx]
    P --> C[Section-aware chunking<br/>1200 chars, 150 overlap,<br/>never across headings]
    C --> E[Embed with header<br/>title > heading path]
    C --> N[Arabic-normalized<br/>search copy]
    E & N --> W[(kb_documents + kb_chunks)]
    W --> R[Retire older versions<br/>in the same series]
```

- **Versioning by series.** `price_sheet:QMH` v2 (active) retires v1. A late-arriving older
  version is stored as retired. Search only ever sees `status = 'active'`.
- **Price sheets never leak exact prices.** The `.xlsx` parser turns a sheet into payment-plan
  sections and price *ranges* per unit type only. Exact unit prices will come from the inventory
  database, so a stale sheet can't put an old price into an answer.
- **Embedder consistency guard.** Each document stores the `embedding_model` that built it. The
  CLI refuses to search an index built by a different embedder.
- **Schema.** `kb_chunks.tsv` is a generated `tsvector` (English + Arabic) with a GIN index;
  `kb_chunks.embedding` is `vector(1536)` with an HNSW cosine index.

## Hybrid retrieval

Dense search finds paraphrases; keyword search finds exact unit codes and compound names. Both
run in parallel and are fused by rank, so their raw scores never need calibrating.

```mermaid
flowchart LR
    Q["Rep question<br/>e.g. المقدم كام في لازولي باي؟"] --> NQ[Arabic + case<br/>normalization]
    Q --> EQ[Gemini embed<br/>RETRIEVAL_QUERY]
    NQ --> KW[Postgres FTS<br/>OR of lexemes, top 40]
    EQ --> VS[pgvector HNSW<br/>cosine, top 40]
    EQ -. API down .-> FB[Keyword-only fallback]
    KW & VS --> RRF["RRF fusion, k = 60<br/>deterministic tie-break"]
    FB --> RRF
    RRF --> OUT[Top-k chunks with<br/>source, heading path,<br/>score and per-retriever ranks]
```

- Keyword search uses an OR of all lexemes because `websearch_to_tsquery` ANDs every word and
  misses natural questions.
- Each result carries the rank it got from each retriever, so a wrong answer can be traced to
  the retriever that caused it.

## Pricing engine

The LLM will never do arithmetic. Every number a rep sees about payments comes from this module.

| Function | What it guarantees |
|---|---|
| `calculate_installment_plan` | Discount applies to list price; down and delivery percentages apply to the net price; installments are equal and the last one absorbs rounding, so the schedule sums **exactly** to the net price. Monthly, quarterly, semi-annual or annual, up to 15 years. |
| `calculate_mortgage` | Standard fixed-rate annuity at 34-digit `Decimal` precision, 1 to 30 years, zero-rate case handled. Returns monthly payment, total paid and total interest. |
| `evaluate_discount` | Approves a discount within the caller's role limit; otherwise escalates to the **lowest** role whose limit covers it (a rep asking for 4% goes to the team lead, not the manager). Defaults: rep 2%, team lead 5%, manager 10%. |

Floats are never used for money. Inputs are validated as domain invariants (percentages 0 to 100,
down + delivery ≤ 100%, a 0-year plan must be fully covered), and the HTTP layer adds strict
bounds on top.

```bash
curl -s localhost:8000/pricing/installments -H 'Content-Type: application/json' -d '{
  "list_price": "4500000", "down_payment_pct": "10", "years": 8,
  "frequency": "quarterly", "delivery_payment_pct": "5", "discount_pct": "0"}'
```

The discount check is implemented and tested but not exposed over HTTP yet: the approver role
must come from an authenticated token, never from a request body, so it waits for the auth module.

## Design rules that keep answers safe

- **No invented prices.** Exact prices come from the inventory database; calculations come from
  the pricing module; price sheets only contribute plans and ranges to retrieval.
- **No stale documents.** Superseded versions are retired at ingestion and filtered out of search.
- **No mixed vector spaces.** An index built by one embedder can't be queried with another.
- **Degrade, don't fail.** An embedding outage drops retrieval to keyword-only instead of
  breaking the answer.
- **Secrets stay secret.** API keys are `SecretStr` in typed settings, so they never print in logs.
- **Fictional data only.** No real developer or compound is paired with invented prices.
- **Roles are an ordered type** (`rep < team_lead < manager`) shared by every module, so discount
  escalation and future access control use one definition.

## Synthetic demo corpus

Generated by `backend/tools/synthetic_data.py` with seed 42, byte-for-byte reproducible in content.

| Item | Contents |
|---|---|
| Compounds | Qamar Heights (QMH), Lazuli Bay (LZB), Sidra Groves (SDG), Lotus Capital Residence (LTC), with developers, unit types, amenities and payment plans in English and Arabic |
| Inventory | 240 units with status and v1 / v2 prices (`data/synthetic/inventory/units.csv`) |
| Price sheets | 8 `.xlsx` files: v1 retired (June 2026) and v2 active (October 2026, +8%) per compound |
| Documents | 4 brochures, FAQ, sales policies and a team-lead playbook, bilingual Markdown |
| Gold set | 49 Q&A items (35 English, 14 Egyptian Arabic) across payment plans, unit prices, fees, policy, delivery, inventory search, calculations, playbook and out-of-scope; 20 are flagged as tool-backed |

Area names (New Cairo, North Coast, ...) are real places used only for realism; every developer,
compound, unit, price and policy is invented.

## Evaluation

```bash
uv run aios eval-retrieval ../data/synthetic/eval/gold_qa.jsonl     # recall@k, MRR, recall per language
```

The retrieval eval keeps only the 28 gold questions answerable from documents (tool-backed and
out-of-scope items are excluded) and counts a hit when any expected source document is in the
top k.

| Run | Embedder | n | recall@8 | MRR |
|---|---|---|---|---|
| Offline baseline | `HashingEmbedder` (lexical, not semantic) | 28 | 1.00 | 0.85 |

These numbers are an **upper bound**, not a quality claim: the gold questions are templated from
the same source as the documents and scoring is document-level. Known weak spot: for
"المقدم كام في لازولي باي؟" the overview section outranks the payment-plan section. A
paraphrased, section-labelled eval set and a reranker are the next step (see [Roadmap](#roadmap)).

## Testing and CI gates

**68 tests**: 57 unit tests (pricing math and invariants, chunking, parsers, RRF, Arabic
normalization, Gemini adapter retries and normalization, synthetic-data consistency) and 11
integration tests against real PostgreSQL 16 + pgvector and the HTTP API: idempotent ingestion,
new versions retiring old ones (and late old versions staying retired), retired price sheets
never retrieved, exact plan codes found by keyword search, compound filters, a retrieval-quality
floor on the gold set, exact money strings and 422 mapping in the API.

| Gate | What it checks |
|---|---|
| `ruff check` + `ruff format --check` | Lint rules E, W, F, I, B, UP, N, SIM, RUF, PT, ANN, S (bandit), DTZ (timezone-aware datetimes) |
| `mypy --strict` | Full static typing with the Pydantic plugin, over `src/` and `tools/` |
| `pytest --cov` | Unit + integration tests, with a `pgvector/pgvector:pg16` service container in CI |
| Docker build | The production image builds after the backend job passes |
| **Commit guard** | Every pushed commit must be authored and committed by the repo owner and carry no AI attribution trailers |

## Tech stack

| Layer | In use now |
|---|---|
| **Backend** | Python 3.12, FastAPI, Pydantic v2, pydantic-settings, Uvicorn |
| **Data** | PostgreSQL 16, pgvector (HNSW, cosine), Postgres full-text search (`english` + `arabic`), SQLAlchemy 2 async, psycopg 3, Alembic |
| **Embeddings** | Google Gemini API via `google-genai` (`gemini-embedding-001`, 1536 dims), offline hashing embedder |
| **Retrieval** | Hybrid dense + keyword, Reciprocal Rank Fusion (Cormack et al., 2009) |
| **Documents** | openpyxl (price sheets), Markdown section parser |
| **Arabic** | Custom normalizer (letter variants, diacritics, tatweel, Eastern Arabic digits) |
| **Quality** | pytest, pytest-asyncio, pytest-cov, ruff, mypy strict |
| **Delivery** | uv, Docker (multi-stage, non-root), Docker Compose, GitHub Actions |

| Planned layer (from the target design) | Tools |
|---|---|
| LLM and agents | Claude via the Anthropic SDK, LangGraph router and answer composer, MCP servers |
| Reranking | Cross-encoder reranker behind a `Reranker` port |
| CRM Copilot | CRM webhooks, Celery + Redis, Whisper, pyannote.audio, structured summaries |
| Best time to call | Heuristic baseline, then LightGBM and lifelines once real call logs exist |
| Observability | Langfuse traces, cost per answer |
| Frontend and deploy | Next.js on Vercel, API + worker + Postgres + Redis on Render |

**Deliberately not used:** LLM fine-tuning (knowledge changes daily; RAG stays fresh and
auditable), LLM arithmetic (the pricing module does it), free-text text-to-SQL for inventory
(typed, parameterized tools instead), pure vector search (unit codes and compound names need
keyword search), MVC (spreads one feature across the tree), and a separate search engine such as
OpenSearch (Postgres FTS covers it at this scale).

## Methodologies

- **Hexagonal architecture** inside a **modular monolith**, organized by bounded context
  (domain-driven design).
- **Agentic RAG foundation with citation-first retrieval**: every chunk keeps its source,
  version and heading path.
- **Hybrid retrieval with rank fusion** instead of score blending.
- **Deterministic tools over model output**: money math and discount rules are plain, tested code.
- **Document lifecycle management**: manifest-driven, versioned, idempotent ingestion.
- **Graceful degradation** for external dependencies.
- **Evaluation-driven development**: a gold set and retrieval metrics exist before any LLM is
  wired in, and their limits are stated next to the numbers.
- **Architecture Decision Records** for every major choice.
- **Reproducible synthetic data** with a fixed seed, so tests and evals are stable.
- **Privacy by design** in the target system: consent checks, PII minimization and Egypt PDPL
  (Law 151 of 2020) retention rules.

## Run it locally

Needs Python 3.12, [uv](https://docs.astral.sh/uv/) and Docker (for Postgres).

```bash
cp .env.example .env                       # set AIOS_GEMINI_API_KEY
docker compose up -d postgres redis
cd backend && uv sync
uv run alembic upgrade head

uv run aios ingest ../data/synthetic/manifest.json
uv run aios search "المقدم كام في لازولي باي؟"
uv run aios eval-retrieval ../data/synthetic/eval/gold_qa.jsonl

uv run uvicorn aios.entrypoints.api:app --reload     # http://localhost:8000/docs
```

No API key? Add `--offline` to the `aios` commands to use the lexical `HashingEmbedder`. It is
not semantic, and an index built with it can't be mixed with a Gemini one: re-ingest with
`--force` when switching.

Run the whole stack in containers with `docker compose up --build` (API on port 8000).

**Checks**

```bash
cd backend
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run pytest tests/unit                                   # no database needed
AIOS_TEST_DATABASE_URL=postgresql+psycopg://aios:aios@localhost:5432/aios_test uv run pytest
```

Regenerate the demo corpus: `uv run python tools/synthetic_data.py --out ../data/synthetic --seed 42`.

## Configuration

All settings are environment variables with the `AIOS_` prefix (`backend/src/aios/shared/config.py`).

| Variable | Default | Purpose |
|---|---|---|
| `AIOS_DATABASE_URL` | `postgresql+psycopg://aios:aios@localhost:5432/aios` | Postgres with pgvector |
| `AIOS_GEMINI_API_KEY` | unset | Gemini embeddings (or use `--offline`) |
| `AIOS_EMBEDDING_MODEL` | `gemini-embedding-001` | Embedding model id, stored with every document |
| `AIOS_EMBEDDING_DIM` | `1536` | Must match the migration's `vector(1536)` |
| `AIOS_EMBEDDING_BATCH_SIZE` | `100` | Texts per embedding request |
| `AIOS_DISCOUNT_LIMITS_PCT__<ROLE>` | rep 2, team_lead 5, manager 10 | Discount limit per role |
| `AIOS_ANTHROPIC_API_KEY`, `AIOS_LLM_MODEL` | unset, `claude-opus-5-5` | Reserved for the orchestration layer |
| `AIOS_REDIS_URL` | `redis://localhost:6379/0` | Reserved for the background worker |
| `AIOS_ENV`, `AIOS_LOG_LEVEL` | `local`, `INFO` | Environment and JSON log level |

## Project structure

```
backend/
  src/aios/
    shared/            settings, errors, JSON logs, roles, async DB engine, Arabic normalization
    modules/
      pricing/         domain (Decimal money, plans, mortgage, discounts), service, API, limits adapter
      knowledge/       domain (chunking, RRF), ingest + retrieve + eval use cases,
                       Gemini / hashing embedders, Markdown + xlsx parsers, pgvector repository
    orchestration/     LangGraph router and answer composer (next phase)
    entrypoints/       FastAPI app and operator CLI (composition roots)
  migrations/          Alembic, plain SQL (pgvector, HNSW, generated tsvector)
  tests/unit/          pure domain, parser and adapter tests
  tests/integration/   real Postgres + pgvector and HTTP API tests
  tools/               seeded synthetic data generator
data/synthetic/        fictional compounds, inventory, price sheets, documents, gold Q&A
docs/                  target architecture and decision records
frontend/, evals/, infra/   reserved for later phases
```

## Decision records

| ADR | Decision |
|---|---|
| [0001](docs/adr/0001-modular-monolith-hexagonal.md) | Modular monolith with hexagonal modules, not MVC |
| [0002](docs/adr/0002-embeddings-gemini.md) | Hosted Gemini embeddings at 1536 dims instead of local bge-m3 on a GPU-less host |
| [0003](docs/adr/0003-knowledge-ingestion-and-hybrid-retrieval.md) | Manifest-driven versioned ingestion, price-sheet safety, hybrid retrieval with RRF |

## Roadmap

1. Live Gemini ingestion and eval against the offline baseline.
2. Reranker behind a `Reranker` port, plus a hand-written paraphrased eval set with section-level
   labels (English, Egyptian Arabic, Franco-Arabic).
3. Inventory module: units in Postgres with typed, parameterized search tools.
4. Auth: JWT and role-based access (rep, team lead, manager), then the discount endpoint.
5. Orchestration: LangGraph router (knowledge, inventory, calculator, escalate), answer composer
   with citations, `/chat` endpoint on Claude.
6. CRM Copilot: webhooks, call transcription, context cards, handover summaries.
7. Role-play coaching, escalation and memory loop, best-time-to-call, Next.js UI, deployment.

## Honest limits

- No LLM is wired in yet; this is the retrieval and pricing foundation.
- Retrieval metrics come from the offline lexical embedder on a templated gold set, so they
  overstate quality. Gemini retrieval quality on Arabic is not yet measured.
- Evaluation is document-level; chunk ranking inside the right document is still weak.
- HNSW filters apply after the approximate search, which is fine at this scale; larger corpora
  need pgvector iterative scans or partial indexes.
- Regenerating the synthetic price sheets changes the `.xlsx` bytes (openpyxl stamps the save
  time) even though the content is identical.

---

Built by **Mrwan Awad**, AI & LLMs Engineer.
