"""End-to-end /score, /healthz, /readyz checks via FastAPI TestClient."""

from __future__ import annotations


def test_healthz_reports_loaded_model(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["model_loaded"] is True
    assert body["model_version"] == "stub-v0"


def test_readyz_same_payload(client):
    r = client.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert {"status", "model_loaded", "model_version", "redis_ok"} <= set(body.keys())


def test_score_malicious_request_high_prob(client):
    r = client.post("/score", json={
        "method": "GET",
        "path": "/login.php",
        "query": "id=1' UNION SELECT password FROM users--",
        "body": "",
        "user_agent": "sqlmap/1.7.2",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["prob"] is not None
    assert body["prob"] > 0.9
    assert body["model"] == "stub"
    assert body["model_version"] == "stub-v0"
    assert body["cached"] is False
    assert body["latency_ms"] >= 0.0
    assert body["fallback_reason"] is None


def test_score_benign_request_low_prob(client):
    r = client.post("/score", json={
        "method": "GET",
        "path": "/dashboard",
        "query": "page=1",
        "body": "",
        "user_agent": "Mozilla/5.0 Chrome/127",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["prob"] is not None
    assert body["prob"] < 0.1


def test_score_response_shape_is_stable(client):
    r = client.post("/score", json={"method": "GET", "path": "/", "query": ""})
    body = r.json()
    expected = {"prob", "model", "model_version", "latency_ms", "cached", "fallback_reason"}
    assert expected <= set(body.keys())


def test_score_returns_fallback_when_no_model_loaded(client_no_model):
    r = client_no_model.post("/score", json={
        "method": "GET", "path": "/", "query": "",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["prob"] is None
    assert body["model"] is None
    assert body["model_version"] is None
    assert body["fallback_reason"] == "no_active_model"


def test_healthz_degraded_when_no_model(client_no_model):
    r = client_no_model.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["model_loaded"] is False


def test_score_cache_hit_marks_cached(stub_state, client):
    """Pre-warm the cache, then verify the next call returns cached=True."""
    from waf_ml_service.cache import cache_key

    payload = {
        "method": "GET",
        "path": "/dashboard",
        "query": "page=1",
        "body": "",
        "user_agent": "Mozilla/5.0",
    }
    key = cache_key(payload["method"], payload["path"], payload["query"])

    # Use an in-memory dict-backed cache for this test.
    class _DictCache:
        def __init__(self) -> None:
            self.store: dict[str, dict] = {}

        @property
        def healthy(self):
            return True

        def get(self, k):
            return self.store.get(k)

        def set(self, k, v):
            self.store[k] = v

    stub_state.cache = _DictCache()

    # First call populates.
    r1 = client.post("/score", json=payload)
    assert r1.json()["cached"] is False
    # Second call hits.
    r2 = client.post("/score", json=payload)
    assert r2.json()["cached"] is True
    # And the cache key actually exists.
    assert key in stub_state.cache.store


def test_iforest_decision_function_does_not_collapse_on_batch_1():
    """fix regression: IsolationForest-shaped estimator with
    only `decision_function` must give a non-trivial probability on a
    single-row input. The previous per-batch min/max normalisation
    collapsed to 0 here.
    """
    from waf_ml_service.cache import ScoreCache
    from waf_ml_service.main import _AppState, _score_request
    from waf_ml_service.model_loader import LoadedModel
    from waf_ml_service.schemas import ScoreRequest

    class _IFStub:
        """Mimics sklearn IsolationForest's decision_function only."""

        def decision_function(self, X):  # noqa: N803
            import numpy as np
            # Inlier-ish for benign, anomaly-ish for attack — flag on
            # tok_union_select column (index 10).
            df = np.where(X[:, 10] > 0.0, -0.30, 0.30)
            return df

    state = _AppState()
    state.model = LoadedModel(
        estimator=_IFStub(), algo="iforest", version="if-v0", source="filesystem",
    )
    state.cache = ScoreCache(client=None, ttl_sec=30)

    benign = ScoreRequest(method="GET", path="/", query="", body="", user_agent="Mozilla/5.0")
    malicious = ScoreRequest(
        method="GET", path="/", query="id=1 UNION SELECT *", body="", user_agent="sqlmap/1.7",
    )

    benign_resp = _score_request(state, benign)
    mal_resp = _score_request(state, malicious)

    assert benign_resp.prob is not None
    assert mal_resp.prob is not None
    # The whole hotfix point — not 0.0:
    assert benign_resp.prob > 0.05
    assert mal_resp.prob > 0.05
    # And ordering is preserved: malicious > benign.
    assert mal_resp.prob > benign_resp.prob
