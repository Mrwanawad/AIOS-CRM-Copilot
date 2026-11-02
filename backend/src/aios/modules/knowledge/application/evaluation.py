"""Offline retrieval evaluation: recall@k and MRR at document and section level.

Two gold formats are accepted, one JSON object per line:

- generated set (``data/synthetic/eval/gold_qa.jsonl``): ``expected_sources`` only,
  so it is scored at document level;
- hand-written set (``evals/retrieval_paraphrased.jsonl``): ``relevant`` is a list of
  ``{"source": ..., "section": ...}`` where ``section`` is the chunk's last heading.
  It is scored at both levels. Section level is the one that matters for answers:
  the right document with the wrong section still gives the LLM the wrong text.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from aios.modules.knowledge.application.retrieve import HybridRetriever
from aios.modules.knowledge.domain.models import RetrievedChunk

Section = tuple[str, str]  # (source_id, last heading)


@dataclass(frozen=True, slots=True)
class GoldQuestion:
    id: str
    language: str
    category: str
    question: str
    expected_sources: tuple[str, ...]
    expected_sections: tuple[Section, ...] = ()


@dataclass(slots=True)
class Metric:
    """Recall@k and MRR for one matching rule, overall and per language."""

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

    def record(self, item: GoldQuestion, rank: int | None) -> None:
        self.total += 1
        self.by_language[item.language][1] += 1
        if rank is None:
            self.misses.append(item.id)
            return
        self.hits += 1
        self.reciprocal_rank_sum += 1 / rank
        self.by_language[item.language][0] += 1

    def as_dict(self) -> dict[str, object]:
        return {
            "n": self.total,
            "recall_at_k": round(self.recall_at_k, 3),
            "mrr": round(self.mrr, 3),
            "recall_by_language": {
                lang: round(self.language_recall(lang), 3) for lang in sorted(self.by_language)
            },
            "misses": self.misses,
        }


@dataclass(slots=True)
class RetrievalReport:
    k: int
    document: Metric = field(default_factory=Metric)
    section: Metric = field(default_factory=Metric)

    # Document-level shortcuts, kept for existing callers.
    @property
    def total(self) -> int:
        return self.document.total

    @property
    def recall_at_k(self) -> float:
        return self.document.recall_at_k

    @property
    def mrr(self) -> float:
        return self.document.mrr

    @property
    def misses(self) -> list[str]:
        return self.document.misses

    def language_recall(self, lang: str) -> float:
        return self.document.language_recall(lang)

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {"k": self.k, "document": self.document.as_dict()}
        if self.section.total:
            out["section"] = self.section.as_dict()
        return out


def load_retrieval_gold(path: Path) -> list[GoldQuestion]:
    """Load either gold format; tool-backed and out-of-scope items are skipped."""
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        if raw.get("requires_tool"):
            continue
        sections: tuple[Section, ...] = tuple(
            (r["source"], r["section"]) for r in raw.get("relevant", [])
        )
        sources = raw.get("expected_sources") or list(dict.fromkeys(s for s, _ in sections))
        docs = tuple(s for s in sources if s.startswith("doc:"))
        if not docs:
            continue
        items.append(
            GoldQuestion(
                raw["id"], raw["language"], raw["category"], raw["question"], docs, sections
            )
        )
    return items


def _section_of(chunk: RetrievedChunk) -> Section:
    return (chunk.source_id, chunk.heading_path[-1] if chunk.heading_path else "")


def document_rank(results: list[RetrievedChunk], item: GoldQuestion) -> int | None:
    """1-based rank of the first chunk from an expected document."""
    return next((i for i, r in enumerate(results, 1) if r.source_id in item.expected_sources), None)


def section_rank(results: list[RetrievedChunk], item: GoldQuestion) -> int | None:
    """1-based rank of the first chunk from an expected section."""
    expected = set(item.expected_sections)
    return next((i for i, r in enumerate(results, 1) if _section_of(r) in expected), None)


async def evaluate_retrieval(
    retriever: HybridRetriever, gold: list[GoldQuestion], *, k: int = 8
) -> RetrievalReport:
    """Document hit: any expected source in the top k. Section hit: any expected section."""
    report = RetrievalReport(k=k)
    for item in gold:
        results = await retriever.search(item.question, k=k)
        report.document.record(item, document_rank(results, item))
        if item.expected_sections:
            report.section.record(item, section_rank(results, item))
    return report
