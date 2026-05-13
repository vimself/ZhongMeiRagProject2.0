from __future__ import annotations

import hashlib
import html
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

SPARSE_DIMENSION = 500_000

_ASCII_TOKEN_RE = re.compile(r"[a-z0-9_]+")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
_HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
_WHITESPACE_RE = re.compile(r"\s+")


def dense_vector_literal(values: Sequence[float]) -> str:
    finite_values = [float(value) for value in values if math.isfinite(float(value))]
    return "[" + ",".join(f"{value:.8g}" for value in finite_values) + "]"


def clean_display_text(text: str) -> str:
    normalized = html.unescape(text or "")
    normalized = _HTML_TAG_RE.sub(" ", normalized)
    normalized = _WHITESPACE_RE.sub(" ", normalized)
    return normalized.strip()


def text_term_weights(text: str) -> dict[str, float]:
    """Build stable lexical weights for fallback and SeekDB SPARSEVECTOR probes."""
    lowered = clean_display_text(text).lower()
    weights: dict[str, float] = {}
    for token in _ASCII_TOKEN_RE.findall(lowered):
        weights[token] = weights.get(token, 0.0) + 1.0
    for run in _CJK_RUN_RE.findall(lowered):
        for ch in run:
            weights[ch] = weights.get(ch, 0.0) + 0.5
        if len(run) >= 2:
            for index in range(len(run) - 1):
                token = run[index : index + 2]
                weights[token] = weights.get(token, 0.0) + 1.0
    return weights


def sparse_vector_literal(weights: Mapping[Any, float]) -> str | None:
    merged: dict[int, float] = {}
    for key, value in weights.items():
        try:
            weight = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(weight) or weight <= 0:
            continue
        dim = key if isinstance(key, int) else _stable_sparse_dimension(str(key))
        if dim <= 0:
            continue
        merged[dim] = merged.get(dim, 0.0) + weight
    if not merged:
        return None
    return "{" + ",".join(f"{dim}:{value:.8g}" for dim, value in sorted(merged.items())) + "}"


def _stable_sparse_dimension(token: str) -> int:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, byteorder="big", signed=False)
    return value % SPARSE_DIMENSION + 1
