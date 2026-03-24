"""Utilities for parsing gem5 stats output files.

The parser is intentionally tolerant to naming differences across gem5 versions.
It extracts hit and miss counters using preferred keys with fallback candidates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List


@dataclass(frozen=True)
class Gem5StatsSnapshot:
    hits: int
    misses: int
    total_accesses: int


def parse_stats_file(stats_path: str) -> Dict[str, float]:
    """Parse gem5 stats.txt into a key/value dictionary.

    Lines in stats.txt usually look like:
        system.cpu.dcache.overallHits::total   1234   # comment
    """

    parsed: Dict[str, float] = {}
    with open(stats_path, "r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            key = parts[0]
            value_token = parts[1]
            try:
                value = float(value_token)
            except ValueError:
                continue
            parsed[key] = value
    return parsed


def extract_hits_and_misses(
    stats: Dict[str, float],
    preferred_hits_key: str = "",
    preferred_misses_key: str = "",
) -> Gem5StatsSnapshot:
    """Extract hit/miss counts with key fallbacks for classic cache stats."""

    hit_candidates = _candidate_keys(
        preferred_hits_key,
        [
            "system.cpu.dcache.overallHits::total",
            "system.cpu.dcache.overall_hits::total",
            "system.dcache.overallHits::total",
            "system.dcache.overall_hits::total",
            "system.cpu.dcache.demandHits::total",
            "system.cpu.dcache.demand_hits::total",
            "system.dcache.demandHits::total",
            "system.dcache.demand_hits::total",
            "system.cpu.dcache.ReadReq.hits::total",
            "system.dcache.ReadReq.hits::total",
            "system.cpu.dcache.overallHits::cpu.data",
            "system.dcache.overallHits::cpu.data",
        ],
    )
    miss_candidates = _candidate_keys(
        preferred_misses_key,
        [
            "system.cpu.dcache.overallMisses::total",
            "system.cpu.dcache.overall_misses::total",
            "system.dcache.overallMisses::total",
            "system.dcache.overall_misses::total",
            "system.cpu.dcache.demandMisses::total",
            "system.cpu.dcache.demand_misses::total",
            "system.dcache.demandMisses::total",
            "system.dcache.demand_misses::total",
            "system.cpu.dcache.ReadReq.misses::total",
            "system.dcache.ReadReq.misses::total",
            "system.cpu.dcache.overallMisses::cpu.data",
            "system.dcache.overallMisses::cpu.data",
        ],
    )

    hits = _first_found_int(stats, hit_candidates)
    misses = _first_found_int(stats, miss_candidates)

    if hits < 0 or misses < 0:
        raise ValueError(
            "Could not find cache hit/miss counters in gem5 stats. "
            "Use --gem5-stats-hits-key and --gem5-stats-misses-key to override."
        )

    total = hits + misses
    return Gem5StatsSnapshot(hits=hits, misses=misses, total_accesses=total)


def _candidate_keys(preferred: str, defaults: List[str]) -> List[str]:
    if preferred.strip():
        return [preferred.strip(), *defaults]
    return defaults


def _first_found_int(stats: Dict[str, float], keys: Iterable[str]) -> int:
    for key in keys:
        if key in stats:
            return int(stats[key])
    return -1
