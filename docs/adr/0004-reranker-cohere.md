# ADR 0004: Reranking with Cohere Rerank

- Status: Accepted (not yet measured live; see below)
- Date: 2026-11-02

## Context

Hybrid retrieval (pgvector + FTS, fused with RRF) finds the right document, but not
the right section near the top. On the hand-written paraphrased set
(`evals/retrieval_paraphrased.jsonl`, 46 questions in English, Egyptian Arabic and
Franco-Arabic, labelled by section), with live Gemini embeddings and k = 8:

| Level | recall@8 | MRR |
|---|---|---|
| Document | 0.978 | 0.823 |
| Section | 0.957 | 0.646 |

At k = 3, section recall drops to 0.80. The answer composer only reads a few chunks,
so ranking inside the top 8 matters.

## Options

1. **Cohere Rerank (`rerank-v3.5`), hosted.** Multilingual cross-encoder, one HTTP call,
   paid per search. Needs a second vendor key.
2. **Self-hosted `bge-reranker-v2-m3`.** No vendor, but about 2 GB of weights and CPU
   latency in the API image. That breaks the "no model weights in the image" rule
   from ADR 0002 and the Render deploy plan.
3. **LLM-as-reranker (Gemini or Claude).** No new key, but slower, costlier per query,
   and less stable scores than a trained cross-encoder.

## Decision

Option 1, behind a `Reranker` port (`modules/knowledge/ports/reranker.py`) with a
`CohereReranker` adapter that calls `POST /v2/rerank` with plain `httpx` (no SDK).

- The retriever fuses `rerank_candidates` (default 30) chunks, sends them with their
  title and heading trail, and keeps the top k by relevance.
- Reranking is **optional**. With no `AIOS_COHERE_API_KEY`, or when Cohere fails after
  retries, the fused RRF order is returned. A reranker outage never fails an answer.
- 429/5xx and transport errors are retried with backoff; 4xx are not.

## Consequences

- One more vendor and key; cost grows with queries × candidates.
- Not yet measured: the build environment has no Cohere key and its network policy
  blocks `api.cohere.com`. Run `aios eval-retrieval ../evals/retrieval_paraphrased.jsonl
  --compare-rerank` once both are in place. Keep Cohere only if section MRR clearly
  improves; otherwise revisit option 3.
- The paraphrased set is written by hand by someone who read the docs; it is harder
  than the templated set but still not real user traffic.
