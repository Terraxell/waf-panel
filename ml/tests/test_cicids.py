"""CICIDS 2017 loader smoke test.

WHY: real CICIDS files are licence-gated and several GB. We feed the
     loader a tiny synthesised CSV with a representative row mix so
     a contributor can prove the projection works without the dataset.
"""

from __future__ import annotations

from pathlib import Path

from waf_ml.datasets import load_cicids_2017

_CSV_HEADER = (
    "Destination Port,Protocol,Flow Bytes/s,Total Fwd Packets,Label\n"
)
_CSV_ROWS = [
    "80,6,1200.5,5,BENIGN\n",
    "443,6,4500.0,12,BENIGN\n",
    "22,6,80.0,2,SSH-Patator\n",
    "8080,6,Infinity,3,Web Attack – Brute Force\n",
    "3389,6,15.5,1,DoS Hulk\n",
    "0,17,0.0,0,benign\n",
]


def test_load_cicids_2017_projects_rows(tmp_path: Path) -> None:
    csv_dir = tmp_path / "raw"
    csv_dir.mkdir()
    (csv_dir / "Wednesday-workingHours.pcap_ISCX.csv").write_text(
        _CSV_HEADER + "".join(_CSV_ROWS), encoding="utf-8",
    )

    rows = load_cicids_2017(csv_dir)
    assert len(rows) == len(_CSV_ROWS)


def test_load_cicids_2017_label_mapping(tmp_path: Path) -> None:
    csv_dir = tmp_path / "raw"
    csv_dir.mkdir()
    (csv_dir / "x.csv").write_text(
        _CSV_HEADER + "".join(_CSV_ROWS), encoding="utf-8",
    )

    rows = load_cicids_2017(csv_dir)
    labels = [r.label for r in rows]
    # Three BENIGN rows (case-insensitive) → label 0; the rest → 1.
    assert labels.count(0) == 3
    assert labels.count(1) == 3


def test_load_cicids_2017_synthesises_path(tmp_path: Path) -> None:
    csv_dir = tmp_path / "raw"
    csv_dir.mkdir()
    (csv_dir / "x.csv").write_text(
        _CSV_HEADER + _CSV_ROWS[0], encoding="utf-8",
    )

    rows = load_cicids_2017(csv_dir)
    assert len(rows) == 1
    r = rows[0]
    assert r.user_agent == "cicids-flow"
    assert "/flow/dport-80" in r.path
    assert r.method == "GET"  # port 80 → web traffic → GET


def test_load_cicids_2017_missing_dir_returns_empty(tmp_path: Path) -> None:
    """Same fall-through contract as load_csic_2010: silent empty list."""
    rows = load_cicids_2017(tmp_path / "does-not-exist")
    assert rows == []


def test_load_cicids_2017_handles_leading_spaces(tmp_path: Path) -> None:
    """Some CICIDS distributions ship with ' Destination Port' (leading space)."""
    csv_dir = tmp_path / "raw"
    csv_dir.mkdir()
    quirky = (
        " Destination Port, Protocol,Flow Bytes/s,Total Fwd Packets,Label\n"
        "80,6,1200.5,5,BENIGN\n"
        "443,6,4500.0,12,Web Attack – XSS\n"
    )
    (csv_dir / "fri.csv").write_text(quirky, encoding="utf-8")

    rows = load_cicids_2017(csv_dir)
    assert [r.label for r in rows] == [0, 1]


def test_cicids_request_runs_through_featurize(tmp_path: Path) -> None:
    """Smoke: a CICIDS-derived row must produce a valid feature vector."""
    from waf_ml.features import FEATURE_COLUMNS, featurize

    csv_dir = tmp_path / "raw"
    csv_dir.mkdir()
    (csv_dir / "x.csv").write_text(
        _CSV_HEADER + "80,6,1200.5,5,BENIGN\n", encoding="utf-8",
    )

    rows = load_cicids_2017(csv_dir)
    feats = featurize({
        "method": rows[0].method, "path": rows[0].path,
        "query": rows[0].query, "body": rows[0].body,
        "user_agent": rows[0].user_agent,
    })
    assert set(feats.keys()) == set(FEATURE_COLUMNS)
