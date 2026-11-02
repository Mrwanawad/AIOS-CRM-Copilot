"""Text normalization for search (Arabic orthographic variants + casing + whitespace).

Applied identically at index time and query time, so "أسعار", "اسعار" and "إسعار" all match.
Display text is never normalized; only the search copy is.
"""

from __future__ import annotations

import re
import unicodedata

_DIACRITICS = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭ]")
_TATWEEL = "ـ"
_TRANSLATE = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ة": "ه",
        "ؤ": "و",
        "ئ": "ي",
        # Eastern Arabic and Persian digits -> ASCII, so "٣ غرف" matches "3 غرف".
        **{chr(0x0660 + i): str(i) for i in range(10)},
        **{chr(0x06F0 + i): str(i) for i in range(10)},
    }
)
_WS = re.compile(r"\s+")


def normalize_for_search(text: str) -> str:
    """Lowercase, NFKC, unify Arabic letter variants, strip diacritics/tatweel, squash spaces."""
    text = unicodedata.normalize("NFKC", text)
    text = _DIACRITICS.sub("", text).replace(_TATWEEL, "")
    text = text.translate(_TRANSLATE).lower()
    return _WS.sub(" ", text).strip()


def has_arabic(text: str) -> bool:
    return any("؀" <= ch <= "ۿ" for ch in text)
