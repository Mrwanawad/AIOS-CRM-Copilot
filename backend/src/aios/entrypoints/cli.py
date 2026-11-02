"""Operator CLI: ingest a corpus, run a search, run the retrieval eval.

    uv run aios ingest ../data/synthetic/manifest.json
    uv run aios search "المقدم كام في قمر هايتس؟"
    uv run aios eval-retrieval ../data/synthetic/eval/gold_qa.jsonl

``--offline`` swaps Gemini for the lexical HashingEmbedder (no API key, not semantic).
Vectors from different embedders must never be mixed in one database: re-ingest with
``--force`` when switching.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from google import genai

from aios.modules.knowledge.adapters.gemini_embedder import GeminiEmbedder
from aios.modules.knowledge.adapters.hashing_embedder import HashingEmbedder
from aios.modules.knowledge.adapters.markdown_parser import MarkdownParser
from aios.modules.knowledge.adapters.pg_repository import PgKnowledgeRepository
from aios.modules.knowledge.adapters.price_sheet_parser import PriceSheetParser
from aios.modules.knowledge.application.evaluation import evaluate_retrieval, load_retrieval_gold
from aios.modules.knowledge.application.ingest import IngestService
from aios.modules.knowledge.application.retrieve import HybridRetriever
from aios.modules.knowledge.ports.embedder import Embedder
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


async def _run(args: argparse.Namespace) -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
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
        if args.command == "ingest":
            service = IngestService(repo, embedder, [MarkdownParser(), PriceSheetParser()])
            for r in await service.ingest_manifest(Path(args.manifest), force=args.force):
                print(
                    f"{r.outcome:<9} {r.source_id}@{r.version} "
                    f"chunks={r.chunks} retired={r.retired}"
                )
        elif args.command == "search":
            retriever = HybridRetriever(repo, embedder)
            for i, c in enumerate(await retriever.search(args.query, k=args.k), 1):
                trail = " > ".join(c.heading_path)
                print(f"{i}. [{c.source_id}] {trail}  score={c.score:.4f} ranks={c.ranks}")
                print("   " + c.text[:200].replace("\n", " "))
        elif args.command == "eval-retrieval":
            gold = load_retrieval_gold(Path(args.gold))
            report = await evaluate_retrieval(HybridRetriever(repo, embedder), gold, k=args.k)
            print(
                json.dumps(
                    {
                        "k": report.k,
                        "n": report.total,
                        "recall_at_k": round(report.recall_at_k, 3),
                        "mrr": round(report.mrr, 3),
                        "recall_en": round(report.language_recall("en"), 3),
                        "recall_ar": round(report.language_recall("ar"), 3),
                        "misses": report.misses,
                    },
                    indent=2,
                )
            )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="aios")
    parser.add_argument("--offline", action="store_true", help="use the lexical test embedder")
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
    args = parser.parse_args()
    configure_logging(get_settings().log_level)
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
