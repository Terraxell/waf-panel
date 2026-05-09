"""CICIDS 2017 loader.

The CICIDS 2017 distribution from the Canadian Institute for
Cybersecurity ships per-day CSV files (`Monday-WorkingHours.pcap_ISCX.csv`,
`Wednesday-workingHours.pcap_ISCX.csv`, ...) with ~80 numeric flow
features per row, plus a final `Label` column that's either ``BENIGN``
or one of `Web Attack – ...` / `DoS ...` / `PortScan` / etc.

WHY a separate loader: CSIC ships raw HTTP requests; CICIDS ships
flow-level CSVs. We project CICIDS rows onto the *same*
`LabelledRequest` dataclass so the trainer can mix datasets if an
operator wants. Where flow rows have no real path/query/body the
loader synthesises plausible substitutes from the available columns
(destination port, protocol, flow length) — this is for offline
*evaluation* only; online inference always sees real HTTP fields.

NOTE: this loader is offline-only. The trainer falls back to the
synthetic generator if no path is given; CICIDS is opt-in via
``--dataset cicids --cicids-path PATH``.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path

from .synthetic import LabelledRequest

# WHY: CICIDS labels are heterogeneous. We map every non-BENIGN label
#      to "malicious=1" so we have a clean binary problem. The full
#      multi-class breakdown is a  task (per-class precision
#      so the dashboard can call out web-attacks vs DoS).
_BENIGN_LABEL = "BENIGN"


def _label_for(raw_label: str) -> int:
    return 0 if raw_label.strip().upper() == _BENIGN_LABEL else 1


def _row_to_request(row: dict[str, str]) -> LabelledRequest | None:
    """Project one flow-CSV row onto a LabelledRequest.

    SAFETY: CICIDS columns vary slightly between distribution years and
            even between days (`Destination Port` vs ` Destination Port`
            with leading space). We look up keys case-/space-insensitively
            and bail out cleanly on missing essentials.
    """
    norm = {k.strip().lower(): v for k, v in row.items() if k}

    label_raw = norm.get("label")
    if label_raw is None:
        return None

    dport = norm.get("destination port") or norm.get("dst port") or "0"
    proto = norm.get("protocol") or "tcp"
    flow_bytes = norm.get("flow bytes/s") or "0"
    pkt_count = norm.get("total fwd packets") or "0"

    # Synthesised fields — keep them deterministic given the row so
    # featurize() output is stable for golden tests.
    method = "GET" if int_or_zero(dport) in (80, 8080, 443, 8443) else "POST"
    path = f"/flow/dport-{dport}/proto-{proto}"
    query = f"bytes={flow_bytes}&pkts={pkt_count}"

    return LabelledRequest(
        method=method,
        path=path,
        query=query,
        body="",
        user_agent="cicids-flow",
        label=_label_for(label_raw),
    )


def int_or_zero(s: str) -> int:
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return 0


def _iter_csv(path: Path) -> Iterable[dict[str, str]]:
    # WHY: CICIDS files include occasional NaN/Inf rows from packet
    #      capture artefacts. csv.DictReader is happy with them; we
    #      let `_row_to_request` decide what to keep.
    with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh)
        yield from reader


def load_cicids_2017(root: Path | str) -> list[LabelledRequest]:
    """Load every *.csv under `root` into the LabelledRequest schema.

    Returns an empty list if `root` is missing or has no .csv files —
    same fall-through contract as :func:`load_csic_2010`.
    """
    root_p = Path(root)
    if not root_p.exists():
        return []

    out: list[LabelledRequest] = []
    for csv_file in sorted(root_p.rglob("*.csv")):
        for row in _iter_csv(csv_file):
            req = _row_to_request(row)
            if req is not None:
                out.append(req)
    return out


__all__ = ["load_cicids_2017"]
