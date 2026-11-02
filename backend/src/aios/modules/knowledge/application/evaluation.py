"""Offline retrieval evaluation against the gold Q&A set (recall@k, MRR)."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from aios.modules.knowledge.application.retrieve import HybridRetriever


@dataclass(frozen=True, slots=True)
class GoldQuestion:
    id: str
    language: str
    category: str
    question: str
    expected_sources: tuple[str, ...]


@dataclass(slots=True)
class RetrievalReport:
    k: int
    total: int = 0
    hits: int = 0
    reciprocal_rank_sum: float = 0.0
    by_language: dict[str, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))
    misses: list[str] = field(default_factory=list)

    @property
    def recall_at_k(self) -> float:
        return self.hits / self.total if self.total else 0.0

    @property
    def mrr(self) -> float:
        return self.reciprocal_rank_sum / self.total if self.total else 0.0

    def language_recall(self, lang: str) -> float:
        hits, total = self.by_language[lang]
        return hits / total if total else 0.0


def load_retrieval_gold(path: Path) -> list[GoldQuestion]:
    """Keep only items answerable from documents (tool-backed and out-of-scope excluded)."""
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = json.loads(line)
        docs = tuple(s for s in raw["expected_sources"] if s.startswith("doc:"))
        if raw.get("requires_tool") or not docs:
            continue
        items.append(
            GoldQuestion(raw["id"], raw["language"], raw["category"], raw["question"], docs)
        )
    return items


async def evaluate_retrieval(
    retriever: HybridRetriever, gold: list[GoldQuestion], *, k: int = 8
) -> RetrievalReport:
    """A hit is any expected source document among the top-k chunks."""
    report = RetrievalReport(k=k)
    for item in gold:
        results = await retriever.search(item.question, k=k)
        rank = next(
            (i for i, r in enumerate(results, 1) if r.source_id in item.expected_sources), None
        )
        report.total += 1
        report.by_language[item.language][1] += 1
        if rank is None:
            report.misses.append(item.id)
            continue
        report.hits += 1
        report.reciprocal_rank_sum += 1 / rank
        report.by_language[item.language][0] += 1
    return report
