"""Dataset loaders for the offline trainer.

Real datasets (CSIC 2010, CICIDS 2017) live under `ml/datasets/raw/`
and are pulled by the operator (licence-aware download). The
synthetic generator is for tests and demos that don't depend on
external data.
"""

from .cicids import load_cicids_2017
from .csic import load_csic_2010
from .synthetic import generate_synthetic

__all__ = ["generate_synthetic", "load_csic_2010", "load_cicids_2017"]
