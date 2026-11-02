# ADR 0002: Hosted embeddings via Google Gemini API

- Status: Accepted
- Date: 2026-11-02

## Context

`ARCHITECTURE.md` named bge-m3 run locally. The production target (Render) has no GPU,
and running bge-m3 on CPU there is slow and memory-heavy, so we chose a hosted API.

Rule from the project owner: use an embedding vendor/model **not used in any previous
project**, chosen from the vendors listed in the owner's skills (resume and GitHub
profile README).

Embedding usage found across the owner's repositories (checked 2026-11-02):

| Vendor / model | Where |
|---|---|
| Cohere embed | RAG-System-Using-MongoDB, Real-Time-AI-Voice-Assistant |
| OpenAI embeddings | RAG-System-Using-MongoDB, Real-Time-AI-Voice-Assistant |
| OpenRouter → `nvidia/llama-nemotron-embed-vl-1b-v2` | Real-Time-AI-Voice-Assistant |
| fastembed `BAAI/bge-small-en-v1.5` (local) | JobRadar |
| sentence-transformers `all-MiniLM-L6-v2` (local) | Electro-Pi technical test |

Vendors in the skills list but never used for embeddings: **Gemini / Vertex AI**,
Anthropic (no embedding API), Grok, Ollama (local, ruled out).

## Decision

- Use the **Gemini API** through the official `google-genai` SDK.
- Default model is `gemini-embedding-001`, a stable text model. It is configurable via
  `AIOS_EMBEDDING_MODEL`, and the SDK also lists `gemini-embedding-2` (multimodal),
  which can be evaluated later for brochure and master plan images.
- Use 1536 dimensions (Matryoshka truncation). This stays under pgvector's 2000-dim
  HNSW limit for the `vector` type. Truncated vectors are L2-normalized client-side.
- Use asymmetric task types: `RETRIEVAL_DOCUMENT` for chunks, `RETRIEVAL_QUERY` for
  questions.
- Wrap the client behind the `Embedder` port. Changing vendors means writing a new
  adapter and re-embedding the corpus. The stored vectors are tagged with `model_id`
  so mixed-model indexes can be detected.

## Consequences

- No GPU and no model weights in the image. Cost is per token.
- Retrieval depends on Google's availability. Transient 429/5xx errors are retried
  with exponential backoff, and repeated failures surface as `ExternalServiceError` (502).
- First real measurement (2026-11-02, gold set, n = 28, k = 8): recall@8 = 1.00
  (EN 1.00, AR 1.00), MRR = 0.875, against 0.85 for the offline lexical embedder.
  The gold set is templated and too easy, so this only shows the integration works.
  A paraphrased, section-labelled set is still needed before the choice is final.
- Max input tokens: **2048**, read from the live `models/gemini-embedding-001`
  metadata. Chunks are capped at 1200 characters, so they fit with a wide margin.
- Batch size 100 worked against the live API. Still unverified (official docs are
  blocked from the build environment): the per-token price and the documented batch
  limit. The batch size stays configurable (`AIOS_EMBEDDING_BATCH_SIZE`).
