"""Operator CLI: ingest a corpus, run a search, run the retrieval eval.

    uv run aios ingest ../data/synthetic/manifest.json
    uv run aios search "المقدم كام في قمر هايتس؟"
    uv run aios eval-retrieval ../data/synthetic/eval/gold_qa.jsonl
    uv run aios eval-retrieval ../evals/retrieval_paraphrased.jsonl --compare-rerank

``--offline`` swaps Gemini for the lexical HashingEmbedder (no API key, not semantic).
Reranking (Cohere) runs when ``AIOS_COHERE_API_KEY`` is set; ``--no-rerank`` turns it off.
Vectors from different embedders must never be mixed in one database: re-ingest with
``--force`` when switching.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx
from google import genai

from aios.modules.knowledge.adapters.cohere_reranker import CohereReranker
from aios.modules.knowledge.adapters.gemini_embedder import GeminiEmbedder
from aios.modules.knowledge.adapters.hashing_embedder import HashingEmbedder
from aios.modules.knowledge.adapters.markdown_parser import MarkdownParser
from aios.modules.knowledge.adapters.pg_repository import PgKnowledgeRepository
from aios.modules.knowledge.adapters.price_sheet_parser import PriceSheetParser
from aios.modules.knowledge.application.evaluation import evaluate_retrieval, load_retrieval_gold
from aios.modules.knowledge.application.ingest import IngestService
from aios.modules.knowledge.application.retrieve import HybridRetriever
from aios.modules.knowledge.ports.embedder import Embedder
from aios.modules.knowledge.ports.repository import KnowledgeRepository
from aios.modules.knowledge.ports.reranker import Reranker
from aios.shared.config import Settings, get_settings
from aios.shared.db import create_engine
from aios.shared.logs import configure_logging


def build_embedder(settings: Settings, *, offline: bool) -> Embedder:
    if offline:
        return HashingEmbedder(settings.embedding_dim)
    if settings.gemini_api_key is None:
        sys.exit("AIOS_GEMINI_API_KEY is not set (use --offline for the lexical embedder)")
    client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())
    return GeminiEmbedder(
        client,
        model_id=settings.embedding_model,
        dimension=settings.embedding_dim,
        batch_size=settings.embedding_batch_size,
    )


def build_reranker(settings: Settings, http: httpx.AsyncClient) -> Reranker | None:
    if settings.cohere_api_key is None:
        return None
    return CohereReranker(
        http, api_key=settings.cohere_api_key.get_secret_value(), model_id=settings.rerank_model
    )


def build_retriever(
    settings: Settings,
    repo: KnowledgeRepository,
    embedder: Embedder,
    reranker: Reranker | None,
) -> HybridRetriever:
    return HybridRetriever(
        repo, embedder, reranker=reranker, rerank_candidates=settings.rerank_candidates
    )


async def _run(args: argparse.Namespace) -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    http = httpx.AsyncClient(timeout=settings.rerank_timeout_s)
    try:
        repo = PgKnowledgeRepository(engine, dimension=settings.embedding_dim)
        embedder = build_embedder(settings, offline=args.offline)
        if args.command != "ingest":
            models = await repo.active_embedding_models()
            if models and models != {embedder.model_id}:
                sys.exit(
                    f"index was built with {sorted(models)}, query embedder is "
                    f"{embedder.model_id!r}; re-ingest with --force or switch embedder"
                )
        reranker = None if args.no_rerank else build_reranker(settings, http)
        if args.command == "ingest":
            service = IngestService(repo, embedder, [MarkdownParser(), PriceSheetParser()])
            for r in await service.ingest_manifest(Path(args.manifest), force=args.force):
                print(
                    f"{r.outcome:<9} {r.source_id}@{r.version} "
                    f"chunks={r.chunks} retired={r.retired}"
                )
        elif args.command == "search":
            retriever = build_retriever(settings, repo, embedder, reranker)
            for i, c in enumerate(await retriever.search(args.query, k=args.k), 1):
                trail = " > ".join(c.heading_path)
                print(f"{i}. [{c.source_id}] {trail}  score={c.score:.4f} ranks={c.ranks}")
                print("   " + c.text[:200].replace("\n", " "))
        elif args.command == "eval-retrieval":
            gold = load_retrieval_gold(Path(args.gold))
            runs: dict[str, Reranker | None] = {"rerank" if reranker else "fused": reranker}
            if args.compare_rerank:
                if reranker is None:
                    sys.exit("--compare-rerank needs AIOS_COHERE_API_KEY")
                runs = {"fused": None, "rerank": reranker}
            out = {}
            for name, rr in runs.items():
                retriever = build_retriever(settings, repo, embedder, rr)
                out[name] = (await evaluate_retrieval(retriever, gold, k=args.k)).as_dict()
            print(json.dumps(out, indent=2, ensure_ascii=False))
    finally:
        await http.aclose()
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="aios")
    parser.add_argument("--offline", action="store_true", help="use the lexical test embedder")
    parser.add_argument("--no-rerank", action="store_true", help="skip the reranker")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("ingest")
    p.add_argument("manifest")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("-k", type=int, default=5)
    p = sub.add_parser("eval-retrieval")
    p.add_argument("gold")
    p.add_argument("-k", type=int, default=8)
    p.add_argument(
        "--compare-rerank", action="store_true", help="report fused and reranked side by side"
    )
    args = parser.parse_args()
    configure_logging(get_settings().log_level)
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
