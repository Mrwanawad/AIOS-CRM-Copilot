"""Reciprocal Rank Fusion: combine ranked lists without calibrating their raw scores."""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence

RRF_K = 60  # standard constant from Cormack et al. (2009)


def rrf_fuse[T: Hashable](
    rankings: Mapping[str, Sequence[T]], *, k: int = RRF_K, limit: int | None = None
) -> list[tuple[T, float, dict[str, int]]]:
    """Return ``(item, score, {retriever: rank})`` sorted by fused score, best first.

    ``rankings`` maps a retriever name to its result ids, best first. Ties are broken
    by first appearance so results are deterministic.
    """
    scores: dict[T, float] = {}
    ranks: dict[T, dict[str, int]] = {}
    order: dict[T, int] = {}
    for name, items in rankings.items():
        for rank, item in enumerate(items, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
            ranks.setdefault(item, {})[name] = rank
            order.setdefault(item, len(order))
    fused = sorted(scores, key=lambda i: (-scores[i], order[i]))
    if limit is not None:
        fused = fused[:limit]
    return [(i, scores[i], ranks[i]) for i in fused]
