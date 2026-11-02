# AI OS — Sales Team-Lead Clone + CRM Copilot — Architecture

## Scenario
New sales reps in a real estate brokerage take 5–6 months to close their first deal. They are new to the compounds, developers, payment plans, and objection handling, so they keep interrupting the team lead and dig through dozens of Excel sheets and PDFs. AI OS is one internal AI service for 100% of the sales team: a 24/7 "team-lead twin" that knows every project, unit, price, policy, and the team lead's playbook. When a new project launches, its documents are ingested once and every rep can sell it the same day.

CRM Copilot module: when a client is reassigned between follow-ups, the new rep has no context. Before the rep clicks "Call", the CRM shows a client context card built from every past call, message, and meeting.

## Input
- Rep question (text or voice), from web UI, WhatsApp, or CRM sidebar.
- Knowledge: developer brochures, price sheets, payment plans, master plans, FAQs, policies, team-lead playbook.
- Live inventory database (units, prices, availability).
- CRM: lead records, stage, notes, site visits, assignments.
- Interactions: call recordings, WhatsApp/email threads, meeting notes, call logs (answered/missed timestamps).

## Output
- Grounded answer with citations (unit IDs, document pages), confidence score.
- Recommended units, installment/mortgage calculations, next best action.
- Role-play session with scoring (onboarding mode).
- Escalation ticket to team lead with summarized context.
- Client context card (JSON → CRM sidebar / dialer pop-up): profile, interaction timeline, stated needs, closing drivers, open concerns with suggested answers, promises made, best time to call, top matched units, talking points.
- Handover summary on reassignment; post-call summary + auto-updated CRM fields + scheduled follow-up.

## Architecture

```
 Channels: Web UI | WhatsApp | CRM sidebar / dialer
        |
        v
 [API Gateway - FastAPI]  auth, role-based access (rep / team lead / manager)
        |
        v
 [Router agent - LangGraph]
   intent: knowledge | lead coaching | calculation | role-play | context card | escalate
        |
        +--> [Knowledge RAG]     hybrid retrieval (pgvector + BM25) -> cross-encoder rerank
        +--> [Inventory tool]    guarded text-to-SQL over live units
        +--> [CRM tool]          lead history, stage, notes, assignments (MCP server)
        +--> [Calculator tool]   installments, mortgage, discount limits (deterministic Python)
        +--> [Role-play agent]   buyer personas + scoring rubric
        +--> [Context builder]   transcripts + threads + notes -> structured client card
        +--> [Best-time model]   LightGBM / survival on answered vs. missed calls
        +--> [Escalation tool]   ticket + summary to team lead
        |
        v
 [Answer composer]  citations, confidence, guardrails (no invented prices/policies)
        |
        v
 [Memory loop]  team-lead answers to escalations -> reviewed -> knowledge base

 Ingestion pipeline (new project onboarding):
   PDFs / Excel / images -> Docling parse -> pandera validation -> chunk + embed (bge-m3)
   -> version tag (old price sheets retired) -> link to inventory rows

 Interaction pipeline (CRM Copilot):
   CRM webhook (lead opened / reassigned / call ended) -> Celery queue
   -> Whisper transcription + pyannote diarization -> LLM structured summary (Pydantic)
   -> context card + handover summary -> CRM widget; post-call CRM field update

 Observability: Langfuse traces, eval dashboard, cost per answer
```

## Tools Used
- LLM & agents: Claude (tool use, structured output), LangGraph, MCP servers (CRM, inventory, docs)
- Retrieval: PostgreSQL + pgvector, BM25 (rank_bm25 or OpenSearch), bge-m3 embeddings, cross-encoder reranker (bge-reranker)
- Arabic: camel-tools normalization
- Documents: Docling / Unstructured, pandas, openpyxl, pandera
- Speech: Whisper large-v3 (or API), pyannote.audio
- ML: LightGBM, lifelines (best-time-to-call)
- Backend: FastAPI, Pydantic, Celery + Redis, PostgreSQL
- Integrations: CRM APIs/webhooks (Salesforce / HubSpot / Zoho / in-house), Twilio or local cloud telephony, WhatsApp Business API
- Frontend: Next.js (chat + CRM widget mock)
- Evaluation & observability: Ragas, custom gold Q&A set, LLM-as-judge, Langfuse
- DevOps: Docker, GitHub Actions, pytest, ruff

## Tools Not Used (and why)
- Fine-tuning an LLM on company data: knowledge changes daily; RAG + tools stay fresh and auditable.
- LLM arithmetic: all prices/installments come from the calculator tool.
- Unrestricted text-to-SQL: schema-limited, read-only queries only.
- External profiling of clients (social scraping): only data the client shared with the company.
- Pure vector search: Arabic/English unit codes and compound names need BM25 too.

## Methodologies
- Agentic RAG with tool routing; citation-first answers.
- Human-in-the-loop escalation and knowledge approval.
- Offline eval set (gold Q&A graded by team leads) gating every release.
- Role-based access control; PII minimization; Egypt PDPL (Law 151/2020) consent and retention; call-recording consent.

## Evaluation Metrics
- Answer accuracy on gold Q&A, citation faithfulness, hallucination rate.
- Retrieval: recall@k, MRR, NDCG@10.
- Context card: summary faithfulness (human-graded), field completeness.
- Best-time model: answer-rate uplift at predicted times vs. random.
- Ops: p95 latency, cost per answer, escalation rate.
- Business: time-to-first-close for new reps, team-lead interruptions per rep per week, reassigned-lead conversion, rep prep time before calls.

## Production Monitoring
- Langfuse traces: latency, token cost, tool errors.
- Unanswered / low-confidence question log → knowledge gaps.
- Stale-document detector (price sheets older than active version).
- Thumbs up/down feedback, escalation trends, drift in question topics.

## Deployment Plan
- Backend: Render (Docker web service + worker + managed Postgres with pgvector, Redis).
- Frontend: Vercel (Next.js chat UI + CRM sidebar demo).
- CI/CD: GitHub Actions (tests, eval gate, deploy on main).
- Demo data: sample compounds, units, synthetic leads and conversations clearly marked synthetic.
