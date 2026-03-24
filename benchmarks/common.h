/*
 * common.h — Shared definitions for cache associativity microbenchmarks
 *
 * Study: Effect of cache associativity and memory access patterns on
 *        pipeline performance (gem5 TimingSimpleCPU / O3CPU)
 *
 * Design rationale:
 *   L1_SIZE_BYTES  = 32 KB  (typical gem5 default)
 *   ARRAY_BYTES    = 256 KB (8× L1 — guarantees working set exceeds L1)
 *   ARRAY_SIZE     = 65536 ints (256 KB / 4 bytes)
 *   CACHE_LINE     = 64 bytes
 *   CACHE_SETS     = 128     (32 KB / (4-way × 64 B) = 128 sets)
 *
 * The CONFLICT_STRIDE places successive accesses in the same cache set,
 * maximally stressing associativity. For 32 KB / 64 B line / 128 sets:
 *   conflict stride = 128 sets × 64 B / 4 B = 2048 elements
 */

#ifndef COMMON_H
#define COMMON_H

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ---------------------------------------------------------------
 * Array / working-set sizing
 * --------------------------------------------------------------- */
#define L1_SIZE_BYTES    (32 * 1024)          /* 32 KB L1 D-cache          */
#define ARRAY_BYTES      (256 * 1024)         /* 256 KB working set (8×L1) */
#define ARRAY_SIZE       ((int)(ARRAY_BYTES / sizeof(int)))  /* 65536 elems */

/* ---------------------------------------------------------------
 * Cache geometry (adjust to match gem5 config)
 * --------------------------------------------------------------- */
#define CACHE_LINE_BYTES  64
#define ELEMS_PER_LINE    ((int)(CACHE_LINE_BYTES / sizeof(int)))  /* 16 */

/* Conflict stride: maps every access to the same cache set
 * Formula: (L1_SIZE / (assoc × line_bytes)) × (line_bytes / elem_bytes)
 * For 4-way 32 KB: 128 sets × 16 elems/line = 2048 elems              */
#define CONFLICT_STRIDE  (ARRAY_SIZE / ELEMS_PER_LINE)   /* 2048 */

/* ---------------------------------------------------------------
 * Iteration counts  — fixed, identical across all configurations
 *
 * WARMUP_PASSES:  fills TLB, primes branch predictor, thermal steady-state
 * COMPUTE_PASSES: region of interest — large enough for stat stability
 * PTR_ITERS:      pointer-chase iteration count (one load per iter)
 * --------------------------------------------------------------- */
#define WARMUP_PASSES    10
#define COMPUTE_PASSES   200
#define PTR_ITERS        (ARRAY_SIZE * 100)   /* 6 553 600 dependent loads */

/* ---------------------------------------------------------------
 * m5ops — gem5 magic instructions
 *
 * When compiled natively (outside gem5) these expand to nothing,
 * so the same source builds and runs on a host for functional checks.
 * In gem5, link against libm5 or use m5op.h from util/m5/.
 * --------------------------------------------------------------- */
#ifdef GEM5
#  include <gem5/m5ops.h>
#  define ROI_BEGIN()  do { m5_reset_stats(0, 0); } while (0)
#  define ROI_END()    do { m5_dump_stats(0, 0);  } while (0)
#else
/* Native build stubs — functional smoke-test only */
#  define ROI_BEGIN()  do { /* no-op outside gem5 */ } while (0)
#  define ROI_END()    do { /* no-op outside gem5 */ } while (0)
#endif

/* ---------------------------------------------------------------
 * Prevent the compiler from silently deleting load-only loops.
 * Accumulate into a global volatile sink; store at end of ROI.
 * --------------------------------------------------------------- */
volatile int  g_sink = 0;          /* result sink — prevents DCE          */
volatile long g_idx_sink = 0;      /* pointer-chase result sink            */

/* ---------------------------------------------------------------
 * Utility: print benchmark header for reproducibility logging
 * --------------------------------------------------------------- */
static inline void print_config(const char *bench_name, int stride)
{
    printf("=== %s ===\n", bench_name);
    printf("  array_size_bytes : %d\n",   ARRAY_BYTES);
    printf("  array_elems      : %d\n",   (int)ARRAY_SIZE);
    printf("  warmup_passes    : %d\n",   WARMUP_PASSES);
    printf("  compute_passes   : %d\n",   COMPUTE_PASSES);
    if (stride > 0)
        printf("  stride_elems     : %d  (%d bytes)\n",
               stride, (int)(stride * sizeof(int)));
    printf("  ROI              : m5_reset_stats -> m5_dump_stats\n\n");
}

#endif /* COMMON_H */
