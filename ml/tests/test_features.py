"""Golden-file feature stability.

WHY: training and online inference both call `featurize`. Any silent
     change to a feature definition would break the deployed model
     without a single Python error. The golden vector below is the
     contract; bumping it is a deliberate retraining signal.
"""

from __future__ import annotations

from waf_ml.features import FEATURE_COLUMNS, featurize, to_vector

# WHY: 25-feature contract. If you append a column, append the
#      expected value here too — and bump the model version.
_GOLDEN_REQUEST = {
    "method": "GET",
    "path": "/login.php",
    "query": "id=1' UNION SELECT username,password FROM users--",
    "body": "",
    "user_agent": "sqlmap/1.7.2",
    "referer": "",
}


def test_feature_columns_count():
    # SAFETY: bumping this number means retraining. Lock it on purpose.
    assert len(FEATURE_COLUMNS) == 25


def test_feature_columns_are_unique():
    assert len(FEATURE_COLUMNS) == len(set(FEATURE_COLUMNS))


def test_featurize_returns_all_columns():
    out = featurize(_GOLDEN_REQUEST)
    assert set(out.keys()) == set(FEATURE_COLUMNS)


def test_to_vector_preserves_order():
    feats = featurize(_GOLDEN_REQUEST)
    vec = to_vector(feats)
    assert vec == [feats[c] for c in FEATURE_COLUMNS]


def test_golden_attack_vector():
    """If any of these flip, the trained model would silently mis-score."""
    feats = featurize(_GOLDEN_REQUEST)
    # Length-derived features.
    assert feats["len_url"] == float(len("/login.php"))
    assert feats["len_query"] == float(
        len("id=1' UNION SELECT username,password FROM users--")
    )
    assert feats["len_body"] == 0.0
    assert feats["n_params"] == 1.0  # one query string segment
    # Token presence — the attack signal.
    assert feats["tok_union_select"] == 1.0
    assert feats["tok_or_1_eq_1"] == 0.0  # OR 1=1 not in this payload
    assert feats["tok_script"] == 0.0
    # Method one-hot.
    assert feats["method_get"] == 1.0
    assert feats["method_post"] == 0.0
    # UA classifier.
    assert feats["ua_is_bot"] == 1.0
    # Headers.
    assert feats["has_referer"] == 0.0


def test_benign_request_has_no_attack_tokens():
    benign = {
        "method": "POST",
        "path": "/api/v1/users",
        "query": "page=1",
        "body": "",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/127.0",
        "referer": "https://example.com/dashboard",
    }
    feats = featurize(benign)
    assert feats["tok_union_select"] == 0.0
    assert feats["tok_script"] == 0.0
    assert feats["tok_path_traversal"] == 0.0
    assert feats["tok_etc_passwd"] == 0.0
    assert feats["ua_is_bot"] == 0.0
    assert feats["has_referer"] == 1.0
    assert feats["method_post"] == 1.0


def test_path_traversal_detected():
    feats = featurize({
        "method": "GET",
        "path": "/files",
        "query": "name=../../../../etc/passwd",
        "body": "",
        "user_agent": "curl/8.4",
    })
    assert feats["tok_path_traversal"] == 1.0
    assert feats["tok_etc_passwd"] == 1.0


def test_xss_script_tag_detected():
    feats = featurize({
        "method": "GET",
        "path": "/search",
        "query": "q=<script>alert(1)</script>",
        "body": "",
        "user_agent": "Mozilla/5.0",
    })
    assert feats["tok_script"] == 1.0


def test_missing_fields_safe_defaults():
    feats = featurize({})
    assert feats["len_url"] == 0.0
    assert feats["len_query"] == 0.0
    assert feats["entropy_path"] == 0.0
    assert feats["method_other"] == 1.0  # empty method falls into "other"
    assert feats["ua_is_bot"] == 0.0
