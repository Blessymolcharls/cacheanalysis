"""Core domain models for gem5 experiment records.

FIX: ExperimentResult.to_dict() now includes 'status' and 'failure_reason'
     columns so CSV/JSON outputs clearly mark failed configurations instead of
     silently emitting zero-valued rows.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class CacheCounters:
    """Counters for cache performance metrics and invariants."""

    total_accesses: int = 0
    hits: int = 0
    misses: int = 0


    @property
    def hit_rate(self) -> float:
        if self.total_accesses == 0:
            return 0.0
        return self.hits / self.total_accesses

    @property
    def miss_rate(self) -> float:
        if self.total_accesses == 0:
            return 0.0
        return self.misses / self.total_accesses

    def validate(self) -> None:
        if self.total_accesses != self.hits + self.misses:
            raise ValueError(
                "Invariant violation: total_accesses != hits + misses"
            )

        if abs((self.hit_rate + self.miss_rate) - 1.0) > 1e-9 and self.total_accesses > 0:
            raise ValueError(
                "Invariant violation: hit_rate + miss_rate must equal 1"
            )

    def as_dict(self) -> Dict[str, Any]:
        # FIX: Removed self.validate() call here.  validate() is called
        #      explicitly after construction in gem5_runner.  Calling it again
        #      during serialisation crashes on failed results whose counters are
        #      intentionally zero (the invariant holds, but previously a caller
        #      could get confused).  Keeping serialisation pure and side-effect-
        #      free avoids cascading failures during CSV/JSON export.
        return {
            "total_accesses": self.total_accesses,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": self.hit_rate,
            "miss_rate": self.miss_rate,
        }


@dataclass(frozen=True)
class ExperimentKey:
    """Unique key for one experiment condition and workload."""

    cache_size_kb: int
    block_size_kb: int
    associativity: int
    replacement_policy: str
    workload_name: str
    block_size_bytes: int = 0


@dataclass
class ExperimentResult:
    """Result record for a single experiment run."""

    key: ExperimentKey
    counters: CacheCounters

    runtime_seconds: float
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        # FIX: Derive status and failure_reason from notes sentinel so that
        #      every CSV/JSON row explicitly records success vs failure.
        #      Consumers (dashboards, scripts) can filter on status='failed'
        #      without parsing free-text notes.
        _FAILED = "status=failed"
        _SUCCESS = "status=success"
        is_failed = any(_FAILED in note for note in self.notes)
        status = "failed" if is_failed else "success"

        failure_reason = ""
        if is_failed:
            for note in self.notes:
                if note.startswith("failure_reason="):
                    failure_reason = note[len("failure_reason="):]
                    break
            if not failure_reason:
                failure_reason = "unknown"

        # IMPROVEMENT: notes stored as semicolon-joined string for CSV
        #              compatibility (lists don't round-trip through CSV).
        notes_str = " ; ".join(self.notes)

        data = {
            "cache_size_kb": self.key.cache_size_kb,
            "block_size_kb": self.key.block_size_kb,
            "block_size_bytes": self.key.block_size_bytes,
            "associativity": self.key.associativity,
            "replacement_policy": self.key.replacement_policy,
            "workload_name": self.key.workload_name,
            "runtime_seconds": self.runtime_seconds,
            # FIX: Explicit status column — key addition for fault-tolerant output.
            "status": status,
            "failure_reason": failure_reason,
            "notes": notes_str,
        }
        data.update(self.counters.as_dict())
        return data


@dataclass
class ExperimentBatch:
    """Container for all experiment outputs."""

    config_snapshot: Dict[str, Any]
    results: List[ExperimentResult]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "config": self.config_snapshot,
            "results": [result.to_dict() for result in self.results],
        }

    def to_rows(self) -> List[Dict[str, Any]]:
        return [result.to_dict() for result in self.results]


def dataclass_to_dict(instance: Any) -> Dict[str, Any]:
    """Safe dataclass serialization helper.

    This wrapper exists so callers can convert nested dataclasses in one place
    without importing `asdict` from `dataclasses` in every module.
    """

    return asdict(instance)
