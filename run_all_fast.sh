#!/bin/bash

GEM5=../gem5/build/X86/gem5.opt
MAIN=main.py

echo "========================================"
echo "Running ALL experiments"
echo "CPU: TimingSimpleCPU"
echo "========================================"

# Use ticks instead of maxinsts (SUPPORTED)
MAXTICKS="--gem5-max-ticks=1000000000"

# -------- MATRIX MULT --------

echo "Running matrix_mul_ijk..."
python3 $MAIN \
  --gem5-binary=$GEM5 \
  --gem5-benchmark=benchmarks/bin/matrix_mul \
  --gem5-benchmark-args='128 ijk' \
  --gem5-workload-name=matrix_mul_ijk \
  --gem5-cpu-type=TimingSimpleCPU \
  --gem5-output-subdir=gem5_runs_matrix_mul_ijk \
  --output-dir=results/matrix_mul_ijk \
  $MAXTICKS

echo "Running matrix_mul_ikj..."
python3 $MAIN \
  --gem5-binary=$GEM5 \
  --gem5-benchmark=benchmarks/bin/matrix_mul \
  --gem5-benchmark-args='128 ikj' \
  --gem5-workload-name=matrix_mul_ikj \
  --gem5-cpu-type=TimingSimpleCPU \
  --gem5-output-subdir=gem5_runs_matrix_mul_ikj \
  --output-dir=results/matrix_mul_ikj \
  $MAXTICKS

echo "Running matrix_mul_blocked..."
python3 $MAIN \
  --gem5-binary=$GEM5 \
  --gem5-benchmark=benchmarks/bin/matrix_mul \
  --gem5-benchmark-args='128 blocked' \
  --gem5-workload-name=matrix_mul_blocked \
  --gem5-cpu-type=TimingSimpleCPU \
  --gem5-output-subdir=gem5_runs_matrix_mul_blocked \
  --output-dir=results/matrix_mul_blocked \
  $MAXTICKS

# -------- POINTER CHASE --------

echo "Running ptr_chase_seq..."
python3 $MAIN \
  --gem5-binary=$GEM5 \
  --gem5-benchmark=benchmarks/bin/ptr_chase_seq \
  --gem5-workload-name=ptr_chase_seq \
  --gem5-cpu-type=TimingSimpleCPU \
  --gem5-output-subdir=gem5_runs_ptr_chase_seq \
  --output-dir=results/ptr_chase_seq \
  $MAXTICKS

echo "Running ptr_chase_shuffle..."
python3 $MAIN \
  --gem5-binary=$GEM5 \
  --gem5-benchmark=benchmarks/bin/ptr_chase_shuffle \
  --gem5-workload-name=ptr_chase_shuffle \
  --gem5-cpu-type=TimingSimpleCPU \
  --gem5-output-subdir=gem5_runs_ptr_chase_shuffle \
  --output-dir=results/ptr_chase_shuffle \
  $MAXTICKS

echo "========================================"
echo "All simulations complete"
echo "========================================"