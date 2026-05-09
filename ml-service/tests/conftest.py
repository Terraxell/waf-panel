"""Shared fixtures — stub estimators and TestClient.

WHY: real joblib + sklearn aren't needed to test the API surface.
We feed `_AppState` tiny estimators that mimic predict_proba and expose
either feature_importances_ or coef_ for /explain tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make sure waf_ml is importable from the sibling ml/ tree at test time.
_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "ml" / "src"))


class _StubEstimator:
    """XGBoost-shaped stub: predict_proba + feature_importances_."""

    def __init__(self):
        import numpy as np

        # 25 features; mark UNION/SELECT, JS-script and path-traversal as the
        # heavy importances so /explain tests can assert on them.
        # Indices: 10 tok_union_select, 12 tok_script, 14 tok_path_traversal,
        # 24 ua_is_bot, 2 len_body.
        imps = np.zeros(25, dtype=np.float64)
        imps[10] = 0.45
        imps[12] = 0.30
        imps[14] = 0.10
        imps[24] = 0.05
        imps[2] = 0.10
        self.feature_importances_ = imps

    def predict_proba(self, X):  # noqa: N803
        import numpy as np

        out = np.zeros((X.shape[0], 2), dtype=np.float64)
        attack_signal = (X[:, 10] + X[:, 12] + X[:, 14]) > 0.0
        out[:, 1] = np.where(attack_signal, 0.97, 0.03)
        out[:, 0] = 1.0 - out[:, 1]
        return out


class _LinearStub:
    """LogisticRegression-shaped stub: predict_proba + coef_."""

    def __init__(self):
        import numpy as np

        coef = np.zeros((1, 25), dtype=np.float64)
        coef[0, 10] = 2.0   # union/select push class-1 up
        coef[0, 24] = 1.5   # bot UA push up
        coef[0, 23] = -1.0  # has_referer pushes class-1 down
        self.coef_ = coef

    def predict_proba(self, X):  # noqa: N803
        import numpy as np

        z = (X @ self.coef_.reshape(-1)).reshape(-1)
        p = 1.0 / (1.0 + np.exp(-z))
        out = np.zeros((X.shape[0], 2), dtype=np.float64)
        out[:, 1] = p
        out[:, 0] = 1.0 - p
        return out


@pytest.fixture
def stub_state():
    """An _AppState pre-loaded with the XGB-shaped stub and no Redis."""
    from waf_ml_service.cache import ScoreCache
    from waf_ml_service.main import _AppState
    from waf_ml_service.model_loader import LoadedModel

    state = _AppState()
    state.model = LoadedModel(
        estimator=_StubEstimator(),
        algo="stub",
        version="stub-v0",
        source="filesystem",
    )
    state.cache = ScoreCache(client=None, ttl_sec=30)
    return state


@pytest.fixture
def client(stub_state):
    from fastapi.testclient import TestClient

    from waf_ml_service.main import create_app

    return TestClient(create_app(stub_state))


@pytest.fixture
def lr_state():
    """An _AppState backed by the linear stub (LR-flavour /explain path)."""
    from waf_ml_service.cache import ScoreCache
    from waf_ml_service.main import _AppState
    from waf_ml_service.model_loader import LoadedModel

    state = _AppState()
    state.model = LoadedModel(
        estimator=_LinearStub(),
        algo="lr",
        version="lr-v0",
        source="filesystem",
    )
    state.cache = ScoreCache(client=None, ttl_sec=30)
    return state


@pytest.fixture
def lr_client(lr_state):
    from fastapi.testclient import TestClient

    from waf_ml_service.main import create_app

    return TestClient(create_app(lr_state))


@pytest.fixture
def client_no_model():
    """A client whose state has no model — to exercise the fallback branch."""
    from fastapi.testclient import TestClient

    from waf_ml_service.cache import ScoreCache
    from waf_ml_service.main import _AppState, create_app

    state = _AppState()
    state.model = None
    state.cache = ScoreCache(client=None, ttl_sec=30)
    return TestClient(create_app(state))
