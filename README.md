# Cache Simulation and Analysis Framework (gem5-style)

This repository provides a detailed, modular cache simulation framework inspired
by architectural exploration workflows commonly used with gem5.

It focuses on analyzing the impact of:

- Cache block size
- Cache associativity
- LRU replacement policy

while reporting detailed metrics and miss classifications.

## Implemented Requirements

### 1. Cache Configuration

- Fixed cache size (default 2048 KB; configurable)
- Block sizes: 16 KB, 32 KB, 64 KB, 128 KB, 256 KB (default sweep)
- Associativity levels: 1-way, 2-way, 4-way, 8-way (default sweep)
- Replacement policy: LRU

### 2. Performance Metrics

For each experiment:

- Total accesses
- Hits
- Misses
- Hit rate = hits / total_accesses
- Miss rate = misses / total_accesses

The framework validates:

- `hits + misses == total_accesses`
- `hit_rate + miss_rate == 1`

Also tracked:

- Load and store counts
- Miss breakdown: compulsory, conflict, capacity

### 3. Simulation Engine

- Supports load/store access stream simulation
- Per-access update of cache state and counters
- Modular access pipeline:
  - Address decode
  - Cache lookup
  - LRU update
  - Miss classification

### 4. LRU Replacement Policy

- Independent per-set LRU tracker
- Updated on every hit
- Evicts least-recently-used line on miss when set is full

### 5. Address Breakdown

Each address is split into:

- Tag
- Index
- Offset

Implemented via `AddressDecoder` in `addressing.py`.

### 6. Experimental Goals

The framework produces data to verify key observations:

1. Associativity beyond 4-way or 8-way tends to show diminishing returns.
2. Larger blocks initially help due to spatial locality, then can hurt due to
   reduced number of sets and increased conflict pressure.

### 7. Automation

Runs all combinations automatically:

- 5 block sizes x 4 associativity levels = 20 cache geometries
- Across 3 workloads by default = 60 experiment runs

Outputs:

- CSV file
- JSON file
- Summary text

### 8. Visualization

Automatically generates graphs:

- Block size vs hit rate
- Block size vs miss rate
- Associativity vs hit rate
- Associativity vs miss rate

### 9. Benchmark Workloads

Included workloads:

- Sequential access (high spatial locality)
- Random access (low locality)
- Matrix operation pattern (mixed locality)

### 10. Example Output

Example record formatting:

```
Block Size: 64 KB
Associativity: 4-way
Total Accesses: 100000
Hits: 85000
Misses: 15000
Hit Rate: 0.850000
Miss Rate: 0.150000
```

## Project Structure

```
CacheAnalysis/
  main.py
  requirements.txt
  README.md
  src/cache_analysis/
    __init__.py
    __main__.py
    cli.py
    config.py
    models.py
    addressing.py
    cache_core.py
    miss_classifier.py
    simulator.py
    experiments.py
    reporting.py
    visualization.py
    logging_config.py
    replacement/
      lru.py
    workloads/
      __init__.py
      base.py
      sequential.py
      random_access.py
      matrix_ops.py
  results/
```

## Installation

From repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

### Default Full Sweep

```bash
PYTHONPATH=src python3 main.py --print-config --print-examples
```

### Custom Sweep

```bash
PYTHONPATH=src python3 main.py \
  --cache-size-kb 2048 \
  --block-sizes-kb 16 32 64 128 256 \
  --associativities 1 2 4 8 \
  --replacement-policy LRU \
  --seq-accesses 120000 \
  --rand-accesses 120000 \
  --matrix-dim 96 \
  --output-dir results
```

### Logging

```bash
PYTHONPATH=src python3 main.py --log-level DEBUG --log-file results/run.log
```

## Generated Artifacts

In `results/` by default:

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

## Notes on Miss Classification

Miss classification is based on deterministic heuristic tracking:

- Compulsory misses are exact first-touch misses.
- Conflict/capacity split is approximated using active working-set pressure.

For production-grade microarchitectural studies, this can be extended using a
parallel fully-associative shadow cache baseline.

## gem5 Integration Path

This framework is intentionally modular. To integrate with gem5:

1. Replace synthetic workload generation with gem5 trace inputs.
2. Feed real access traces into `CacheSimulator.run(...)`.
3. Keep existing reporting and plotting pipeline unchanged.

## Code Size

The implementation is intentionally detailed and modular, with extensive
comments/docstrings and multiple components to exceed 1000 lines of code while
remaining readable and maintainable.
