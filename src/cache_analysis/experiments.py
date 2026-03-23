"""Experiment automation over cache geometry and workloads."""

from __future__ import annotations

import os
import time
from dataclasses import asdict
from typing import Iterable, List, Sequence

from .config import CacheGeometry, ExperimentConfig
from .logging_config import get_logger
from .models import ExperimentBatch, ExperimentResult
from .reporting import ResultWriter
from .simulator import CacheSimulator
from .visualization import Plotter
from .workloads import MatrixWorkload, RandomWorkload, SequentialWorkload, WorkloadGenerator


class ExperimentRunner:
    """Runs all requested cache experiments and exports artifacts."""

    def __init__(self, config: ExperimentConfig) -> None:
        self.config = config
        self.config.validate()
        self.logger = get_logger(self.__class__.__name__)

    def build_workloads(self) -> Sequence[WorkloadGenerator]:
        wcfg = self.config.workloads
        return [
            SequentialWorkload(
                total_accesses=wcfg.sequential_accesses,
                stride_bytes=wcfg.sequential_stride,
            ),
            RandomWorkload(
                total_accesses=wcfg.random_accesses,
                address_limit_bytes=wcfg.random_address_limit_bytes,
                seed=wcfg.random_seed,
            ),
            MatrixWorkload(
                dimension=wcfg.matrix_dimension,
                element_size_bytes=wcfg.matrix_element_size_bytes,
            ),
        ]

    def run_all(self) -> ExperimentBatch:
        self.logger.info("Starting full experiment sweep")
        start = time.perf_counter()

        workloads = self.build_workloads()
        geometries = self.config.all_geometries()
        results: List[ExperimentResult] = []

        total_runs = len(workloads) * len(geometries)
        run_id = 0

        for workload in workloads:
            trace = list(workload.generate())
            self.logger.info(
                "Prepared workload '%s' with %d accesses",
                workload.name,
                len(trace),
            )

            for geometry in geometries:
                run_id += 1
                self.logger.info(
                    "Run %d/%d: workload=%s block=%dKB assoc=%d",
                    run_id,
                    total_runs,
                    workload.name,
                    geometry.block_size_kb,
                    geometry.associativity,
                )

                simulator = CacheSimulator(
                    geometry=geometry,
                    replacement_policy=self.config.replacement_policy,
                )
                result = simulator.run(trace, workload_name=workload.name)
                results.append(result)

        elapsed = time.perf_counter() - start
        self.logger.info("Experiment sweep completed in %.3f sec", elapsed)

        snapshot = asdict(self.config)
        snapshot["elapsed_seconds"] = elapsed

        batch = ExperimentBatch(config_snapshot=snapshot, results=results)
        return batch

    def export_all(self, batch: ExperimentBatch) -> dict[str, str]:
        out_cfg = self.config.output
        writer = ResultWriter(output_dir=out_cfg.output_dir)

        csv_path = writer.write_csv(out_cfg.csv_name, batch.results)
        json_path = writer.write_json(out_cfg.json_name, batch)
        summary_path = writer.write_summary(out_cfg.summary_name, batch.results)

        plotter = Plotter(output_dir=out_cfg.output_dir)
        plot_paths = plotter.generate_all(
            batch.results,
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
        }
        outputs.update(plot_paths)

        self.logger.info("Exported artifacts to %s", os.path.abspath(out_cfg.output_dir))
        return outputs

    def run_and_export(self) -> tuple[ExperimentBatch, dict[str, str]]:
        batch = self.run_all()
        outputs = self.export_all(batch)
        return batch, outputs


def print_experiment_examples(results: Iterable[ExperimentResult], limit: int = 5) -> str:
    """Build example output snippet requested in assignment format."""

    lines: List[str] = []
    count = 0
    for result in results:
        lines.extend(
            [
                f"Block Size: {result.key.block_size_kb} KB",
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
