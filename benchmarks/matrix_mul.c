#include <errno.h>
#include <inttypes.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define ALIGNMENT 64ULL
#define DEFAULT_MATRIX_KB 1024ULL
#define DEFAULT_TILE 32ULL
#define DEFAULT_PASSES 3U
#define DEFAULT_STRIDE 4ULL
#define MIN_DIM 32U

typedef struct {
    uint64_t accesses;
    uint64_t reads;
    uint64_t writes;
    double checksum;
} PatternStats;

typedef struct {
    uint64_t total_accesses;
    uint64_t total_reads;
    uint64_t total_writes;
    double checksum;
} BenchmarkStats;

static volatile double global_sink = 0.0;

static uint64_t parse_u64_arg(const char *arg, uint64_t fallback) {
    char *end = NULL;
    unsigned long long value;
    if (arg == NULL || *arg == '\0') {
        return fallback;
    }
    errno = 0;
    value = strtoull(arg, &end, 10);
    if (errno != 0 || end == arg || *end != '\0' || value == 0ULL) {
        return fallback;
    }
    return (uint64_t)value;
}

static size_t align_up_size(size_t bytes, size_t alignment) {
    size_t rem = bytes % alignment;
    if (rem == 0U) {
        return bytes;
    }
    return bytes + (alignment - rem);
}

static double *alloc_aligned_matrix(size_t elements) {
    size_t bytes = elements * sizeof(double);
    size_t aligned = align_up_size(bytes, (size_t)ALIGNMENT);
    return (double *)aligned_alloc((size_t)ALIGNMENT, aligned);
}

static uint32_t derive_matrix_dim_from_kb(uint64_t matrix_kb) {
    double bytes = (double)(matrix_kb * 1024ULL);
    double elems = bytes / sizeof(double);
    double side = floor(sqrt(elems));
    uint32_t n;
    if (side < (double)MIN_DIM) {
        side = (double)MIN_DIM;
    }
    n = (uint32_t)side;
    return n;
}

static void zero_matrix(double *m, uint32_t n, PatternStats *stats) {
    uint64_t i;
    uint64_t total = (uint64_t)n * (uint64_t)n;
    for (i = 0ULL; i < total; ++i) {
        m[i] = 0.0;
        stats->writes += 1ULL;
        stats->accesses += 1ULL;
    }
}

static void init_matrix_a(double *a, uint32_t n, PatternStats *stats) {
    uint32_t i;
    for (i = 0U; i < n; ++i) {
        uint32_t j;
        for (j = 0U; j < n; ++j) {
            double v = (double)(i * 131U + j * 17U) / (double)(n + 1U);
            a[(uint64_t)i * n + j] = v;
            stats->writes += 1ULL;
            stats->accesses += 1ULL;
        }
    }
}

static void init_matrix_b(double *b, uint32_t n, PatternStats *stats) {
    uint32_t i;
    for (i = 0U; i < n; ++i) {
        uint32_t j;
        for (j = 0U; j < n; ++j) {
            double v = (double)((i ^ j) + 3U) / (double)(j + 1U);
            b[(uint64_t)i * n + j] = v;
            stats->writes += 1ULL;
            stats->accesses += 1ULL;
        }
    }
}

static void copy_matrix(double *dst, const double *src, uint32_t n, PatternStats *stats) {
    uint64_t i;
    uint64_t total = (uint64_t)n * (uint64_t)n;
    for (i = 0ULL; i < total; ++i) {
        dst[i] = src[i];
        stats->reads += 1ULL;
        stats->writes += 1ULL;
        stats->accesses += 2ULL;
    }
}

static double checksum_matrix(const double *m, uint32_t n, PatternStats *stats) {
    uint32_t i;
    double sum = 0.0;
    for (i = 0U; i < n; ++i) {
        uint32_t j;
        for (j = 0U; j < n; ++j) {
            double v = m[(uint64_t)i * n + j];
            sum += v;
            stats->reads += 1ULL;
            stats->accesses += 1ULL;
        }
    }
    return sum;
}

static double multiply_ijk(
    const double *a,
    const double *b,
    double *c,
    uint32_t n,
    uint32_t passes,
    PatternStats *stats
) {
    uint32_t p;
    double local = 0.0;
    for (p = 0U; p < passes; ++p) {
        uint32_t i;
        for (i = 0U; i < n; ++i) {
            uint32_t j;
            for (j = 0U; j < n; ++j) {
                uint32_t k;
                double sum = c[(uint64_t)i * n + j];
                stats->reads += 1ULL;
                stats->accesses += 1ULL;
                for (k = 0U; k < n; ++k) {
                    double av = a[(uint64_t)i * n + k];
                    double bv = b[(uint64_t)k * n + j];
                    sum += av * bv;
                    stats->reads += 2ULL;
                    stats->accesses += 2ULL;
                }
                c[(uint64_t)i * n + j] = sum;
                stats->writes += 1ULL;
                stats->accesses += 1ULL;
                local += sum * 1e-9;
            }
        }
    }
    return local;
}

static double multiply_ikj(
    const double *a,
    const double *b,
    double *c,
    uint32_t n,
    uint32_t passes,
    PatternStats *stats
) {
    uint32_t p;
    double local = 0.0;
    for (p = 0U; p < passes; ++p) {
        uint32_t i;
        for (i = 0U; i < n; ++i) {
            uint32_t k;
            for (k = 0U; k < n; ++k) {
                double aik = a[(uint64_t)i * n + k];
                uint32_t j;
                stats->reads += 1ULL;
                stats->accesses += 1ULL;
                for (j = 0U; j < n; ++j) {
                    uint64_t idx = (uint64_t)i * n + j;
                    double val = c[idx] + aik * b[(uint64_t)k * n + j];
                    c[idx] = val;
                    stats->reads += 2ULL;
                    stats->writes += 1ULL;
                    stats->accesses += 3ULL;
                    local += val * 1e-10;
                }
            }
        }
    }
    return local;
}

static double multiply_jki(
    const double *a,
    const double *b,
    double *c,
    uint32_t n,
    uint32_t passes,
    PatternStats *stats
) {
    uint32_t p;
    double local = 0.0;
    for (p = 0U; p < passes; ++p) {
        uint32_t j;
        for (j = 0U; j < n; ++j) {
            uint32_t k;
            for (k = 0U; k < n; ++k) {
                double bkj = b[(uint64_t)k * n + j];
                uint32_t i;
                stats->reads += 1ULL;
                stats->accesses += 1ULL;
                for (i = 0U; i < n; ++i) {
                    uint64_t idx = (uint64_t)i * n + j;
                    double val = c[idx] + a[(uint64_t)i * n + k] * bkj;
                    c[idx] = val;
                    stats->reads += 2ULL;
                    stats->writes += 1ULL;
                    stats->accesses += 3ULL;
                    local += val * 1e-11;
                }
            }
        }
    }
    return local;
}

static double multiply_blocked(
    const double *a,
    const double *b,
    double *c,
    uint32_t n,
    uint32_t tile,
    uint32_t passes,
    PatternStats *stats
) {
    uint32_t p;
    double local = 0.0;
    if (tile == 0U) {
        tile = 1U;
    }

    for (p = 0U; p < passes; ++p) {
        uint32_t ii;
        for (ii = 0U; ii < n; ii += tile) {
            uint32_t kk;
            uint32_t i_end = (ii + tile < n) ? (ii + tile) : n;
            for (kk = 0U; kk < n; kk += tile) {
                uint32_t jj;
                uint32_t k_end = (kk + tile < n) ? (kk + tile) : n;
                for (jj = 0U; jj < n; jj += tile) {
                    uint32_t j_end = (jj + tile < n) ? (jj + tile) : n;
                    uint32_t i;
                    for (i = ii; i < i_end; ++i) {
                        uint32_t k;
                        for (k = kk; k < k_end; ++k) {
                            double aik = a[(uint64_t)i * n + k];
                            uint32_t j;
                            stats->reads += 1ULL;
                            stats->accesses += 1ULL;
                            for (j = jj; j < j_end; ++j) {
                                uint64_t idx = (uint64_t)i * n + j;
                                double val = c[idx] + aik * b[(uint64_t)k * n + j];
                                c[idx] = val;
                                stats->reads += 2ULL;
                                stats->writes += 1ULL;
                                stats->accesses += 3ULL;
                                local += val * 1e-12;
                            }
                        }
                    }
                }
            }
        }
    }
    return local;
}

static double reverse_traversal_mix(
    double *a,
    double *b,
    double *c,
    uint32_t n,
    uint32_t passes,
    uint32_t stride,
    PatternStats *stats
) {
    uint32_t p;
    double local = 0.0;
    if (stride == 0U) {
        stride = 1U;
    }

    for (p = 0U; p < passes; ++p) {
        uint32_t i;
        for (i = n; i > 0U; --i) {
            uint32_t ii = i - 1U;
            uint32_t j = n;
            while (j > 0U) {
                uint32_t jj = j - 1U;
                uint64_t idx = (uint64_t)ii * n + jj;
                double av = a[idx];
                double bv = b[(uint64_t)jj * n + ii];
                double cv = c[idx];
                c[idx] = cv + av - bv + (double)p * 0.0001;
                stats->reads += 3ULL;
                stats->writes += 1ULL;
                stats->accesses += 4ULL;
                local += c[idx] * 1e-6;

                if (j <= stride) {
                    break;
                }
                j -= stride;
            }
        }
    }
    return local;
}

static double verify_with_reference(
    const double *a,
    const double *b,
    const double *c,
    uint32_t n,
    PatternStats *stats
) {
    uint32_t max_check = (n > 24U) ? 24U : n;
    uint32_t i;
    double err = 0.0;

    for (i = 0U; i < max_check; ++i) {
        uint32_t j;
        for (j = 0U; j < max_check; ++j) {
            uint32_t k;
            double ref = 0.0;
            for (k = 0U; k < max_check; ++k) {
                ref += a[(uint64_t)i * n + k] * b[(uint64_t)k * n + j];
                stats->reads += 2ULL;
                stats->accesses += 2ULL;
            }
            {
                double got = c[(uint64_t)i * n + j];
                double diff = fabs(got - ref);
                err += diff;
                stats->reads += 1ULL;
                stats->accesses += 1ULL;
            }
        }
    }
    return err;
}

static void print_pattern_result(const char *pattern, const PatternStats *stats, double checksum) {
    printf(
        "RESULT: pattern=%s, accesses=%" PRIu64 ", reads=%" PRIu64 ", writes=%" PRIu64 ", checksum=%.10e\n",
        pattern,
        stats->accesses,
        stats->reads,
        stats->writes,
        checksum
    );
}

static void accumulate_total(BenchmarkStats *total, const PatternStats *s, double checksum) {
    total->total_accesses += s->accesses;
    total->total_reads += s->reads;
    total->total_writes += s->writes;
    total->checksum += checksum;
}

static void print_usage(const char *prog) {
    printf("Usage: %s [matrix_kb] [tile] [passes] [stride]\n", prog);
    printf("Example: %s 1024 32 3 4\n", prog);
}

int main(int argc, char **argv) {
    uint64_t matrix_kb = DEFAULT_MATRIX_KB;
    uint64_t tile_u64 = DEFAULT_TILE;
    uint64_t passes_u64 = DEFAULT_PASSES;
    uint64_t stride_u64 = DEFAULT_STRIDE;
    uint32_t n;
    uint32_t tile;
    uint32_t passes;
    uint32_t stride;
    uint64_t elements;
    double *a;
    double *b;
    double *c;
    double *a_ref;
    double *b_ref;
    PatternStats init_stats = {0, 0, 0, 0.0};
    BenchmarkStats total = {0, 0, 0, 0.0};

    if (argc > 1 && (strcmp(argv[1], "-h") == 0 || strcmp(argv[1], "--help") == 0)) {
        print_usage(argv[0]);
        return 0;
    }

    if (argc > 1) {
        matrix_kb = parse_u64_arg(argv[1], DEFAULT_MATRIX_KB);
    }
    if (argc > 2) {
        tile_u64 = parse_u64_arg(argv[2], DEFAULT_TILE);
    }
    if (argc > 3) {
        passes_u64 = parse_u64_arg(argv[3], DEFAULT_PASSES);
    }
    if (argc > 4) {
        stride_u64 = parse_u64_arg(argv[4], DEFAULT_STRIDE);
    }

    if (tile_u64 > 4096ULL) {
        tile_u64 = 4096ULL;
    }
    if (passes_u64 > 1000ULL) {
        passes_u64 = 1000ULL;
    }
    if (stride_u64 > 4096ULL) {
        stride_u64 = 4096ULL;
    }

    n = derive_matrix_dim_from_kb(matrix_kb);
    tile = (uint32_t)tile_u64;
    passes = (uint32_t)passes_u64;
    stride = (uint32_t)stride_u64;
    elements = (uint64_t)n * (uint64_t)n;

    a = alloc_aligned_matrix((size_t)elements);
    b = alloc_aligned_matrix((size_t)elements);
    c = alloc_aligned_matrix((size_t)elements);
    a_ref = alloc_aligned_matrix((size_t)elements);
    b_ref = alloc_aligned_matrix((size_t)elements);

    if (a == NULL || b == NULL || c == NULL || a_ref == NULL || b_ref == NULL) {
        fprintf(stderr, "allocation failed for matrix dimension %u\n", n);
        free(a);
        free(b);
        free(c);
        free(a_ref);
        free(b_ref);
        return 1;
    }

    init_matrix_a(a, n, &init_stats);
    init_matrix_b(b, n, &init_stats);
    copy_matrix(a_ref, a, n, &init_stats);
    copy_matrix(b_ref, b, n, &init_stats);
    zero_matrix(c, n, &init_stats);
    print_pattern_result("init", &init_stats, (double)init_stats.accesses);
    accumulate_total(&total, &init_stats, (double)init_stats.accesses);

    {
        PatternStats s = {0, 0, 0, 0.0};
        double cs = multiply_ijk(a, b, c, n, passes, &s);
        print_pattern_result("matmul_ijk", &s, cs);
        accumulate_total(&total, &s, cs);
    }

    {
        PatternStats s = {0, 0, 0, 0.0};
        double cs = multiply_ikj(a, b, c, n, passes, &s);
        print_pattern_result("matmul_ikj", &s, cs);
        accumulate_total(&total, &s, cs);
    }

    {
        PatternStats s = {0, 0, 0, 0.0};
        double cs = multiply_jki(a, b, c, n, passes, &s);
        print_pattern_result("matmul_jki", &s, cs);
        accumulate_total(&total, &s, cs);
    }

    {
        PatternStats s = {0, 0, 0, 0.0};
        double cs = multiply_blocked(a, b, c, n, tile, passes, &s);
        print_pattern_result("matmul_blocked", &s, cs);
        accumulate_total(&total, &s, cs);
    }

    {
        PatternStats s = {0, 0, 0, 0.0};
        double cs = reverse_traversal_mix(a, b, c, n, passes, stride, &s);
        print_pattern_result("reverse_strided_mix", &s, cs);
        accumulate_total(&total, &s, cs);
    }

    {
        PatternStats s_checksum = {0, 0, 0, 0.0};
        PatternStats s_verify = {0, 0, 0, 0.0};
        double cs = checksum_matrix(c, n, &s_checksum);
        double err = verify_with_reference(a_ref, b_ref, c, n, &s_verify);
        print_pattern_result("checksum", &s_checksum, cs);
        print_pattern_result("verify", &s_verify, err);
        accumulate_total(&total, &s_checksum, cs);
        accumulate_total(&total, &s_verify, err);
        global_sink += cs + err;
    }

    global_sink += c[(uint64_t)(n / 2U) * n + (n / 2U)];

    printf(
        "RESULT: pattern=summary, matrix_kb=%" PRIu64 ", N=%u, tile=%u, passes=%u, stride=%u, accesses=%" PRIu64 ", reads=%" PRIu64 ", writes=%" PRIu64 ", checksum=%.10e\n",
        matrix_kb,
        n,
        tile,
        passes,
        stride,
        total.total_accesses,
        total.total_reads,
        total.total_writes,
        total.checksum + global_sink
    );

    free(a);
    free(b);
    free(c);
    free(a_ref);
    free(b_ref);
    return 0;
}
