"""Cache analysis framework package.

This package provides gem5-based cache analysis automation.
"""

from .config import (
    DEFAULT_ASSOCIATIVITIES,
    DEFAULT_BLOCK_SIZES_KB,
    DEFAULT_CACHE_SIZE_KB,
    ExperimentConfig,
)
from .gem5_runner import Gem5ExperimentRunner

__all__ = [
    "DEFAULT_ASSOCIATIVITIES",
    "DEFAULT_BLOCK_SIZES_KB",
    "DEFAULT_CACHE_SIZE_KB",
    "ExperimentConfig",
    "Gem5ExperimentRunner",
]
