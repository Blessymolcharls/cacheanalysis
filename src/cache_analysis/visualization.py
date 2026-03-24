"""Visualization helpers for experiment trends."""

from __future__ import annotations

import os
from collections import defaultdict
from typing import Dict, Iterable, List, Tuple

import matplotlib.pyplot as plt
import numpy as np

from .models import ExperimentResult


class Plotter:
    """Generate plots for hit/miss rates vs block size and associativity."""

    def __init__(self, output_dir: str) -> None:
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def generate_all(
        self,
        results: Iterable[ExperimentResult],
        hit_vs_block_name: str,
        miss_vs_block_name: str,
        hit_vs_assoc_name: str,
        miss_vs_assoc_name: str,
        bar_hit_vs_block_name: str,
        bar_miss_vs_block_name: str,
        bar_hit_vs_assoc_name: str,
        bar_miss_vs_assoc_name: str,
    ) -> Dict[str, str]:
        items = list(results)
        outputs: Dict[str, str] = {}

        outputs["hit_vs_block"] = self.plot_block_metric(
            items,
            metric="hit",
            output_name=hit_vs_block_name,
            title="Block Size vs Hit Rate",
        )
        outputs["miss_vs_block"] = self.plot_block_metric(
            items,
            metric="miss",
            output_name=miss_vs_block_name,
            title="Block Size vs Miss Rate",
        )
        outputs["hit_vs_assoc"] = self.plot_assoc_metric(
            items,
            metric="hit",
            output_name=hit_vs_assoc_name,
            title="Associativity vs Hit Rate",
        )
        outputs["miss_vs_assoc"] = self.plot_assoc_metric(
            items,
            metric="miss",
            output_name=miss_vs_assoc_name,
            title="Associativity vs Miss Rate",
        )
        outputs["bar_hit_vs_block"] = self.plot_block_metric_bar(
            items,
            metric="hit",
            output_name=bar_hit_vs_block_name,
            title="Block Size vs Hit Rate (Bar)",
        )
        outputs["bar_miss_vs_block"] = self.plot_block_metric_bar(
            items,
            metric="miss",
            output_name=bar_miss_vs_block_name,
            title="Block Size vs Miss Rate (Bar)",
        )
        outputs["bar_hit_vs_assoc"] = self.plot_assoc_metric_bar(
            items,
            metric="hit",
            output_name=bar_hit_vs_assoc_name,
            title="Associativity vs Hit Rate (Bar)",
        )
        outputs["bar_miss_vs_assoc"] = self.plot_assoc_metric_bar(
            items,
            metric="miss",
            output_name=bar_miss_vs_assoc_name,
            title="Associativity vs Miss Rate (Bar)",
        )

        return outputs

    def plot_block_metric(
        self,
        results: List[ExperimentResult],
        metric: str,
        output_name: str,
        title: str,
    ) -> str:
        series = _group_by_assoc(results, metric)

        fig, ax = plt.subplots(figsize=(10, 6))
        for assoc, points in sorted(series.items()):
            xs, ys = _sorted_points(points)
            ax.plot(xs, ys, marker="o", label=f"{assoc}-way")

        ax.set_title(title)
        ax.set_xlabel("Block Size")
        ax.set_ylabel("Rate")
        ax.grid(True, linestyle="--", alpha=0.4)
        ax.legend()

        path = os.path.join(self.output_dir, output_name)
        fig.tight_layout()
        fig.savefig(path)
        plt.close(fig)
        return path

    def plot_assoc_metric(
        self,
        results: List[ExperimentResult],
        metric: str,
        output_name: str,
        title: str,
    ) -> str:
        series = _group_by_block(results, metric)

        fig, ax = plt.subplots(figsize=(10, 6))
        for block, points in sorted(series.items()):
            xs, ys = _sorted_points(points)
            ax.plot(xs, ys, marker="s", label=f"{_format_bytes(block)} block")

        ax.set_title(title)
        ax.set_xlabel("Associativity (ways)")
        ax.set_ylabel("Rate")
        ax.grid(True, linestyle=":", alpha=0.5)
        ax.legend()

        path = os.path.join(self.output_dir, output_name)
        fig.tight_layout()
        fig.savefig(path)
        plt.close(fig)
        return path

    def plot_block_metric_bar(
        self,
        results: List[ExperimentResult],
        metric: str,
        output_name: str,
        title: str,
    ) -> str:
        series = _group_by_assoc(results, metric)

        assoc_values = sorted(series.keys())
        x_categories = sorted({x for points in series.values() for x, _ in points})
        x = np.arange(len(x_categories))
        width = 0.18

        fig, ax = plt.subplots(figsize=(12, 6))
        for idx, assoc in enumerate(assoc_values):
            points = sorted(series[assoc], key=lambda item: item[0])
            y_by_x = {xv: yv for xv, yv in points}
            ys = [y_by_x.get(xv, 0.0) for xv in x_categories]
            shift = (idx - (len(assoc_values) - 1) / 2) * width
            ax.bar(x + shift, ys, width=width, label=f"{assoc}-way")

        ax.set_title(title)
        ax.set_xlabel("Block Size")
        ax.set_ylabel("Rate")
        ax.set_xticks(x)
        ax.set_xticklabels([_format_bytes(v) for v in x_categories])
        ax.grid(True, axis="y", linestyle="--", alpha=0.35)
        ax.legend()

        path = os.path.join(self.output_dir, output_name)
        fig.tight_layout()
        fig.savefig(path)
        plt.close(fig)
        return path

    def plot_assoc_metric_bar(
        self,
        results: List[ExperimentResult],
        metric: str,
        output_name: str,
        title: str,
    ) -> str:
        series = _group_by_block(results, metric)

        block_sizes = sorted(series.keys())
        x_categories = sorted({x for points in series.values() for x, _ in points})
        x = np.arange(len(x_categories))
        width = 0.16

        fig, ax = plt.subplots(figsize=(12, 6))
        for idx, block in enumerate(block_sizes):
            points = sorted(series[block], key=lambda item: item[0])
            y_by_x = {xv: yv for xv, yv in points}
            ys = [y_by_x.get(xv, 0.0) for xv in x_categories]
            shift = (idx - (len(block_sizes) - 1) / 2) * width
            ax.bar(x + shift, ys, width=width, label=f"{_format_bytes(block)} block")

        ax.set_title(title)
        ax.set_xlabel("Associativity (ways)")
        ax.set_ylabel("Rate")
        ax.set_xticks(x)
        ax.set_xticklabels([str(v) for v in x_categories])
        ax.grid(True, axis="y", linestyle=":", alpha=0.45)
        ax.legend()

        path = os.path.join(self.output_dir, output_name)
        fig.tight_layout()
        fig.savefig(path)
        plt.close(fig)
        return path


def _group_by_assoc(
    results: List[ExperimentResult],
    metric: str,
) -> Dict[int, List[Tuple[int, float]]]:
    grouped: Dict[int, List[Tuple[int, float]]] = defaultdict(list)
    for result in results:
        value = result.counters.hit_rate if metric == "hit" else result.counters.miss_rate
        grouped[result.key.associativity].append((result.key.block_size_bytes, value))
    return grouped


def _group_by_block(
    results: List[ExperimentResult],
    metric: str,
) -> Dict[int, List[Tuple[int, float]]]:
    grouped: Dict[int, List[Tuple[int, float]]] = defaultdict(list)
    for result in results:
        value = result.counters.hit_rate if metric == "hit" else result.counters.miss_rate
        # Group by normalized block size in bytes to keep plotting consistent
        grouped[result.key.block_size_bytes].append((result.key.associativity, value))
    return grouped


def _sorted_points(points: List[Tuple[int, float]]) -> Tuple[List[int], List[float]]:
    points = sorted(points, key=lambda item: item[0])
    return [x for x, _ in points], [y for _, y in points]


def _format_bytes(val: int) -> str:
    if val >= 1024 * 1024:
        return f"{val // (1024 * 1024)}MB"
    if val >= 1024:
        return f"{val // 1024}KB"
    return f"{val}B"
