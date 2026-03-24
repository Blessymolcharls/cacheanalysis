"""Minimal gem5 configuration for cache block-size/associativity sweeps.

Usage example:
  build/X86/gem5.opt --outdir=run_out scripts/gem5_cache_sweep.py \
    --cmd=/path/to/binary --options="arg1 arg2" \
    --cpu-type=TimingSimpleCPU --mem-size=2GB \
        --cache-size-kb=32 --block-size-bytes=64 --assoc=4
"""

from __future__ import annotations

import argparse
import shlex

import m5
from m5.objects import AddrRange, Cache, DDR3_1600_8x8, MemCtrl, Process, Root, SEWorkload, SrcClockDomain, System, SystemXBar, VoltageDomain


class L1DCache(Cache):
    # Avoid hard-coded associativity at class level; set per-instance below.
    tag_latency = 2
    data_latency = 2
    response_latency = 2
    mshrs = 16
    tgts_per_mshr = 20
    writeback_clean = True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="gem5 cache sweep config")
    parser.add_argument("--cmd", required=True)
    parser.add_argument("--workload-name", default="gem5_workload")
    parser.add_argument("--options", default="")
    parser.add_argument("--cpu-type", default="TimingSimpleCPU")
    parser.add_argument("--mem-size", default="2GB")
    parser.add_argument("--cache-size-kb", type=int, required=True)
    parser.add_argument("--block-size-bytes", type=int, required=True,
                        help="Block size in BYTES.")
    parser.add_argument("--assoc", type=int, required=True)
    parser.add_argument("--max-ticks", type=int, default=0)
    return parser


def create_cpu(cpu_type: str):
    cpu_map = {
        "TimingSimpleCPU": m5.objects.TimingSimpleCPU,
        "AtomicSimpleCPU": m5.objects.AtomicSimpleCPU,
        "MinorCPU": m5.objects.MinorCPU,
    }
    try:
        return cpu_map[cpu_type]()
    except KeyError as exc:
        raise ValueError(f"Unsupported cpu type: {cpu_type}") from exc


def main() -> None:
    args = build_parser().parse_args()

    system = System()
    system.clk_domain = SrcClockDomain()
    system.clk_domain.clock = "1GHz"
    system.clk_domain.voltage_domain = VoltageDomain()

    system.mem_mode = "atomic" if args.cpu_type == "AtomicSimpleCPU" else "timing"
    system.mem_ranges = [AddrRange(args.mem_size)]
    block_bytes = args.block_size_bytes

    system.cache_line_size = block_bytes

    system.cpu = create_cpu(args.cpu_type)
    system.cpu.createInterruptController()

    system.membus = SystemXBar()

    # Instantiate the L1 data cache with per-instance size and associativity
    cache_size_str = f"{args.cache_size_kb}kB"
    # Provide size and assoc at construction time to avoid accidental overrides
    l1d = L1DCache(size=cache_size_str, assoc=args.assoc)
    system.dcache = l1d

    # Runtime validation prints to ensure associativity/block size are applied
    print("[gem5-config] CONFIG ARGS:")
    print(f"[gem5-config] cmd={args.cmd}")
    print(f"[gem5-config] workload_name={args.workload_name}")
    print(f"[gem5-config] cpu_type={args.cpu_type}")
    print(f"[gem5-config] cache_size_kb={args.cache_size_kb}")
    print(f"[gem5-config] block_size_bytes={args.block_size_bytes}")
    print(f"[gem5-config] assoc_arg={args.assoc}")
    print(f"[gem5-config] Cache Size (instance): {l1d.size}")
    print(f"[gem5-config] Associativity (instance): {getattr(l1d, 'assoc', None)}")
    print(f"[gem5-config] Block Size (bytes/system): {block_bytes}")

    # Connect CPU and L1D: CPU.dcache_port <-> L1D.cpu_side ; L1D.mem_side <-> membus
    if hasattr(system.cpu, "icache_port"):
        system.cpu.icache_port = system.membus.cpu_side_ports
    l1d.cpu_side = system.cpu.dcache_port
    # Connect the cache memory side to the membus CPU-side ports (correct wiring)
    # In gem5 the cache `mem_side` connects to the bus `cpu_side_ports`.
    l1d.mem_side = system.membus.cpu_side_ports

    system.mem_ctrl = MemCtrl()
    system.mem_ctrl.dram = DDR3_1600_8x8()
    system.mem_ctrl.dram.range = system.mem_ranges[0]
    system.mem_ctrl.port = system.membus.mem_side_ports

    system.system_port = system.membus.cpu_side_ports

    # X86 SE mode requires explicit interrupt wiring.
    if hasattr(system.cpu, "interrupts") and system.cpu.interrupts:
        system.cpu.interrupts[0].pio = system.membus.mem_side_ports
        system.cpu.interrupts[0].int_requestor = system.membus.cpu_side_ports
        system.cpu.interrupts[0].int_responder = system.membus.mem_side_ports

    process = Process()
    cmd_argv = [args.cmd]
    if args.options:
        # Assign once so gem5 Param conversion wraps each entry correctly.
        cmd_argv.extend(shlex.split(args.options))
    process.cmd = cmd_argv

    system.workload = SEWorkload.init_compatible(args.cmd)
    system.cpu.workload = process
    system.cpu.createThreads()

    root = Root(full_system=False, system=system)
    m5.instantiate()

    if args.max_ticks > 0:
        exit_event = m5.simulate(args.max_ticks)
    else:
        exit_event = m5.simulate()

    m5.stats.dump()
    m5.stats.reset()

    print(f"Exiting @ tick {m5.curTick()} because {exit_event.getCause()}")
main()
