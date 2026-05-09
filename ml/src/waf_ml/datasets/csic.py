"""CSIC 2010 loader.

Expects the dataset on disk under `ml/datasets/raw/csic2010/` with
the canonical filenames `normalTrafficTraining.txt`,
`anomalousTrafficTest.txt`, `normalTrafficTest.txt`. The file format
is "raw HTTP request blocks separated by blank lines".
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlsplit

from .synthetic import LabelledRequest


def _parse_block(block: str) -> tuple[str, str, str, str, str] | None:
    lines = [ln for ln in block.splitlines() if ln.strip()]
    if not lines:
        return None
    request_line = lines[0].split()
    if len(request_line) < 2:
        return None
    method = request_line[0]
    raw_url = request_line[1]
    parts = urlsplit(raw_url)
    path = parts.path
    query = parts.query

    headers: dict[str, str] = {}
    body_lines: list[str] = []
    in_body = False
    for ln in lines[1:]:
        if not in_body and ln == "":
            in_body = True
            continue
        if in_body:
            body_lines.append(ln)
        elif ":" in ln:
            k, _, v = ln.partition(":")
            headers[k.strip()] = v.strip()
    body = "\n".join(body_lines)
    ua = headers.get("User-Agent", "")
    return method, path, query, body, ua


def _iter_blocks(path: Path) -> Iterable[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    for block in text.split("\n\n\n"):
        if block.strip():
            yield block


def load_csic_2010(root: Path | str) -> list[LabelledRequest]:
    """Load the dataset. Returns empty list if files are missing.

    WHY: the offline trainer falls back to the synthetic generator
         in tests; the real loader runs only when an operator has
         placed the dataset on disk.
    """
    root_p = Path(root)
    out: list[LabelledRequest] = []

    for fname, label in [
        ("normalTrafficTraining.txt", 0),
        ("normalTrafficTest.txt", 0),
        ("anomalousTrafficTest.txt", 1),
    ]:
        f = root_p / fname
        if not f.exists():
            continue
        for block in _iter_blocks(f):
            parsed = _parse_block(block)
            if parsed is None:
                continue
            method, path, query, body, ua = parsed
            out.append(LabelledRequest(
                method=method, path=path, query=query, body=body,
                user_agent=ua, label=label,
            ))
    return out


__all__ = ["load_csic_2010"]
