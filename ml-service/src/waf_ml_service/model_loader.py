"""Pick and load the active model, once at startup.

Two paths, picked by ``ML_USE_REGISTRY``:

1. **Registry path** (production): query ``ml_models WHERE is_active``
   via :func:`waf_ml.registry.get_active`, joblib.load the .pkl pointed
   to by ``artifact_path``.
2. **Filesystem path** (dev/CI): load ``<ML_MODEL_DIR>/<algo>.pkl``
   directly. Used when the trainer wrote artefacts to a local volume
   without inserting a Postgres row (or when Postgres isn't running).

If the requested algorithm is missing, we fall through to
``ML_FALLBACK_ALGO`` (default: ``lr``). If both fail, the service
starts with ``model = None`` and ``/score`` returns
``fallback_reason="no_active_model"``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings

log = logging.getLogger("waf-ml-service.loader")


@dataclass(frozen=True)
class LoadedModel:
    estimator: Any
    algo: str
    version: str
    source: str  # "registry" | "filesystem"


def _load_pkl(path: Path) -> Any:
    import joblib

    return joblib.load(path)


def _from_registry(settings: Settings) -> LoadedModel | None:
    if not settings.use_registry:
        return None
    try:
        # Local import keeps psycopg out of the test path when registry is off.
        from waf_ml.registry import get_active
    except Exception as e:  # noqa: BLE001
        log.warning("waf_ml.registry not importable: %s", e)
        return None

    row = get_active(algo=settings.model_algo, dsn=settings.postgres_dsn)
    if row is None:
        log.warning("no active model for algo=%s in registry", settings.model_algo)
        return None
    try:
        est = _load_pkl(Path(row.artifact_path))
    except Exception as e:  # noqa: BLE001
        log.error("failed to joblib.load(%s): %s", row.artifact_path, e)
        return None
    return LoadedModel(
        estimator=est, algo=row.algo, version=row.version, source="registry",
    )


def _from_filesystem(settings: Settings, algo: str) -> LoadedModel | None:
    pkl = Path(settings.model_dir) / f"{algo}.pkl"
    if not pkl.exists():
        log.info("no %s on filesystem at %s", algo, pkl)
        return None
    try:
        est = _load_pkl(pkl)
    except Exception as e:  # noqa: BLE001
        log.error("joblib.load(%s) failed: %s", pkl, e)
        return None
    # WHY: filesystem path has no version; fall back to mtime so the
    #      response still tells operators which artefact they hit.
    version = f"fs:{algo}:{int(pkl.stat().st_mtime)}"
    return LoadedModel(estimator=est, algo=algo, version=version, source="filesystem")


def load_active_model(settings: Settings | None = None) -> LoadedModel | None:
    """Try registry → primary algo on disk → fallback algo on disk → None."""
    settings = settings or Settings()

    found = _from_registry(settings)
    if found is not None:
        return found

    found = _from_filesystem(settings, settings.model_algo)
    if found is not None:
        return found

    if settings.fallback_algo and settings.fallback_algo != settings.model_algo:
        log.info("falling back to algo=%s", settings.fallback_algo)
        found = _from_filesystem(settings, settings.fallback_algo)
        if found is not None:
            return found

    log.warning("no model could be loaded — service starts in fallback mode")
    return None
