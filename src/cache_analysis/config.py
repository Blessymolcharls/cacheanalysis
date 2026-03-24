"""Configuration types and defaults for gem5 cache experiments."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from typing import Iterable, List

DEFAULT_CACHE_SIZE_KB = 32
# SKIP: 16B excluded — triggers AVX-VNNI (opcode 0f38/0x59) panic in gem5's
# TimingSimpleCPU because the benchmark binary uses instructions not yet
# implemented by this gem5 build.  Also architecturally atypical (real
# hardware standardised on 64B blocks).  Remove this comment and add 16 back
# once the benchmark is recompiled with -march=x86-64 (no AVX-VNNI).
DEFAULT_BLOCK_SIZES_BYTES = [32, 64, 128, 256]
# Backward-compatible alias used by existing imports/call sites.
DEFAULT_BLOCK_SIZES_KB = DEFAULT_BLOCK_SIZES_BYTES
DEFAULT_ASSOCIATIVITIES = [1, 2, 4, 8]
DEFAULT_REPLACEMENT_POLICY = "LRU"
DEFAULT_ADDRESS_SPACE_BITS = 32


@dataclass(frozen=True)
class CacheGeometry:
    """Static cache geometry for one experiment run.

    Attributes:
        cache_size_kb: Total cache capacity in KB.
        block_size_kb: Block size in bytes (legacy field name retained).
        associativity: Number of ways per set.
        address_space_bits: Width of simulated addresses.
    """

    cache_size_kb: int
    block_size_kb: int
    associativity: int
    address_space_bits: int = DEFAULT_ADDRESS_SPACE_BITS

    @property
    def cache_size_bytes(self) -> int:
        return self.cache_size_kb * 1024

    @property
    def block_size_bytes(self) -> int:
        return self.block_size_kb

    @property
    def num_blocks(self) -> int:
        return self.cache_size_bytes // self.block_size_bytes

    @property
    def num_sets(self) -> int:
        if self.associativity <= 0:
            raise ValueError("Associativity must be > 0")
        return self.num_blocks // self.associativity

    def validate(self) -> None:
        if self.cache_size_kb <= 0:
            raise ValueError("cache_size_kb must be positive")
        if self.block_size_kb <= 0:
            raise ValueError("block_size_kb must be positive")
        if self.associativity <= 0:
            raise ValueError("associativity must be positive")
        if self.address_space_bits <= 0:
            raise ValueError("address_space_bits must be positive")

        if self.cache_size_bytes % self.block_size_bytes != 0:
            raise ValueError(
                "Cache size must be evenly divisible by block size. "
                f"cache={self.cache_size_bytes}, block={self.block_size_bytes}"
            )

        if self.num_blocks % self.associativity != 0:
            raise ValueError(
                "Number of blocks must be divisible by associativity. "
                f"blocks={self.num_blocks}, assoc={self.associativity}"
            )

        if self.num_sets <= 0:
            raise ValueError(
                "Configuration yields zero sets; check cache/block size and associativity"
            )


@dataclass
class OutputConfig:
    """Output paths for experiment artifacts."""

    output_dir: str = "results"
    csv_name: str = "cache_results.csv"
    json_name: str = "cache_results.json"
    summary_name: str = "summary.txt"

    plot_hit_vs_block: str = "plot_block_vs_hit_rate.png"
    plot_miss_vs_block: str = "plot_block_vs_miss_rate.png"
    plot_hit_vs_assoc: str = "plot_assoc_vs_hit_rate.png"
    plot_miss_vs_assoc: str = "plot_assoc_vs_miss_rate.png"

    bar_hit_vs_block: str = "bar_block_vs_hit_rate.png"
    bar_miss_vs_block: str = "bar_block_vs_miss_rate.png"
    bar_hit_vs_assoc: str = "bar_assoc_vs_hit_rate.png"
    bar_miss_vs_assoc: str = "bar_assoc_vs_miss_rate.png"


@dataclass
class ExperimentConfig:
    """Top-level configuration for full factorial gem5 experiments."""

    cache_size_kb: int = DEFAULT_CACHE_SIZE_KB
    block_sizes_kb: List[int] = field(default_factory=lambda: list(DEFAULT_BLOCK_SIZES_KB))
    associativities: List[int] = field(default_factory=lambda: list(DEFAULT_ASSOCIATIVITIES))
    replacement_policy: str = DEFAULT_REPLACEMENT_POLICY
    address_space_bits: int = DEFAULT_ADDRESS_SPACE_BITS
    output: OutputConfig = field(default_factory=OutputConfig)

    def validate(self) -> None:
        if self.replacement_policy.upper() != "LRU":
            raise ValueError(
                "This framework currently supports only LRU replacement policy"
            )
        _validate_positive_int_list("block_sizes_kb", self.block_sizes_kb)
        _validate_positive_int_list("associativities", self.associativities)
        if self.cache_size_kb <= 0:
            raise ValueError("cache_size_kb must be > 0")
        if self.address_space_bits <= 0:
            raise ValueError("address_space_bits must be > 0")

        for block_kb in self.block_sizes_kb:
            for assoc in self.associativities:
                geometry = CacheGeometry(
                    cache_size_kb=self.cache_size_kb,
                    block_size_kb=block_kb,
                    associativity=assoc,
                    address_space_bits=self.address_space_bits,
                )
                geometry.validate()

    def all_geometries(self) -> List[CacheGeometry]:
        geometries: List[CacheGeometry] = []
        for block_kb in self.block_sizes_kb:
            for assoc in self.associativities:
                geometry = CacheGeometry(
                    cache_size_kb=self.cache_size_kb,
                    block_size_kb=block_kb,
                    associativity=assoc,
                    address_space_bits=self.address_space_bits,
                )
                geometry.validate()
                geometries.append(geometry)
        return geometries


@dataclass
class Gem5RunConfig:
    """Configuration for executing experiments with the real gem5 simulator.

    This mode runs one benchmark binary repeatedly while sweeping cache geometry.
    The classic cache model is configured as L1 D-cache only for direct
    hit/miss extraction from gem5 stats.
    """

    gem5_config_script: str
    benchmark_binary: str
    gem5_binary: str = ""

    benchmark_args: str = ""
    workload_name: str = "gem5_workload"

    cpu_type: str = "TimingSimpleCPU"
    mem_size: str = "2GB"
    max_ticks: int = 0

    stats_hits_key: str = ""
    stats_misses_key: str = ""

    output_subdir: str = "gem5_runs"

    resolved_gem5_binary: str = ""

    def validate(self) -> None:
        if self.gem5_binary.strip():
            self.resolved_gem5_binary = self.gem5_binary.strip()
        else:
            detected = shutil.which("gem5.opt")
            if not detected:
                raise FileNotFoundError(
                    "gem5 binary not found. Install gem5 and either add gem5.opt to PATH "
                    "or pass --gem5-binary /path/to/gem5.opt."
                )
            self.resolved_gem5_binary = detected
        if not self.gem5_config_script.strip():
            raise ValueError("gem5_config_script must be provided")
        if not self.benchmark_binary.strip():
            raise ValueError("benchmark_binary must be provided")
        if not self.workload_name.strip():
            raise ValueError("workload_name must be provided")
        if self.max_ticks < 0:
            raise ValueError("max_ticks must be >= 0")


def _validate_positive_int_list(name: str, values: Iterable[int]) -> None:
    values_list = list(values)
    if not values_list:
        raise ValueError(f"{name} must not be empty")
    for value in values_list:
        if not isinstance(value, int):
            raise TypeError(f"{name} must contain only integers")
        if value <= 0:
            raise ValueError(f"{name} must contain only positive values")
