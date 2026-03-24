# Cache Analysis Framework (gem5-only)

This project uses gem5 exclusively for cache simulation.

The framework automates cache parameter sweeps, parses `stats.txt`, and exports
CSV/JSON reports with plots.

## What It Runs

- Single backend: gem5 executable
- Sweep dimensions:
	- Cache size (KB)
	- Block size (KB)
	- Associativity (ways)
- Replacement policy target: LRU (configured in gem5 classic cache setup)

## Key Metrics

For every run, the framework extracts from gem5 stats:

- hits
- misses
- total accesses (`hits + misses`)
- hit rate (`hits / total_accesses`)
- miss rate (`misses / total_accesses`)

## Project Structure

```
CacheAnalysis/
	main.py
	requirements.txt
	README.md
	scripts/
		gem5_cache_sweep.py
	src/cache_analysis/
		__init__.py
		__main__.py
		cli.py
		config.py
		gem5_runner.py
		gem5_stats.py
		logging_config.py
		models.py
		reporting.py
		visualization.py
	results/
```

## Installation

From repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## gem5 Requirement

gem5 must be installed.

The CLI will fail fast if gem5 is unavailable and prints a clear error:

`gem5 binary not found. Install gem5 and either add gem5.opt to PATH or pass --gem5-binary /path/to/gem5.opt.`

## Usage

Run from repository root:

```bash
PYTHONPATH=src python3 main.py \
	--gem5-binary /path/to/gem5/build/X86/gem5.opt \
	--gem5-config-script scripts/gem5_cache_sweep.py \
	--gem5-benchmark /path/to/benchmark_binary \
	--gem5-workload-name benchmark_run \
	--cache-size-kb 2048 \
	--block-sizes-kb 16 32 64 128 256 \
	--associativities 1 2 4 8 \
	--output-dir results/full
```

Optional arguments:

```bash
	--gem5-benchmark-args "arg1 arg2" \
	--gem5-cpu-type TimingSimpleCPU \
	--gem5-mem-size 2GB \
	--gem5-max-ticks 0 \
	--gem5-stats-hits-key "system.cpu.dcache.overallHits::total" \
	--gem5-stats-misses-key "system.cpu.dcache.overallMisses::total" \
	--print-config --print-examples
```

## Parameter Passing To gem5 Script

Each run passes these required parameters into `scripts/gem5_cache_sweep.py`:

- `--cache-size-kb`
- `--block-size-kb`
- `--assoc`
- `--workload-name`
- benchmark command via `--cmd` and `--options`

The gem5 script converts block size KB to bytes for `system.cache_line_size`.

## Outputs

In the chosen output directory:

- `cache_results.csv`
- `cache_results.json`
- `summary.txt`
- `plot_block_vs_hit_rate.png`
- `plot_block_vs_miss_rate.png`
- `plot_assoc_vs_hit_rate.png`
- `plot_assoc_vs_miss_rate.png`
- `bar_block_vs_hit_rate.png`
- `bar_block_vs_miss_rate.png`
- `bar_assoc_vs_hit_rate.png`
- `bar_assoc_vs_miss_rate.png`

Per-run gem5 artifacts are stored under:

- `<output_dir>/<gem5_output_subdir>/b<block_kb>KB_a<assoc>/`

Each run directory contains `stats.txt`, `stdout.log`, `stderr.log`, and `command.txt`.
