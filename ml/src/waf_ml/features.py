"""HTTP-request → feature vector.

WHY: the same function MUST run during training and during online
     inference (Sprint 8). If they drift, model quality silently
     collapses. We pin the contract with `tests/test_features.py`
     against a fixed input.

NOTE: pure function, no I/O, deterministic. Inputs are normalised
      strings; outputs are floats keyed by canonical column names.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any
from urllib.parse import unquote

# WHY: ordered column list — model training and inference must produce
#      vectors in the same order. Adding a feature means appending here.
FEATURE_COLUMNS: list[str] = [
    "len_url",
    "len_query",
    "len_body",
    "n_params",
    "n_special_path",
    "n_special_query",
    "entropy_path",
    "entropy_query",
    "n_url_encoded",
    "ratio_special_path",
    # Token presence (0/1):
    "tok_union_select",
    "tok_or_1_eq_1",
    "tok_script",
    "tok_javascript_proto",
    "tok_path_traversal",
    "tok_etc_passwd",
    "tok_eval",
    "tok_base64_long",
    # Method one-hot (small set):
    "method_get",
    "method_post",
    "method_put",
    "method_delete",
    "method_other",
    # Misc:
    "has_referer",
    "ua_is_bot",
]

_SPECIAL_CHARS = set("'\"<>;/*=%&|")
_BOT_UA_HINTS = (
    "bot", "spider", "crawl", "sqlmap", "nikto", "wfuzz", "dirbuster",
    "curl", "wget", "python-requests", "go-http",
)


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    counts: dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(s)
    h = 0.0
    for c in counts.values():
        p = c / n
        h -= p * math.log2(p)
    return h


def _count_special(s: str) -> int:
    return sum(1 for ch in s if ch in _SPECIAL_CHARS)


def _normalise(s: Any) -> str:
    if s is None:
        return ""
    return str(s)


def featurize(req: Mapping[str, Any]) -> dict[str, float]:
    """Turn one normalised HTTP-request dict into a feature dict.

    Expected keys (any of them missing → safe defaults):
        method, path, query, body, headers (dict), user_agent, referer.
    """
    method = _normalise(req.get("method")).upper()
    path = _normalise(req.get("path"))
    query = _normalise(req.get("query"))
    body = _normalise(req.get("body"))

    headers = req.get("headers") or {}
    if not isinstance(headers, Mapping):
        headers = {}
    ua = _normalise(req.get("user_agent") or headers.get("user-agent") or headers.get("User-Agent"))
    referer = _normalise(req.get("referer") or headers.get("referer") or headers.get("Referer"))

    decoded_path = unquote(path)
    decoded_query = unquote(query)
    haystack = (decoded_path + "?" + decoded_query + " " + body).lower()

    n_params = query.count("&") + (1 if query else 0)
    n_special_path = _count_special(decoded_path)
    n_special_query = _count_special(decoded_query)

    # Token detectors — keep them as plain substring checks.
    # WHY: regex would gain nothing here on typed shorthands; speed and
    #      reproducibility matter more than a few false positives.
    tok_union_select = "union" in haystack and "select" in haystack
    tok_or_1_eq_1 = " or 1=1" in haystack or " or '1'='1" in haystack
    tok_script = "<script" in haystack
    tok_js_proto = "javascript:" in haystack
    tok_path_traversal = "../" in haystack
    tok_etc_passwd = "/etc/passwd" in haystack
    tok_eval = "eval(" in haystack or "exec(" in haystack
    # base64-ish: long alnum block ending with `=` padding.
    tok_b64 = any(
        len(part) >= 20 and part.rstrip("=").isalnum()
        for part in body.split()
    )

    return {
        "len_url": float(len(path)),
        "len_query": float(len(query)),
        "len_body": float(len(body)),
        "n_params": float(n_params),
        "n_special_path": float(n_special_path),
        "n_special_query": float(n_special_query),
        "entropy_path": _entropy(decoded_path),
        "entropy_query": _entropy(decoded_query),
        "n_url_encoded": float(path.count("%") + query.count("%")),
        "ratio_special_path": (n_special_path / len(decoded_path)) if decoded_path else 0.0,
        "tok_union_select": float(tok_union_select),
        "tok_or_1_eq_1": float(tok_or_1_eq_1),
        "tok_script": float(tok_script),
        "tok_javascript_proto": float(tok_js_proto),
        "tok_path_traversal": float(tok_path_traversal),
        "tok_etc_passwd": float(tok_etc_passwd),
        "tok_eval": float(tok_eval),
        "tok_base64_long": float(tok_b64),
        "method_get": float(method == "GET"),
        "method_post": float(method == "POST"),
        "method_put": float(method == "PUT"),
        "method_delete": float(method == "DELETE"),
        "method_other": float(method not in {"GET", "POST", "PUT", "DELETE"}),
        "has_referer": float(bool(referer)),
        "ua_is_bot": float(any(h in ua.lower() for h in _BOT_UA_HINTS)),
    }


def featurize_batch(reqs: list[Mapping[str, Any]]) -> list[dict[str, float]]:
    return [featurize(r) for r in reqs]


def to_vector(features: Mapping[str, float]) -> list[float]:
    """Lock the column order. Same vector layout for train and inference."""
    return [float(features.get(c, 0.0)) for c in FEATURE_COLUMNS]


__all__ = ["FEATURE_COLUMNS", "featurize", "featurize_batch", "to_vector"]
