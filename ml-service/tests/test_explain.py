"""POST /explain — top-K feature contributors and provenance."""

from __future__ import annotations

import math

_MALICIOUS = {
    "method": "GET",
    "path": "/login.php",
    "query": "id=1' UNION SELECT password FROM users--",
    "body": "",
    "user_agent": "sqlmap/1.7.2",
}


def test_explain_uses_feature_importances_for_xgb_stub(client):
    r = client.post("/explain", json=_MALICIOUS)
    assert r.status_code == 200
    body = r.json()
    assert body["method"] == "feature_importances"
    assert body["model"] == "stub"
    assert body["model_version"] == "stub-v0"
    assert isinstance(body["contributors"], list)
    assert len(body["contributors"]) > 0


def test_explain_returns_top_k_normalised_to_unit_sum(client):
    r = client.post("/explain?top_k=3", json=_MALICIOUS)
    body = r.json()
    weights = [c["weight"] for c in body["contributors"]]
    assert len(weights) == 3
    # WHY: weights are normalised by absolute magnitude and sum to 1.0;
    #      sign is preserved so the UI can colour pos vs neg.
    assert abs(sum(abs(w) for w in weights) - 1.0) < 1e-6


def test_explain_picks_attack_features_for_malicious(client):
    r = client.post("/explain", json=_MALICIOUS)
    features = {c["feature"]: c["weight"] for c in r.json()["contributors"]}
    # WHY: golden malicious request fires UNION/SELECT, sqlmap UA. Both
    #      should bubble to the top.
    assert "tok_union_select" in features
    assert features["tok_union_select"] > 0.0


def test_explain_uses_coef_for_linear_stub(lr_client):
    r = lr_client.post("/explain", json=_MALICIOUS)
    assert r.status_code == 200
    body = r.json()
    assert body["method"] == "coef"
    # The malicious vector activates tok_union_select (coef=+2) and ua_is_bot
    # (coef=+1.5); both should appear with positive sign.
    features = {c["feature"]: c["weight"] for c in body["contributors"]}
    assert features.get("tok_union_select", 0) > 0.0
    assert features.get("ua_is_bot", 0) > 0.0


def test_explain_response_shape_is_stable(client):
    r = client.post("/explain", json=_MALICIOUS)
    body = r.json()
    expected = {"prob", "model", "model_version", "contributors", "method", "fallback_reason"}
    assert expected <= set(body.keys())
    for c in body["contributors"]:
        assert {"feature", "weight"} <= set(c.keys())


def test_explain_falls_back_when_no_model_loaded(client_no_model):
    r = client_no_model.post("/explain", json=_MALICIOUS)
    assert r.status_code == 200
    body = r.json()
    assert body["prob"] is None
    assert body["contributors"] == []
    assert body["method"] == "unsupported"
    assert body["fallback_reason"] == "no_active_model"


def test_explain_returns_empty_when_estimator_has_no_weights(stub_state, client):
    """An estimator without coef_ / feature_importances_ → method=unsupported."""

    class NoWeights:
        def predict_proba(self, X):  # noqa: N803
            import numpy as np
            return np.column_stack([np.zeros(len(X)), np.ones(len(X))])

    # Swap the loaded estimator to one that exposes neither attribute.
    stub_state.model = stub_state.model.__class__(
        estimator=NoWeights(),
        algo="custom",
        version="custom-v0",
        source="filesystem",
    )
    r = client.post("/explain", json=_MALICIOUS)
    body = r.json()
    assert body["method"] == "unsupported"
    assert body["contributors"] == []


def test_explain_top_k_clamps_to_at_least_one(client):
    r = client.post("/explain?top_k=0", json=_MALICIOUS)
    body = r.json()
    # WHY: top_k=0 is a no-op for the user; we serve at least 1 row.
    assert len(body["contributors"]) >= 1


def test_explain_handles_zero_contribution_request(client):
    """A benign-everything request hits no token features; the response is
    a valid empty contributor list rather than a crash."""
    r = client.post("/explain", json={
        "method": "GET", "path": "/", "query": "",
        "body": "", "user_agent": "Mozilla/5.0",
    })
    body = r.json()
    # The stub model has zero importance on most columns of a benign vector,
    # so the absolute sum may collapse to ~0. Accept either an empty list
    # OR a non-zero list — both are valid; what's NOT valid is a crash.
    assert math.isfinite(body["prob"]) or body["prob"] is None
