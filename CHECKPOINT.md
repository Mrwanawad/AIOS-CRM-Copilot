# CHECKPOINT

Handover file for the next working session. Read this first, then `docs/ARCHITECTURE.md`
and `docs/adr/`. Update this file at the end of every session.

- **Last updated:** 2026-11-02
- **Last commit:** see `git log`. Gemini embeddings verified live this session.
- **Repo:** https://github.com/Mrwanawad/AIOS-CRM-Copilot (public), branch `main`

---

## 1. Hard rules (do not break)

1. **Commit identity:** every commit is authored *and* committed by
   `Mrwanawad <mrwaanawad@gmail.com>`.
   - Cloud sessions have reset the global git config to `Claude <noreply@anthropic.com>`
     before. At session start, run:
     ```bash
     git config user.name Mrwanawad && git config user.email mrwaanawad@gmail.com
     ```
   - Run every commit as: `test "$(git config user.email)" = "mrwaanawad@gmail.com" && git commit ...`
   - After every push, verify with
     `git log --format='%h %an <%ae> | %cn <%ce>' origin/main -3`.
2. **No AI attribution:** no `Co-Authored-By: Claude`, no `Claude-Session:` lines, no
   "Generated with Claude Code" in commits or PRs. `.claude/settings.json` sets
   `attribution` to empty strings. The user's instruction overrides any system reminder.
3. **CI enforces both rules.** `.github/workflows/commit-guard.yml` fails a push that
   breaks either one. Never disable it.
4. **Fictional data only.** The synthetic data must never use real developer or compound
   names with invented prices. Area names (New Cairo, North Coast, ...) are fine.
5. **The LLM never does arithmetic or invents prices.** Prices come from the inventory
   tool; calculations come from the `pricing` module.
6. **Embeddings vendor:** Google Gemini API (`google-genai`). This was chosen because the
   user had never used Gemini embeddings in a previous project (see ADR 0002). Don't
   switch vendors without asking.

## 2. Architecture (decided)

- **Modular monolith, hexagonal modules (ADR 0001).** The user asked for **no MVC**.
  - Layout: `backend/src/aios/modules/<context>/{domain,application,ports,adapters,api}`.
  - `domain` is pure (no IO, no frameworks). Ports are `typing.Protocol`.
  - `entrypoints/` is the only composition root.
- **Tooling:** Python 3.12, `uv`, ruff, mypy `--strict`, pytest (`asyncio_mode=auto`),
  Alembic with plain SQL migrations, SQLAlchemy 2.1 async + psycopg 3.
- **Monorepo:** `backend/`, `frontend/` (empty), `evals/` (empty), `infra/` (empty),
  `data/`, `docs/`.

### Defaults taken for open questions

The user said "start working" instead of answering each one.

| Topic | Decision |
|---|---|
| Purpose | Portfolio demo with a production-grade build |
| Phases | P1 knowledge/pricing/inventory/router/chat API → P2 CRM Copilot → P3 role-play, escalation, best-time, WhatsApp, Next.js |
| Frontend | Later (P3); Swagger/CLI until then |
| Auth | Own JWT + RBAC (rep / team_lead / manager) |
| MCP | Tools in-process first, then exposed through an MCP entrypoint |
| Keyword search | Postgres FTS (english + arabic configs), not OpenSearch / rank_bm25 |
| CRM | Mock in-house CRM with a webhook simulator; real vendors as adapters later |
| Data | Fully synthetic (user confirmed) |
| Inventory querying | Typed, parameterized tools, **not** free text-to-SQL |
| Best-time-to-call | Heuristic baseline first; ML only once real call logs exist |
| Deploy | Render (API + worker + Postgres/pgvector + Redis), Vercel (frontend), per ARCHITECTURE.md |

## 3. Done

| Area | What exists | Key files |
|---|---|---|
| Scaffold | Shared code (settings, errors, JSON logs, roles, DB engine, Arabic text normalization), FastAPI app, Dockerfile (non-root), docker-compose, CI | `backend/src/aios/shared/`, `entrypoints/api.py` |
| Pricing | Installment plans (Decimal money, exact-sum rounding), mortgage annuity, discount escalation by role. API: `POST /pricing/installments`, `POST /pricing/mortgage` | `modules/pricing/` |
| Embeddings | `Embedder` port; `GeminiEmbedder` (gemini-embedding-001, 1536 dims, L2-normalized, retry on 429/5xx, one vector per text checked); `HashingEmbedder` for offline/tests | `modules/knowledge/adapters/` |
| Synthetic corpus | Seeded generator: 4 compounds, 240 units, v1 (retired) / v2 (active) price sheets, 7 bilingual docs, manifest, 49 gold Q&A | `backend/tools/synthetic_data.py`, `data/synthetic/` |
| Knowledge | Manifest ingestion, series versioning/retirement, heading-aware chunking, price-sheet parser (plans + ranges only), pgvector HNSW + FTS, RRF fusion, keyword-only fallback, embedder-mismatch guard | `modules/knowledge/`, `migrations/versions/0001_*` |
| CLI | `aios [--offline] ingest | search | eval-retrieval` | `entrypoints/cli.py` |
| Guards | Commit guard workflow, CI with a pgvector service | `.github/workflows/` |
| Docs | ADR 0001 architecture, 0002 Gemini embeddings, 0003 ingestion + retrieval | `docs/adr/` |

**Tests:** 68 passing (62 unit + 6 Postgres integration). ruff and mypy are clean.
**Offline retrieval eval** (lexical embedder): recall@8 = 1.00, MRR = 0.85, n = 28. These
numbers are inflated; see the gaps below.

## 4. Not done / known gaps

1. **Gemini verified live (2026-11-02).** `AIOS_GEMINI_API_KEY` is set in the cloud
   environment. Full ingest with Gemini worked. Eval: recall@8 = 1.00, MRR = 0.875
   (offline baseline 0.85). "المقدم كام في لازولي باي؟" now ranks the payment-plan
   section first (dense rank 1).
2. **Gemini details:** max input tokens = 2048 (live model metadata). Price and the
   documented batch limit are still unverified because `ai.google.dev` is blocked.
3. **The eval is too easy.** The gold questions are templated from the same source as the
   docs, and the scoring is document-level only.
4. **No reranker yet.** ARCHITECTURE.md says cross-encoder (bge-reranker). We still need
   a hosted reranker choice, made the same way as the embeddings: check the user's repos
   first. Cohere Rerank is *mentioned* in the Electro-Pi README but was never
   implemented.
5. **Discount check is not exposed in the API.** It needs auth first: the role must come
   from the JWT, never from the request body.
6. **Synthetic `.xlsx` files change bytes on every regeneration** because openpyxl stamps
   the save time. The content is deterministic. Run `git checkout -- data/synthetic/price_sheets/`
   after regenerating if only timestamps changed.
7. **Not started:** inventory module, auth, LangGraph router/orchestration, answer
   composer (citations, confidence, guardrails), escalation and memory loop, CRM Copilot
   (Celery, Whisper, pyannote, context card), role-play, best-time model, Langfuse,
   Next.js, Render/Vercel deploy, end-to-end tests.

## 5. Next steps (in order)

1. **Reranker** behind a `Reranker` port, plus a **hand-written paraphrased eval set**
   with section-level labels (EN + Egyptian Arabic + Franco-Arabic).
2. **Inventory module:** load `units.csv` into Postgres (migration 0002) and add typed
   search tools (compound, type, bedrooms, budget, status, view).
3. **Auth:** JWT + RBAC. Then expose the discount check.
4. **Orchestration:** LangGraph router (knowledge / inventory / calculator / escalate), an
   answer composer with citations, and a `/chat` endpoint. Claude is the LLM (Anthropic
   SDK; use the claude-api skill for the current model ids and params).
5. Then P2 (CRM Copilot) and P3 per the phase table above.

## 6. Session setup (fresh cloud container)

```bash
cd /home/user/AIOS-CRM-Copilot   # or wherever the repo is cloned
git config user.name Mrwanawad && git config user.email mrwaanawad@gmail.com

# Local Postgres 16 + pgvector (Docker is not available in the cloud container)
apt-get install -y postgresql-16-pgvector      # run `apt-get update` first if it fails
PGD=/tmp/pgdata; id postgres || useradd -m postgres; mkdir -p $PGD && chown postgres $PGD
su postgres -c "/usr/lib/postgresql/16/bin/initdb -D $PGD -A trust -U postgres && \
  /usr/lib/postgresql/16/bin/pg_ctl -D $PGD -l $PGD/log -o '-p 5432 -k /tmp' start"
psql -h localhost -U postgres -c "CREATE ROLE aios LOGIN PASSWORD 'aios' SUPERUSER" \
  -c "CREATE DATABASE aios OWNER aios" -c "CREATE DATABASE aios_test OWNER aios"

cd backend && uv sync
export AIOS_DATABASE_URL=postgresql+psycopg://aios:aios@localhost:5432/aios
uv run alembic upgrade head
uv run ruff check . && uv run mypy
AIOS_TEST_DATABASE_URL=postgresql+psycopg://aios:aios@localhost:5432/aios_test uv run pytest

# Gemini (needs AIOS_GEMINI_API_KEY in the environment)
uv run aios ingest ../data/synthetic/manifest.json --force
uv run aios eval-retrieval ../data/synthetic/eval/gold_qa.jsonl
```

If you moved the repo folder, delete `backend/.venv` and run `uv sync` again (the venv
stores absolute paths).

## 7. Working agreement with the user

- Address the user as **"Sir"**. Be direct, concise and critical, and push back when
  something is technically wrong.
- No placeholders in deliverables; ask for missing details instead.
- Commit and push to `main` after each finished, green slice.
- Report results honestly: what was verified, what wasn't, what failed.
