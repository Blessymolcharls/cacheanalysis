"""Result export and textual reporting helpers.

FIX: write_csv now unions fieldnames across ALL rows before writing so that
     failed-run rows (which have the same schema but status='failed') never
     cause KeyError in the DictWriter.  build_summary_text also reports failed
     configurations explicitly.
"""

from __future__ import annotations

import csv
import json
import os
from collections import defaultdict
from typing import Dict, Iterable, List

from .models import ExperimentBatch, ExperimentResult


class ResultWriter:
    """Write experiment outputs to CSV, JSON, and summary text."""

    def __init__(self, output_dir: str) -> None:
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def write_csv(self, file_name: str, results: Iterable[ExperimentResult]) -> str:
        rows = [r.to_dict() for r in results]
        path = os.path.join(self.output_dir, file_name)

        if not rows:
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write("")
            return path

        # FIX: Build fieldnames as the UNION of all row keys, not just row[0].
        #      Failed vs successful rows always share the same schema after our
        #      models.py changes, but this union approach is robust to any future
        #      schema divergence.
        all_keys: set = set()
        for row in rows:
            all_keys.update(row.keys())
        # IMPROVEMENT: Sort for deterministic column order; put key columns first.
        priority = [
            "workload_name", "cache_size_kb", "block_size_bytes",
            "block_size_kb", "associativity", "replacement_policy",
            "status", "hit_rate", "miss_rate", "hits", "misses",
            "total_accesses", "runtime_seconds", "failure_reason", "notes",
        ]
        ordered = [k for k in priority if k in all_keys]
        remainder = sorted(all_keys - set(ordered))
        fieldnames = ordered + remainder

        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=fieldnames, extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows(rows)

        return path

    def write_json(self, file_name: str, batch: ExperimentBatch) -> str:
        path = os.path.join(self.output_dir, file_name)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(batch.to_dict(), handle, indent=2)
        return path

    def write_summary(self, file_name: str, results: Iterable[ExperimentResult]) -> str:
        path = os.path.join(self.output_dir, file_name)
        text = build_summary_text(list(results))
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path


def build_summary_text(results: List[ExperimentResult]) -> str:
    """Build human-readable report with key trends and spot checks.

    IMPROVEMENT: Now shows failed configurations clearly so experimenters can
                 quickly identify which geometries need investigation.
    """

    lines: List[str] = []
    lines.append("Cache Simulation Summary")
    lines.append("=" * 80)
    lines.append("")

    if not results:
        lines.append("No results available.")
        return "\n".join(lines)

    # FIX: Separate successful from failed results for the summary.
    _FAILED_SENTINEL = "status=failed"
    successful = [r for r in results if not any(_FAILED_SENTINEL in n for n in r.notes)]
    failed = [r for r in results if any(_FAILED_SENTINEL in n for n in r.notes)]

    lines.append(f"Total configurations: {len(results)}")
    lines.append(f"  Successful: {len(successful)}")
    lines.append(f"  Failed:     {len(failed)}")
    lines.append("")

    # ------------------------------------------------------------------
    # Successful results section
    # ------------------------------------------------------------------
    by_workload: Dict[str, List[ExperimentResult]] = defaultdict(list)
    for result in successful:
        by_workload[result.key.workload_name].append(result)

    for workload, group in sorted(by_workload.items()):
        lines.append(f"Workload: {workload}")
        lines.append("-" * 80)

        # Sort by block bytes then associativity for stable comparisons.
        group = sorted(group, key=lambda r: (r.key.block_size_bytes, r.key.associativity))

        for result in group:
            lines.append(
                " | ".join(
                    [
                        f"Block={result.key.block_size_bytes}B",
                        f"Assoc={result.key.associativity}-way",
                        f"Accesses={result.counters.total_accesses}",
                        f"Hits={result.counters.hits}",
                        f"Misses={result.counters.misses}",
                        f"HitRate={result.counters.hit_rate:.6f}",
                        f"MissRate={result.counters.miss_rate:.6f}",
                    ]
                )
            )

        lines.append("")

    # ------------------------------------------------------------------
    # IMPROVEMENT: Failed results section — always shown when failures exist.
    # ------------------------------------------------------------------
    if failed:
        lines.append("FAILED Configurations")
        lines.append("-" * 80)
        lines.append("  These runs did not produce valid stats.txt output.")
        lines.append("  Check per-run stderr.log for the root cause.")
        lines.append("")
        failed = sorted(failed, key=lambda r: (r.key.block_size_bytes, r.key.associativity))
        for result in failed:
            reason = "unknown"
            stderr_log = ""
            for note in result.notes:
                if note.startswith("failure_reason="):
                    reason = note[len("failure_reason="):]
                if note.startswith("stderr_log="):
                    stderr_log = note[len("stderr_log="):]
            line = (
                f"  Block={result.key.block_size_bytes}B "
                f"Assoc={result.key.associativity}-way "
                f"| reason: {reason}"
            )
            if stderr_log:
                line += f"\n    → see {stderr_log}"
            lines.append(line)
        lines.append("")

    lines.append("Key Insight Targets")
    lines.append("-" * 80)
    lines.append("1. Hit rate often increases with block size initially, then may saturate.")
    lines.append("2. Miss rate often decreases initially, but may rise if conflicts dominate.")
    lines.append("3. Associativity tends to show diminishing returns beyond 4-way.")

    return "\n".join(lines)
