# ADR 0003: Knowledge ingestion and hybrid retrieval

- Status: Accepted
- Date: 2026-11-02

## Decisions

1. **Manifest-driven ingestion.** Every file arrives with explicit metadata (source id,
   series, type, version, effective date, status, compound). Nothing about status or
   version is inferred from file content.
2. **Versioning by series.** Documents that supersede each other share a `series`
   (e.g. `price_sheet:QMH`). Ingesting a newer active version retires older ones. An
   older version that arrives late is stored as retired. Search only ever sees
   `status = 'active'`.
3. **Price sheets are not a price source for retrieval.** Only payment plans and price
   *ranges* per unit type are chunked. Exact unit prices come from the inventory tool,
   so a stale sheet cannot leak a price through RAG.
4. **Section-aware chunking.** Text is never merged across headings. Each chunk is
   embedded with a contextual header (`title > heading`).
5. **Hybrid retrieval with RRF.**
   - Dense: pgvector HNSW, cosine distance.
   - Keyword: Postgres FTS with `english` + `arabic` configs, queried as an OR of all
     lexemes (`websearch_to_tsquery` ANDs every word and misses natural questions).
   - The two lists are fused with Reciprocal Rank Fusion (k=60), so the raw scores
     never need calibrating.
6. **Arabic normalization in Python** (alef/ya/ta-marbuta variants, diacritics, tatweel,
   Eastern Arabic digits), applied the same way at index and query time.
   camel-tools is not used yet; the measured gap will decide.
7. **Graceful degradation.** If the embedding API fails, retrieval falls back to
   keyword-only instead of failing the answer.
8. **Embedder consistency guard.** Each document stores `embedding_model`. Search
   refuses to run if the index was built with a different embedder.

## Known gaps

- The gold set is generated from the same templates as the documents, so lexical
  overlap is high. Current numbers (offline lexical embedder: recall@8 = 1.00,
  MRR = 0.85) are an upper bound. A hand-written, paraphrased eval set is needed.
- Evaluation is document-level. Chunk ranking inside the right document is weak
  (e.g. the overview outranks the payment-plan section). A reranker stage and
  section-level gold labels are next.
- With HNSW, filters are applied after the approximate search. That is fine at the
  current scale. Larger corpora need pgvector >= 0.8 iterative scans or partial indexes.
