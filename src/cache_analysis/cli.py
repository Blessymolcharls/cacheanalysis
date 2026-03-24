"""Command-line interface for cache simulation framework."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from typing import List

from .config import (
    DEFAULT_ASSOCIATIVITIES,
    DEFAULT_BLOCK_SIZES_BYTES,
    DEFAULT_CACHE_SIZE_KB,
    ExperimentConfig,
    Gem5RunConfig,
    OutputConfig,
)
from .gem5_runner import Gem5ExperimentRunner
from .logging_config import configure_logging, get_logger


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cache-analysis",
        description="gem5-only cache simulation and analysis framework.",
    )

    parser.add_argument("--cache-size-kb", type=int, default=DEFAULT_CACHE_SIZE_KB)
    parser.add_argument(
        "--block-sizes-bytes",
        "--block-sizes-kb",
        dest="block_sizes_bytes",
        nargs="+",
        type=int,
        default=DEFAULT_BLOCK_SIZES_BYTES,
        help="Space-separated list in BYTES, e.g. --block-sizes-bytes 16 32 64 128 256",
    )
    parser.add_argument(
        "--associativities",
        nargs="+",
        type=int,
        default=DEFAULT_ASSOCIATIVITIES,
        help="Space-separated list, e.g. --associativities 1 2 4 8",
    )

    parser.add_argument("--replacement-policy", default="LRU")
    parser.add_argument("--address-bits", type=int, default=32)

    parser.add_argument("--output-dir", default="results")
    parser.add_argument("--csv-name", default="cache_results.csv")
    parser.add_argument("--json-name", default="cache_results.json")
    parser.add_argument("--summary-name", default="summary.txt")

    parser.add_argument("--plot-hit-block", default="plot_block_vs_hit_rate.png")
    parser.add_argument("--plot-miss-block", default="plot_block_vs_miss_rate.png")
    parser.add_argument("--plot-hit-assoc", default="plot_assoc_vs_hit_rate.png")
    parser.add_argument("--plot-miss-assoc", default="plot_assoc_vs_miss_rate.png")

    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--log-file", default=None)

    parser.add_argument("--gem5-binary", default="")
    parser.add_argument("--gem5-config-script", default="scripts/gem5_cache_sweep.py")
    parser.add_argument("--gem5-benchmark", default="")
    parser.add_argument("--gem5-benchmark-args", default="")
    parser.add_argument("--gem5-workload-name", default="gem5_workload")
    parser.add_argument("--gem5-cpu-type", default="TimingSimpleCPU")
    parser.add_argument("--gem5-mem-size", default="2GB")
    parser.add_argument("--gem5-max-ticks", type=int, default=0)
    parser.add_argument("--gem5-stats-hits-key", default="")
    parser.add_argument("--gem5-stats-misses-key", default="")
    parser.add_argument("--gem5-output-subdir", default="gem5_runs")

    parser.add_argument(
        "--print-config",
        action="store_true",
        help="Print resolved configuration as JSON before run",
    )
    parser.add_argument(
        "--print-examples",
        action="store_true",
        help="Print a small sample of per-experiment output blocks",
    )

    return parser


def parse_config(argv: List[str] | None = None) -> ExperimentConfig:
    parser = build_parser()
    args = parser.parse_args(argv)

    output = OutputConfig(
        output_dir=args.output_dir,
        csv_name=args.csv_name,
        json_name=args.json_name,
        summary_name=args.summary_name,
        plot_hit_vs_block=args.plot_hit_block,
        plot_miss_vs_block=args.plot_miss_block,
        plot_hit_vs_assoc=args.plot_hit_assoc,
        plot_miss_vs_assoc=args.plot_miss_assoc,
    )

    config = ExperimentConfig(
        cache_size_kb=args.cache_size_kb,
        block_sizes_kb=list(args.block_sizes_bytes),
        associativities=list(args.associativities),
        replacement_policy=args.replacement_policy,
        address_space_bits=args.address_bits,
        output=output,
    )
    config.validate()

    configure_logging(level=args.log_level, log_file=args.log_file)
    logger = get_logger("cache-analysis")

    if args.print_config:
        print(json.dumps(asdict(config), indent=2))

    gem5_cfg = Gem5RunConfig(
        gem5_binary=args.gem5_binary,
        gem5_config_script=args.gem5_config_script,
        benchmark_binary=args.gem5_benchmark,
        benchmark_args=args.gem5_benchmark_args,
        workload_name=args.gem5_workload_name,
        cpu_type=args.gem5_cpu_type,
        mem_size=args.gem5_mem_size,
        max_ticks=args.gem5_max_ticks,
        stats_hits_key=args.gem5_stats_hits_key,
        stats_misses_key=args.gem5_stats_misses_key,
        output_subdir=args.gem5_output_subdir,
    )
    batch, outputs = Gem5ExperimentRunner(config, gem5_cfg).run_and_export()

    logger.info("Artifacts generated:")
    for key, path in outputs.items():
        logger.info("  %s: %s", key, path)

    if args.print_examples:
        print(_print_experiment_examples(batch.results, limit=6))

    return config


def main(argv: List[str] | None = None) -> int:
    parse_config(argv)
    return 0


def _print_experiment_examples(results, limit: int = 5) -> str:
    lines: List[str] = []
    count = 0
    for result in results:
        lines.extend(
            [
                f"Block Size: {result.key.block_size_bytes} B",
                f"Associativity: {result.key.associativity}-way",
                f"Total Accesses: {result.counters.total_accesses}",
                f"Hits: {result.counters.hits}",
                f"Misses: {result.counters.misses}",
                f"Hit Rate: {result.counters.hit_rate:.6f}",
                f"Miss Rate: {result.counters.miss_rate:.6f}",
                "",
            ]
        )
        count += 1
        if count >= limit:
            break
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
