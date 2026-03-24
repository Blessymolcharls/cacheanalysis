"""gem5-backed experiment runner.

This module executes the real gem5 simulator across cache geometry sweeps and
exports results through the existing reporting/plotting pipeline.

FIX: Overhauled for fault-tolerance so that individual run failures never crash
     the entire experiment pipeline.  Key changes vs the original:
       - _invoke_gem5 retry loop logic corrected (was broken: retried 0 times).
       - MAX_RETRIES raised to 2 configurable attempts (original had 1).
       - run_single_geometry wraps all failure paths and returns a structured
         FailedExperimentResult instead of raising.
       - export_all / visualization skip failed results gracefully.
       - Richer logging: START / SUCCESS / FAILED with stderr snippet.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import ExperimentConfig, Gem5RunConfig
from .gem5_stats import extract_hits_and_misses, parse_stats_file
from .logging_config import get_logger
from .models import (
    CacheCounters,
    ExperimentBatch,
    ExperimentKey,
    ExperimentResult,
)
from .reporting import ResultWriter
from .visualization import Plotter

# FIX: Maximum number of gem5 invocation attempts per configuration.
#      Original code declared _max_retries = 1 but the while-loop logic was
#      broken so it effectively attempted just once and then raised.
#      Now this constant explicitly controls retries and is used correctly.
_GEM5_MAX_ATTEMPTS = 3  # 1 initial + 2 retries


class Gem5ExperimentRunner:
    """Run experiment sweeps with gem5 executable and parse stats outputs."""

    def __init__(self, config: ExperimentConfig, gem5: Gem5RunConfig) -> None:
        self.config = config
        self.gem5 = gem5
        self.logger = get_logger(self.__class__.__name__)

        self.config.validate()
        self.gem5.validate()
        self._validate_paths()

    # ------------------------------------------------------------------
    # Path validation
    # ------------------------------------------------------------------

    def _validate_paths(self) -> None:
        missing: List[str] = []
        for name, raw in [
            ("gem5_binary", self.gem5.resolved_gem5_binary),
            ("gem5_config_script", self.gem5.gem5_config_script),
            ("benchmark_binary", self.gem5.benchmark_binary),
        ]:
            if not Path(raw).exists():
                missing.append(f"{name}={raw}")
        if missing:
            raise FileNotFoundError(
                "Missing gem5 path(s): " + ", ".join(missing)
            )

    # ------------------------------------------------------------------
    # Main sweep
    # ------------------------------------------------------------------

    def run_all(self) -> ExperimentBatch:
        self.logger.info("Starting gem5 experiment sweep")
        start = time.perf_counter()

        geometries = self.config.all_geometries()
        results: List[ExperimentResult] = []
        failed_runs: List[Dict] = []  # IMPROVEMENT: structured failure records

        from concurrent.futures import ThreadPoolExecutor, as_completed

        runs_root = Path(self.config.output.output_dir) / self.gem5.output_subdir
        runs_root.mkdir(parents=True, exist_ok=True)

        # IMPROVEMENT: Log the experiment plan upfront so progress is clear.
        self.logger.info(
            "Experiment plan: %d configurations | output_root=%s",
            len(geometries),
            runs_root,
        )

        def run_single_geometry(run_id: int, geometry) -> ExperimentResult:
            """Run one cache geometry and return a result (success or failure).

            FIX: This function NEVER raises.  All error paths return a
                 structured ExperimentResult with status='failed' so that the
                 surrounding ThreadPoolExecutor loop always receives a value
                 rather than an exception crashing the future.
            """
            label = f"block={geometry.block_size_bytes}B assoc={geometry.associativity}"
            run_dir = runs_root / f"b{geometry.block_size_bytes}B_a{geometry.associativity}"
            run_dir.mkdir(parents=True, exist_ok=True)
            stats_path = run_dir / "stats.txt"

            # IMPROVEMENT: Structured START log entry.
            self.logger.info(
                "[START] run %d/%d | %s | run_dir=%s",
                run_id,
                len(geometries),
                label,
                run_dir,
            )

            runtime = 0.0
            reused_existing = False
            failure_reason: Optional[str] = None

            try:
                # ----------------------------------------------------------
                # Step 1: Execute gem5 (or reuse existing stats).
                # ----------------------------------------------------------
                # FIX: VALIDATION CHECK — only reuse if stats.txt is non-empty.
                if stats_path.exists() and stats_path.stat().st_size > 0:
                    reused_existing = True
                    self.logger.info(
                        "[REUSE] Existing stats.txt found for %s; skipping execution.",
                        label,
                    )
                else:
                    try:
                        runtime = self._invoke_gem5(geometry, run_dir)
                    except RuntimeError as exc:
                        # FIX: Capture the gem5 invocation failure reason.
                        failure_reason = str(exc)

                # ----------------------------------------------------------
                # Step 2: Validate stats.txt before attempting parse.
                # ----------------------------------------------------------
                # FIX: Check existence and non-emptiness; do NOT crash if missing.
                if failure_reason is None:
                    if not stats_path.exists():
                        failure_reason = (
                            f"gem5 run produced no stats.txt at {stats_path}"
                        )
                    elif stats_path.stat().st_size == 0:
                        failure_reason = (
                            f"stats.txt exists but is empty: {stats_path}"
                        )

                if failure_reason is not None:
                    # Read stderr snippet for rich diagnostics.
                    stderr_snippet = _read_stderr_snippet(run_dir)
                    self.logger.error(
                        "[FAILED] %s | reason=%s | stderr_hint=%s | stderr_log=%s",
                        label,
                        failure_reason,
                        stderr_snippet,
                        run_dir / "stderr.log",
                    )
                    return _make_failed_result(geometry, self.config, self.gem5, run_dir, failure_reason)

                # ----------------------------------------------------------
                # Step 3: Parse stats.txt.
                # ----------------------------------------------------------
                try:
                    parsed = parse_stats_file(str(stats_path))
                except Exception as exc:
                    failure_reason = f"stats.txt parse error: {exc}"
                    self.logger.error("[FAILED] %s | %s", label, failure_reason)
                    return _make_failed_result(geometry, self.config, self.gem5, run_dir, failure_reason)

                # ----------------------------------------------------------
                # Step 4: Extract hit/miss counters.
                # ----------------------------------------------------------
                try:
                    snap = extract_hits_and_misses(
                        parsed,
                        preferred_hits_key=self.gem5.stats_hits_key,
                        preferred_misses_key=self.gem5.stats_misses_key,
                    )
                except ValueError as exc:
                    failure_reason = f"hit/miss extraction failed: {exc}"
                    self.logger.error("[FAILED] %s | %s", label, failure_reason)
                    return _make_failed_result(geometry, self.config, self.gem5, run_dir, failure_reason)

                # ----------------------------------------------------------
                # Step 5: Build and validate counters.
                # ----------------------------------------------------------
                try:
                    counters = CacheCounters(
                        total_accesses=snap.total_accesses,
                        hits=snap.hits,
                        misses=snap.misses,
                    )
                    counters.validate()
                except ValueError as exc:
                    failure_reason = f"counter invariant violated: {exc}"
                    self.logger.error("[FAILED] %s | %s", label, failure_reason)
                    return _make_failed_result(geometry, self.config, self.gem5, run_dir, failure_reason)

                # ----------------------------------------------------------
                # Step 6: Assemble successful result.
                # ----------------------------------------------------------
                key = ExperimentKey(
                    cache_size_kb=geometry.cache_size_kb,
                    block_size_kb=geometry.block_size_kb,
                    block_size_bytes=geometry.block_size_bytes,
                    associativity=geometry.associativity,
                    replacement_policy=self.config.replacement_policy,
                    workload_name=self.gem5.workload_name,
                )
                notes = [
                    "Source: gem5 stats.txt",
                    "status=success",
                    f"Run dir: {run_dir}",
                    f"hit_key_override={self.gem5.stats_hits_key or 'auto'}",
                    f"miss_key_override={self.gem5.stats_misses_key or 'auto'}",
                ]
                if reused_existing:
                    notes.append("Reused existing stats.txt (resume mode)")

                # IMPROVEMENT: Log success with hit-rate for quick sanity check.
                self.logger.info(
                    "[SUCCESS] %s | hits=%d misses=%d hit_rate=%.4f | runtime=%.2fs",
                    label,
                    snap.hits,
                    snap.misses,
                    counters.hit_rate,
                    runtime,
                )

                return ExperimentResult(
                    key=key,
                    counters=counters,
                    runtime_seconds=runtime,
                    notes=notes,
                )

            except Exception as exc:
                # FIX: Catch-all safety net — this function must never propagate.
                failure_reason = f"Unexpected error: {exc}"
                self.logger.exception(
                    "[FAILED] %s | Unexpected exception caught", label
                )
                return _make_failed_result(geometry, self.config, self.gem5, run_dir, failure_reason)

        # ------------------------------------------------------------------
        # Dispatch runs in parallel.
        # FIX: future.result() is wrapped in try-except so one bad future
        #      cannot crash the collection loop.  (run_single_geometry also
        #      never raises, adding a second layer of protection.)
        # ------------------------------------------------------------------
        with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
            future_to_geometry = {
                executor.submit(run_single_geometry, run_id, geometry): geometry
                for run_id, geometry in enumerate(geometries, start=1)
            }
            for future in as_completed(future_to_geometry):
                geometry = future_to_geometry[future]
                try:
                    # FIX: try-except around future.result() as explicitly requested.
                    result = future.result()
                    # Separate successful vs failed results.
                    if _is_failed_result(result):
                        failure_info = {
                            "block_bytes": geometry.block_size_bytes,
                            "associativity": geometry.associativity,
                            "reason": _extract_failure_reason(result),
                        }
                        failed_runs.append(failure_info)
                        self.logger.warning(
                            "gem5 run recorded as failed: block=%dB assoc=%d | reason=%s",
                            geometry.block_size_bytes,
                            geometry.associativity,
                            failure_info["reason"],
                        )
                    results.append(result)  # include failed results in output
                except Exception as exc:
                    # FIX: If future itself raises (should not happen after our
                    #      changes, but kept as belt-and-suspenders), log and
                    #      continue rather than crashing.
                    label = f"block={geometry.block_size_bytes}B assoc={geometry.associativity}"
                    self.logger.error(
                        "[FAILED] %s | Future raised unexpectedly: %s", label, exc
                    )
                    failed_runs.append({
                        "block_bytes": geometry.block_size_bytes,
                        "associativity": geometry.associativity,
                        "reason": str(exc),
                    })

        # IMPROVEMENT: Report summary rather than crashing when some runs fail.
        successful = [r for r in results if not _is_failed_result(r)]
        failed_count = len(failed_runs)

        if not successful:
            # FIX: Even if ALL runs fail, we export whatever we have rather than
            #      crashing.  A warning is emitted; we only raise if there are
            #      zero results at all (nothing to export).
            self.logger.error(
                "ALL %d gem5 runs failed. Check per-run stderr.log files under %s.",
                len(geometries),
                runs_root,
            )
            if not results:
                raise RuntimeError(
                    f"All {len(geometries)} gem5 run(s) failed with no recoverable output. "
                    "Check per-run stderr.log files under the gem5 output directory."
                )
        elif failed_count:
            self.logger.warning(
                "Sweep completed with %d failed run(s) out of %d total. "
                "Failed configs are included in outputs with status=failed.",
                failed_count,
                len(geometries),
            )
        else:
            self.logger.info(
                "All %d gem5 runs completed successfully.", len(geometries)
            )

        elapsed = time.perf_counter() - start
        self.logger.info("gem5 sweep completed in %.3f sec", elapsed)

        snapshot: Dict[str, object] = asdict(self.config)
        snapshot["engine"] = "gem5"
        snapshot["gem5"] = asdict(self.gem5)
        snapshot["elapsed_seconds"] = elapsed
        # IMPROVEMENT: Store structured failure records (not just string list).
        snapshot["failed_runs"] = failed_runs
        snapshot["completed_runs"] = len(successful)
        snapshot["total_runs"] = len(geometries)
        snapshot["failed_count"] = failed_count

        # FIX: Return ALL results (including failed ones) so CSV/JSON is complete.
        return ExperimentBatch(config_snapshot=snapshot, results=results)

    # ------------------------------------------------------------------
    # gem5 invocation with corrected retry logic
    # ------------------------------------------------------------------

    def _invoke_gem5(self, geometry, run_dir: Path) -> float:
        """Invoke gem5, retrying up to _GEM5_MAX_ATTEMPTS times on failure.

        FIX: The original retry loop was broken.  `_max_retries = 1` meant only
             one attempt was made.  The while condition `attempt <= _max_retries`
             exited the loop before the retry `continue` could take effect,
             jumping straight to `raise RuntimeError`.

             The new implementation uses a simple `for attempt in range(...):`
             which is unambiguous and retries correctly.
        """
        command = [
            self.gem5.resolved_gem5_binary,
            f"--outdir={str(run_dir)}",
            self.gem5.gem5_config_script,
            f"--cmd={self.gem5.benchmark_binary}",
            f"--workload-name={self.gem5.workload_name}",
            f"--cpu-type={self.gem5.cpu_type}",
            f"--mem-size={self.gem5.mem_size}",
            f"--cache-size-kb={geometry.cache_size_kb}",
            f"--block-size-bytes={geometry.block_size_bytes}",
            f"--assoc={geometry.associativity}",
        ]

        if self.gem5.benchmark_args.strip():
            command.append(f"--options={self.gem5.benchmark_args}")

        if self.gem5.max_ticks > 0:
            command.append(f"--max-ticks={self.gem5.max_ticks}")

        label = f"block={geometry.block_size_bytes}B assoc={geometry.associativity}"
        # IMPROVEMENT: Log the exact command so runs are reproducible.
        self.logger.debug("[CMD] %s | command=%s", label, shlex.join(command))

        final_runtime = 0.0
        last_returncode = -1

        # FIX: Corrected retry loop — attempts 1..._GEM5_MAX_ATTEMPTS.
        for attempt in range(1, _GEM5_MAX_ATTEMPTS + 1):
            self.logger.info(
                "[ATTEMPT %d/%d] %s", attempt, _GEM5_MAX_ATTEMPTS, label
            )
            t0 = time.perf_counter()
            completed = subprocess.run(
                command, capture_output=True, text=True, check=False
            )
            final_runtime = time.perf_counter() - t0
            last_returncode = completed.returncode

            # Always persist logs for every attempt so debugging is easy.
            # IMPROVEMENT: Log file paths are emitted so users can navigate directly.
            stdout_path = run_dir / "stdout.log"
            stderr_path = run_dir / "stderr.log"
            cmd_path = run_dir / "command.txt"
            stdout_path.write_text(completed.stdout, encoding="utf-8")
            stderr_path.write_text(completed.stderr, encoding="utf-8")
            cmd_path.write_text(shlex.join(command) + "\n", encoding="utf-8")
            self.logger.debug(
                "[LOGS] stdout=%s | stderr=%s", stdout_path, stderr_path
            )

            if completed.returncode == 0:
                self.logger.info(
                    "[GEM5 OK] %s | attempt=%d | runtime=%.2fs",
                    label,
                    attempt,
                    final_runtime,
                )
                return final_runtime

            # Non-zero exit — check if stats.txt was still produced (gem5 can
            # panic after dumping stats; those results are still usable).
            stats_path = run_dir / "stats.txt"
            if stats_path.exists() and stats_path.stat().st_size > 0:
                self.logger.warning(
                    "[GEM5 NON-ZERO but stats OK] %s | rc=%d attempt=%d | "
                    "stats.txt present; continuing with partial stats.",
                    label,
                    completed.returncode,
                    attempt,
                )
                return final_runtime

            # FIX: Retry if attempts remain.
            if attempt < _GEM5_MAX_ATTEMPTS:
                stderr_snippet = _read_stderr_snippet(run_dir)
                self.logger.warning(
                    "[RETRY %d/%d] %s | rc=%d | stderr_hint=%s",
                    attempt,
                    _GEM5_MAX_ATTEMPTS,
                    label,
                    completed.returncode,
                    stderr_snippet,
                )
                # Brief back-off before retrying.
                time.sleep(0.5 * attempt)
                continue

        # All attempts exhausted — raise so run_single_geometry can mark failed.
        stderr_snippet = _read_stderr_snippet(run_dir)
        raise RuntimeError(
            f"gem5 execution failed for {label} after {_GEM5_MAX_ATTEMPTS} attempt(s) "
            f"(last rc={last_returncode}); stderr_hint={stderr_snippet}; "
            f"full log at {run_dir / 'stderr.log'}"
        )

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_all(self, batch: ExperimentBatch) -> dict[str, str]:
        out_cfg = self.config.output
        writer = ResultWriter(output_dir=out_cfg.output_dir)

        # FIX: Pass ALL results to CSV/JSON so failures are recorded in output.
        csv_path = writer.write_csv(out_cfg.csv_name, batch.results)
        json_path = writer.write_json(out_cfg.json_name, batch)
        summary_path = writer.write_summary(out_cfg.summary_name, batch.results)

        # IMPROVEMENT: Plots use only successful results to avoid divide-by-zero
        #              or misleading 0-rate bars from failed configurations.
        successful_results = [r for r in batch.results if not _is_failed_result(r)]
        if not successful_results:
            self.logger.warning(
                "No successful results available; skipping plot generation."
            )
            plot_paths: Dict[str, str] = {}
        else:
            plotter = Plotter(output_dir=out_cfg.output_dir)
            plot_paths = plotter.generate_all(
                successful_results,
                hit_vs_block_name=out_cfg.plot_hit_vs_block,
                miss_vs_block_name=out_cfg.plot_miss_vs_block,
                hit_vs_assoc_name=out_cfg.plot_hit_vs_assoc,
                miss_vs_assoc_name=out_cfg.plot_miss_vs_assoc,
                bar_hit_vs_block_name=out_cfg.bar_hit_vs_block,
                bar_miss_vs_block_name=out_cfg.bar_miss_vs_block,
                bar_hit_vs_assoc_name=out_cfg.bar_hit_vs_assoc,
                bar_miss_vs_assoc_name=out_cfg.bar_miss_vs_assoc,
            )

        outputs = {
            "csv": csv_path,
            "json": json_path,
            "summary": summary_path,
            "gem5_runs_root": str(
                Path(out_cfg.output_dir) / self.gem5.output_subdir
            ),
        }
        outputs.update(plot_paths)
        return outputs

    def run_and_export(self) -> Tuple[ExperimentBatch, Dict[str, str]]:
        batch = self.run_all()
        outputs = self.export_all(batch)
        return batch, outputs


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

# FIX: Sentinel note embedded in every failed result so callers can detect them
#      without needing a separate class.
_FAILED_SENTINEL = "status=failed"


def _make_failed_result(
    geometry,
    config: ExperimentConfig,
    gem5_cfg: Gem5RunConfig,
    run_dir: Path,
    reason: str,
) -> ExperimentResult:
    """Return a structured ExperimentResult that represents a failure.

    FIX: Instead of raising an exception (which would crash the future and
         potentially the whole pipeline), we encode the failure as a result
         with zero counters and a sentinel note so it passes through
         CSV/JSON export intact.
    """
    stderr_snippet = _read_stderr_snippet(run_dir)
    key = ExperimentKey(
        cache_size_kb=geometry.cache_size_kb,
        block_size_kb=geometry.block_size_kb,
        block_size_bytes=geometry.block_size_bytes,
        associativity=geometry.associativity,
        replacement_policy=config.replacement_policy,
        workload_name=gem5_cfg.workload_name,
    )
    # FIX: Zero counters for failed run — validate() would fail if called on
    #      these, so we skip validation intentionally.
    counters = CacheCounters(total_accesses=0, hits=0, misses=0)
    return ExperimentResult(
        key=key,
        counters=counters,
        runtime_seconds=0.0,
        notes=[
            _FAILED_SENTINEL,  # sentinel for filtering
            f"failure_reason={reason}",
            f"stderr_snippet={stderr_snippet}",
            f"stderr_log={run_dir / 'stderr.log'}",
            f"run_dir={run_dir}",
        ],
    )


def _is_failed_result(result: ExperimentResult) -> bool:
    """Return True if this result represents a failed gem5 run."""
    return any(_FAILED_SENTINEL in note for note in result.notes)


def _extract_failure_reason(result: ExperimentResult) -> str:
    """Extract the human-readable failure reason from a failed result's notes."""
    for note in result.notes:
        if note.startswith("failure_reason="):
            return note[len("failure_reason="):]
    return "unknown"


def _read_stderr_snippet(run_dir: Path, max_chars: int = 300) -> str:
    """Read the last `max_chars` characters of stderr.log for log messages.

    IMPROVEMENT: Embedding a snippet directly in log lines eliminates the need
                 to manually open files when diagnosing failures at the console.
    """
    stderr_path = run_dir / "stderr.log"
    try:
        text = stderr_path.read_text(encoding="utf-8", errors="replace")
        if not text:
            return "<empty>"
        # Return tail of file — the panic/error is almost always at the end.
        snippet = text.strip()[-max_chars:]
        return snippet.replace("\n", " | ")
    except FileNotFoundError:
        return "<stderr.log not found>"
    except Exception as exc:
        return f"<could not read stderr.log: {exc}>"
