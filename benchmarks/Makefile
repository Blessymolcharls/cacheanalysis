CC=gcc
CFLAGS=-O2 -march=x86-64 -g -std=c11
BIN_DIR=bin

.PHONY: all dirs clean ptr_chase_seq ptr_chase_shuffle

all: dirs $(BIN_DIR)/matrix_mul $(BIN_DIR)/ptr_chase_seq $(BIN_DIR)/ptr_chase_shuffle

dirs:
	mkdir -p $(BIN_DIR)

$(BIN_DIR)/matrix_mul: matrix_mul.c
	$(CC) $(CFLAGS) -o $@ matrix_mul.c -lm

# Pointer-chase: sequential chain (CHAIN_MODE=0) — spatial locality intact
$(BIN_DIR)/ptr_chase_seq: ptr_chase.c common.h
	$(CC) $(CFLAGS) -DCHAIN_MODE=0 -o $@ ptr_chase.c

# Pointer-chase: shuffled chain (CHAIN_MODE=1) — spatial locality destroyed
$(BIN_DIR)/ptr_chase_shuffle: ptr_chase.c common.h
	$(CC) $(CFLAGS) -DCHAIN_MODE=1 -o $@ ptr_chase.c

# Shorthand aliases
ptr_chase_seq: dirs $(BIN_DIR)/ptr_chase_seq
ptr_chase_shuffle: dirs $(BIN_DIR)/ptr_chase_shuffle

clean:
	rm -rf $(BIN_DIR)
