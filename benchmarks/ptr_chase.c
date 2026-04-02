/*
 * ptr_chase.c — Pointer-Chasing Microbenchmark
 *
 * Pattern:  A linked-list traversal encoded as an index array.
 *           Each step: idx = A[idx]
 *           Each load depends on the result of the previous load —
 *           forming a true data-dependent load chain (no ILP).
 *
 * Purpose:  Isolate load-use latency.  Unlike sequential or stride
 *           access, pointer chasing cannot be prefetched by hardware
 *           because the next address is unknown until the current
 *           load completes.  This stresses associativity differently:
 *           conflict misses become full miss-latency stalls with no
 *           overlap.
 *
 * Chain construction modes (compile-time via -DCHAIN_MODE):
 * ──────────────────────────────────────────────────────────
 *   CHAIN_MODE 0 — SEQUENTIAL (default)
 *     A[0]=1, A[1]=2, ..., A[N-2]=N-1, A[N-1]=0
 *     Chain visits all elements in order; spatial locality is high.
 *     This mode establishes the pointer-chase base rate before
 *     randomisation.
 *
 *   CHAIN_MODE 1 — SHUFFLED
 *     Chain visits all elements in a pseudo-random permutation
 *     (Fisher-Yates on indices) seeded with a fixed seed, so the
 *     execution is fully deterministic across runs and configurations.
 *     Spatial locality is destroyed → every load misses in L1 (goes to DRAM).
 *     This is the "hostile" mode for cache associativity experiments.
 *
 * Build:
 *   gcc -O2 -std=c11 -DCHAIN_MODE=0 ptr_chase.c -o ptr_chase_seq
 *   gcc -O2 -std=c11 -DCHAIN_MODE=1 ptr_chase.c -o ptr_chase_shuffle
 *
 * Methodological guarantees
 * ─────────────────────────
 * ✓ Deterministic: fixed seed → identical chain across all configs
 * ✓ Working set 256 KB > 32 KB L1
 * ✓ Single access pattern: dependent-load chain
 * ✓ No branch inside the chase loop
 * ✓ Fixed iteration count (PTR_ITERS) across configurations
 * ✓ Chain spans full array (no short-cut aliasing)
 * ✓ volatile sink prevents DCE on the load chain
 * ✓ No malloc / I/O / function calls in compute loop
 */

#include "common.h"

/* ------------------------------------------------------------------
 * Default to sequential chain if CHAIN_MODE not specified
 * ------------------------------------------------------------------ */
#ifndef CHAIN_MODE
#define CHAIN_MODE 0
#endif

/* Fixed RNG seed for the shuffle — must never change between experiments */
#define SHUFFLE_SEED 42u

/* Array at file scope */
static int A[ARRAY_SIZE];

/* ------------------------------------------------------------------
 * build_sequential_chain()  [compiled only when CHAIN_MODE == 0]
 *
 *   A[0] = 1, A[1] = 2, ..., A[N-2] = N-1, A[N-1] = 0
 *
 * Starting from index 0, the traversal visits every element in order
 * and returns to 0 (ring).  All ARRAY_SIZE elements are reachable.
 * ------------------------------------------------------------------ */
#if CHAIN_MODE == 0
static void build_sequential_chain(void) {
  for (int i = 0; i < ARRAY_SIZE - 1; i++) {
    A[i] = i + 1;
  }
  A[ARRAY_SIZE - 1] = 0; /* close the ring */
}
#endif /* CHAIN_MODE == 0 */

/* ------------------------------------------------------------------
 * build_shuffled_chain()   [compiled only when CHAIN_MODE == 1]
 *
 * Constructs a uniformly-random permutation of [0, ARRAY_SIZE) using
 * the Fisher-Yates (Knuth) shuffle with a deterministic LCG RNG.
 * The permutation p[] maps position k → next element.
 *
 * The resulting A[] encodes: starting from index 0, the traversal
 * visits every element exactly once before returning to 0.
 *
 * Why LCG instead of rand()? rand() state is global and
 * implementation-defined. The LCG here is self-contained, portable,
 * and produces an identical sequence on every platform with every
 * compiler, guaranteeing determinism.
 *
 * LCG parameters: multiplier 1664525, addend 1013904223 (Numerical Recipes)
 * ------------------------------------------------------------------ */
#if CHAIN_MODE == 1
static uint32_t lcg_state;

static inline uint32_t lcg_next(void) {
  lcg_state = lcg_state * 1664525u + 1013904223u;
  return lcg_state;
}

static void build_shuffled_chain(void) {
  /* Step 1: build identity permutation.
   * NOTE: static to avoid a 256 KB stack allocation.
   * This is safe: build_shuffled_chain() is called once before ROI. */
  static int perm[ARRAY_SIZE];
  for (int i = 0; i < ARRAY_SIZE; i++) {
    perm[i] = i;
  }

  /* Step 2: Fisher-Yates shuffle with fixed-seed LCG */
  lcg_state = SHUFFLE_SEED;
  for (int i = ARRAY_SIZE - 1; i > 0; i--) {
    int j = (int)(lcg_next() % (uint32_t)(i + 1));
    /* swap perm[i] and perm[j] */
    int tmp = perm[i];
    perm[i] = perm[j];
    perm[j] = tmp;
  }

  /*
   * Step 3: Encode the permutation as a next-index array.
   * perm[] is a bijection on [0, N).  We build a cyclic chain:
   *   A[perm[k]] = perm[(k+1) % N]
   * This guarantees the chain visits every element exactly once.
   */
  for (int k = 0; k < ARRAY_SIZE - 1; k++) {
    A[perm[k]] = perm[k + 1];
  }
  A[perm[ARRAY_SIZE - 1]] = perm[0]; /* close the ring */
}
#endif /* CHAIN_MODE == 1 */

/* ------------------------------------------------------------------
 * verify_chain()
 *
 * Debug helper (not called in production): confirms every element is
 * reachable exactly once by traversing the full chain and counting.
 * ------------------------------------------------------------------ */
#ifdef DEBUG_CHAIN
static void verify_chain(void) {
  /* static: avoids 256 KB stack allocation (same reason as perm[] above) */
  static int visited[ARRAY_SIZE];
  memset(visited, 0, sizeof(visited));
  int idx = 0;
  for (int i = 0; i < ARRAY_SIZE; i++) {
    if (visited[idx]) {
      printf("ERROR: revisited index %d at step %d\n", idx, i);
      return;
    }
    visited[idx] = 1;
    idx = A[idx];
  }
  if (idx != 0) {
    printf("ERROR: chain did not close (ended at %d)\n", idx);
    return;
  }
  printf("Chain verified: all %d elements visited, ring closed.\n", ARRAY_SIZE);
}
#endif

int main(void) {
  /* ------------------------------------------------------------------
   * Phase 0 — BUILD CHAIN  (outside ROI, not timed)
   *
   * The chain is constructed once.  No malloc: A[] is a static array.
   * The build phase is deterministic and produces the same A[] content
   * for the same CHAIN_MODE and SHUFFLE_SEED, regardless of the cache
   * configuration under test.
   * ------------------------------------------------------------------ */
#if CHAIN_MODE == 0
  build_sequential_chain();
#else
  build_shuffled_chain();
#endif

#ifdef DEBUG_CHAIN
  verify_chain();
#endif

  /* ------------------------------------------------------------------
   * Phase 1 — WARM-UP
   *
   * Traverse the chain WARMUP_PASSES times.
   * WARMUP_PASSES × ARRAY_SIZE = 10 × 65536 = 655,360 dependent loads.
   * This brings the chain into steady-state cache residency before ROI.
   *
   * With no L2 in our setup, the warm-up establishes the steady-state
   * L1 miss rate that the ROI will then measure.
   *
   * The warm-up result is forced into g_idx_sink to prevent elimination.
   *
   * idx type is int: A[] is int[], so the subscript is always in
   * [0, ARRAY_SIZE) — well within int range.  Using int avoids a
   * spurious sign-extension instruction on RISC-V each iteration.
   * ------------------------------------------------------------------ */
  {
    int idx = 0;
    for (int pass = 0; pass < WARMUP_PASSES; pass++) {
      for (int i = 0; i < ARRAY_SIZE; i++) {
        idx = A[idx];
      }
    }
    g_idx_sink = idx;
  }

  /* ------------------------------------------------------------------
   * Phase 2 — REGION OF INTEREST (ROI)
   *
   * The chase loop:
   *   idx = A[idx]
   *
   * This is a single dependent load per iteration.  The entire
   * critical path is:
   *   addr_gen → L1 lookup → (miss → DRAM) → writeback to idx
   * (No L2 in this setup — every L1 miss goes directly to DRAM.)
   *
   * The loop has:
   *   • No branch inside the body (branch is the loop-control cmp/jne only)
   *   • No arithmetic other than the array index (unavoidable)
   *   • No independent loads that could hide latency
   *
   * CPI in this loop reflects the raw cache-miss latency directly.
   *
   * PTR_ITERS = ARRAY_SIZE × 100 = 6 553 600 iterations.
   * Each full ring traversal (ARRAY_SIZE iters) visits every element once.
   * 100 full traversals provides statistically stable counters.
   * ------------------------------------------------------------------ */
  ROI_BEGIN();

  {
    /*
     * idx must be declared volatile here.
     * Without volatile, a sufficiently aggressive compiler could
     * determine that the loop has no observable side effects and
     * eliminate it entirely, even at -O2.
     *
     * The volatile qualifier on the final write to g_idx_sink
     * is not sufficient because the compiler must first prove
     * idx's value matters — volatile on idx itself is the safest
     * and most portable guarantee.
     */
    volatile long idx = 0;
    for (long i = 0; i < PTR_ITERS; i++) {
      idx = A[idx];
    }
    g_idx_sink = idx;
  }

  ROI_END();

  printf("RESULT: pointer_chase mode=%s\n",
         (CHAIN_MODE == 0) ? "sequential" : "shuffled");

  return 0;
}
