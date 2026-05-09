"""Optional TreeSHAP-backed explainer — (audit C-list item 13).

WHY: the default ``/explain`` path uses ``weights × feature_value`` —
fast, dependency-free, and faithful for linear models, but for tree
models (XGBoost, RandomForest) it does not capture feature interactions
or the tree-path-conditional contribution that TreeSHAP produces.

This module wraps ``shap.TreeExplainer`` with three guarantees:

1. **Lazy import.** ``shap`` is heavy (~150 MB with deps); we pull it
   in only the first time the operator opts in via ``ML_USE_SHAP=true``.
2. **Cached per-estimator.** A WeakKeyDictionary keyed on the estimator
   object means each model artefact builds the explainer exactly once,
   even though the FastAPI handler is called per-request.
3. **Fail-soft.** ``shap`` import error or non-tree model → ``None``,
   and the caller falls back to the existing ``weights × feature``
   path. The endpoint never raises 500 because of explainer plumbing.
"""

from __future__ import annotations

import logging
import threading
from typing import Any
from weakref import WeakKeyDictionary

import numpy as np

log = logging.getLogger("waf-ml-service.shap")

# WeakKey: when the model object is garbage-collected (e.g. a hot-swap),
# the cached explainer goes with it. No memory leak, no stale weights.
_EXPLAINER_CACHE: WeakKeyDictionary[Any, Any] = WeakKeyDictionary()
_LOCK = threading.Lock()
_IMPORT_FAILED = False  # remembered between calls to avoid retry storms


def _import_shap():
    """Late, idempotent ``import shap``. Returns the module or ``None``."""
    global _IMPORT_FAILED
    if _IMPORT_FAILED:
        return None
    try:
        import shap  # type: ignore[import-untyped]

        return shap
    except Exception as e:  # noqa: BLE001 — shap is optional
        log.warning("shap not available, falling back to weights×feature: %s", e)
        _IMPORT_FAILED = True
        return None


def _is_tree_model(estimator: Any) -> bool:
    """Heuristic: only attempt TreeExplainer for tree-based estimators.

    Avoids the 'shap.TreeExplainer raises on a LinearSVC' surprise: we'd
    rather fall back silently than burn an exception path per request.
    """
    cls = type(estimator).__name__.lower()
    if any(token in cls for token in ("xgb", "lgbm", "catboost", "forest", "tree", "isolation")):
        return True
    # Ensembles wrapping tree estimators (e.g. sklearn Pipeline) — peek
    # at the final step.
    final = getattr(estimator, "_final_estimator", None) or getattr(estimator, "named_steps", None)
    if final is None:
        return False
    if hasattr(final, "values"):
        # Pipeline.named_steps — last value is the final estimator.
        try:
            tail = list(final.values())[-1]
            return _is_tree_model(tail)
        except Exception:  # noqa: BLE001
            return False
    return _is_tree_model(final)


def get_explainer(estimator: Any) -> Any | None:
    """Return a cached ``shap.TreeExplainer`` or ``None`` if unavailable.

    Calling this multiple times for the same estimator returns the same
    explainer instance. Thread-safe — under a lock the WeakKeyDictionary
    behaves correctly even with concurrent requests.
    """
    if estimator is None:
        return None
    if not _is_tree_model(estimator):
        return None
    shap = _import_shap()
    if shap is None:
        return None
    with _LOCK:
        cached = _EXPLAINER_CACHE.get(estimator)
        if cached is not None:
            return cached
        try:
            expl = shap.TreeExplainer(estimator)
        except Exception as e:  # noqa: BLE001 — model not tree-shaped
            log.warning("TreeExplainer construction failed: %s — falling back", e)
            return None
        _EXPLAINER_CACHE[estimator] = expl
        return expl


def shap_contributions(
    estimator: Any,
    X: np.ndarray,
) -> np.ndarray | None:
    """Return per-feature SHAP values for the single row in ``X``.

    Shape: (n_features,). On any failure path returns ``None`` so the
    caller can fall back to the weights×feature computation.
    """
    expl = get_explainer(estimator)
    if expl is None:
        return None
    try:
        sv = expl.shap_values(X)
    except Exception as e:  # noqa: BLE001 — model behaving oddly
        log.warning("shap_values failed: %s — falling back", e)
        return None

    # shap returns either an ndarray (binary models) or a list of ndarrays
    # (multi-class). Take the positive class for binary, the last class
    # for multi-class — both reduce to the row vector we want.
    if isinstance(sv, list):
        sv = sv[-1]
    arr = np.asarray(sv)
    if arr.ndim == 2:
        return arr[0]
    if arr.ndim == 1:
        return arr
    log.warning("unexpected shap_values shape: %s", arr.shape)
    return None


def reset_for_tests() -> None:
    """Test hook — clears caches and the import-failed sticky bit."""
    global _IMPORT_FAILED
    with _LOCK:
        _EXPLAINER_CACHE.clear()
        _IMPORT_FAILED = False


__all__ = [
    "get_explainer",
    "reset_for_tests",
    "shap_contributions",
]
