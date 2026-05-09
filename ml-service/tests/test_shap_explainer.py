"""SHAP explainer wrapper — (audit C13).

WHY: ``shap`` is intentionally optional. The tests below verify the
wrapper's three guarantees without forcing CI to install shap:

  1. Lazy + idempotent import. When the import fails, the wrapper
     remembers and never re-tries (no log spam, no retry storms).
  2. Cache by estimator identity. Same estimator object → same
     explainer instance.
  3. Non-tree fall-through. A linear model returns ``None`` from
     ``shap_contributions`` so the caller's legacy path runs.

The "real shap is available" path is exercised in the integration test
when shap is installed in the dev container; here we use a hand-rolled
fake to keep the unit test self-sufficient.
"""

from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from waf_ml_service import shap_explainer


@pytest.fixture(autouse=True)
def _clean():
    shap_explainer.reset_for_tests()
    yield
    shap_explainer.reset_for_tests()


# ── 1. Non-tree estimators short-circuit before importing shap ──────


class _LinearStub:
    """An LR-shaped estimator. Should never reach the shap import path."""

    coef_ = np.array([0.1, -0.2, 0.3])


def test_non_tree_returns_none(monkeypatch):
    # Even if shap is available, a non-tree estimator must not be wrapped.
    fake = types.ModuleType("shap")
    fake.TreeExplainer = lambda _est: pytest.fail("must not be called for LR")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "shap", fake)
    assert shap_explainer.get_explainer(_LinearStub()) is None
    assert shap_explainer.shap_contributions(_LinearStub(), np.zeros((1, 3))) is None


# ── 2. Tree-named estimator + fake shap → caches the explainer ─────


class _TreeBoosterStub:
    """Class name contains 'forest' so the heuristic accepts it."""

    feature_importances_ = np.array([0.5, 0.5])


class _FakeExpl:
    def __init__(self, est):
        self.est = est
        self.calls = 0

    def shap_values(self, X):
        self.calls += 1
        # Mirror the real binary-class shape: (n_rows, n_features).
        return np.tile(np.array([[0.4, -0.1]]), (X.shape[0], 1))


def _install_fake_shap(monkeypatch, expl_factory=_FakeExpl):
    fake = types.ModuleType("shap")
    fake.TreeExplainer = expl_factory  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "shap", fake)
    # Force shap_explainer to re-attempt the import after the previous
    # test possibly tripped the import-failed sticky bit.
    shap_explainer.reset_for_tests()


def test_tree_estimator_returns_contributions(monkeypatch):
    _install_fake_shap(monkeypatch)
    est = _TreeBoosterStub()
    # Class name is ``_TreeBoosterStub`` — contains 'tree' ✓ and 'boost' ✓
    # both are accepted by the heuristic.
    sv = shap_explainer.shap_contributions(est, np.zeros((1, 2)))
    assert sv is not None
    assert sv.shape == (2,)
    np.testing.assert_allclose(sv, [0.4, -0.1])


def test_explainer_is_cached_per_estimator(monkeypatch):
    _install_fake_shap(monkeypatch)
    est = _TreeBoosterStub()
    e1 = shap_explainer.get_explainer(est)
    e2 = shap_explainer.get_explainer(est)
    assert e1 is e2  # same instance → cache hit


def test_shap_values_failure_falls_back(monkeypatch):
    class _BrokenExpl:
        def __init__(self, _est):
            pass

        def shap_values(self, _X):
            raise RuntimeError("intentional")

    _install_fake_shap(monkeypatch, _BrokenExpl)
    sv = shap_explainer.shap_contributions(_TreeBoosterStub(), np.zeros((1, 2)))
    assert sv is None  # caller will use weights × feature instead


def test_multiclass_shape_reduced_to_row(monkeypatch):
    class _MultiClassExpl:
        def __init__(self, _est):
            pass

        def shap_values(self, X):
            # List per class — binary classifiers in shap return a list
            # with two entries; we should pick the last (positive class).
            return [
                np.zeros((X.shape[0], 2)),
                np.array([[0.7, -0.3]]),
            ]

    _install_fake_shap(monkeypatch, _MultiClassExpl)
    sv = shap_explainer.shap_contributions(_TreeBoosterStub(), np.zeros((1, 2)))
    assert sv is not None
    np.testing.assert_allclose(sv, [0.7, -0.3])


# ── 3. Missing shap module is remembered (no retry storm) ──────────


def test_missing_shap_returns_none_and_remembers(monkeypatch):
    monkeypatch.setitem(sys.modules, "shap", None)  # forces ImportError
    # Reset the sticky bit so the import attempt happens once.
    shap_explainer.reset_for_tests()
    assert shap_explainer._import_shap() is None
    # Second call short-circuits without re-importing — easy to verify by
    # checking the sticky state directly.
    assert shap_explainer._IMPORT_FAILED is True
    assert shap_explainer._import_shap() is None
