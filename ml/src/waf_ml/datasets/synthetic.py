"""Tiny synthetic HTTP-request generator.

WHY: tests and demos need a zero-dependency dataset that:
     - is bounded in size and runs in <1 second
     - has both benign and clearly-malicious examples
     - is deterministic given a seed, so golden tests stay stable
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class LabelledRequest:
    method: str
    path: str
    query: str
    body: str
    user_agent: str
    label: int  # 0 = benign, 1 = malicious


_BENIGN_PATHS = [
    "/", "/index.html", "/login.php", "/dashboard", "/api/v1/users",
    "/static/app.js", "/static/style.css", "/health", "/about", "/contact",
]
_BENIGN_QUERIES = ["", "page=1", "id=42", "lang=ru", "ref=email", "tab=overview"]
_BENIGN_UAS = [
    "Mozilla/5.0 (Windows NT 10.0) Chrome/127.0",
    "Mozilla/5.0 (Macintosh) Safari/17.6",
    "Mozilla/5.0 (X11; Linux) Firefox/130.0",
]

_MAL_PATHS = [
    "/index.php", "/login.php", "/search", "/profile",
    "/../etc/passwd", "/cgi-bin/exec",
]
_MAL_QUERIES = [
    "id=1 OR 1=1--",
    "id=1' UNION SELECT username,password FROM users--",
    "q=<script>alert(1)</script>",
    "url=javascript:alert(1)",
    "file=../../../../etc/passwd",
    "cmd=cat+/etc/passwd",
    "input=<img src=x onerror=eval('alert(1)')>",
    "search=admin'--",
]
_MAL_UAS = [
    "sqlmap/1.7.2",
    "Nikto/2.5.0",
    "curl/8.4.0",
    "Mozilla/5.0 (compatible; bot)",
    "python-requests/2.31",
]


def generate_synthetic(n: int = 2000, seed: int = 42, ratio_malicious: float = 0.4) -> list[LabelledRequest]:
    """Produce `n` deterministic labelled requests.

    SAFETY: caller must not assume real-world distributions; this is
            for unit tests and demo runs only. Real evaluation goes
            against CSIC / CICIDS via `load_csic_2010`.
    """
    rng = random.Random(seed)
    out: list[LabelledRequest] = []
    n_mal = int(n * ratio_malicious)
    n_ben = n - n_mal

    for _ in range(n_ben):
        out.append(LabelledRequest(
            method=rng.choice(["GET", "GET", "GET", "POST"]),
            path=rng.choice(_BENIGN_PATHS),
            query=rng.choice(_BENIGN_QUERIES),
            body="",
            user_agent=rng.choice(_BENIGN_UAS),
            label=0,
        ))
    for _ in range(n_mal):
        out.append(LabelledRequest(
            method=rng.choice(["GET", "POST"]),
            path=rng.choice(_MAL_PATHS),
            query=rng.choice(_MAL_QUERIES),
            body="" if rng.random() > 0.3 else rng.choice(_MAL_QUERIES),
            user_agent=rng.choice(_MAL_UAS),
            label=1,
        ))
    rng.shuffle(out)
    return out


__all__ = ["LabelledRequest", "generate_synthetic"]
