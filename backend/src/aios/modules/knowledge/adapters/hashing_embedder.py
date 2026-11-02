"""Adapter: deterministic feature-hashing embedder for tests and offline development.

NOT semantic: it hashes normalized word unigrams and bigrams into a fixed-size vector,
so it behaves like a lexical retriever. Use it to exercise the pipeline without
network access or API cost; never in production.
"""

from __future__ import annotations

import hashlib
import itertools
import math
import re
from collections.abc import Sequence

from aios.modules.knowledge.ports.embedder import Vector
from aios.shared.text import normalize_for_search

_TOKEN = re.compile(r"\w+", re.UNICODE)


class HashingEmbedder:
    def __init__(self, dimension: int = 1536) -> None:
        self._dimension = dimension

    @property
    def model_id(self) -> str:
        return f"hashing-{self._dimension}"

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [self._embed(t) for t in texts]

    async def embed_query(self, text: str) -> Vector:
        return self._embed(text)

    def _embed(self, text: str) -> Vector:
        tokens = _TOKEN.findall(normalize_for_search(text))
        features = tokens + [f"{a} {b}" for a, b in itertools.pairwise(tokens)]
        vec = [0.0] * self._dimension
        for feat in features:
            digest = hashlib.blake2b(feat.encode(), digest_size=8).digest()
            idx = int.from_bytes(digest[:4], "little") % self._dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]
