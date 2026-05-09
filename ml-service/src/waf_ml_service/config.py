"""Service configuration via env vars.

WHY: separated from ``main.py`` so tests can spin up the app with a
custom config without monkey-patching env. Defaults are dev-safe.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    model_dir: str = os.environ.get("ML_MODEL_DIR", "/app/models")
    model_algo: str = os.environ.get("ML_MODEL_ALGO", "xgboost")
    fallback_algo: str = os.environ.get("ML_FALLBACK_ALGO", "lr")

    redis_url: str = os.environ.get("ML_REDIS_URL", "redis://redis:6379/2")
    redis_ttl_sec: int = int(os.environ.get("ML_REDIS_TTL_SEC", "30"))

    use_registry: bool = os.environ.get("ML_USE_REGISTRY", "false").lower() == "true"
    postgres_dsn: str | None = os.environ.get("ML_POSTGRES_DSN")

    # Sprint 13 (audit C13): TreeSHAP per-request explainer for tree
    # models. Off by default — `shap` is a heavy import and TreeExplainer
    # adds ~1.5–3 ms per call. Operators opt in by setting
    # ``ML_USE_SHAP=true``; the existing weights × value path remains the
    # fallback if shap is missing or the model isn't tree-based.
    use_shap: bool = os.environ.get("ML_USE_SHAP", "false").lower() == "true"


def get_settings() -> Settings:
    return Settings()
