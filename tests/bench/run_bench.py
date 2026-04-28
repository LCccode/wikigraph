#!/usr/bin/env python3
"""lcwiki N=2000 Performance Benchmark Runner.

Usage:
    python tests/bench/run_bench.py              # default n_docs=2000
    python tests/bench/run_bench.py --n 500      # quick validation run

Exit code:
    0  all benchmarks passed
    1  one or more benchmarks failed
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

# Make sure lcwiki is importable regardless of cwd
_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from tests.bench.gen_synthetic_kb import generate_synthetic_kb
from tests.bench.bench_fixes import (
    bench_fix_a_filename_index,
    bench_fix_b_concepts_writer,
    bench_fix_c_aliases_accuracy,
    bench_fix_d_leiden_timeout,
    bench_fix_e_tldr_cache,
)


def _fmt_result(r: dict) -> str:
    """Format one benchmark result as a single console line."""
    icon = "PASS" if r["passed"] else "FAIL"
    name = r["name"]

    # FIX-E has two sub-timings; special formatting
    if "_cold_elapsed" in r:
        cold_e = r["_cold_elapsed"]
        cold_t = r["_cold_threshold"]
        warm_e = r["_warm_elapsed"]
        warm_t = r["_warm_threshold"]
        cold_icon = "OK" if r["_cold_passed"] else "!!"
        warm_icon = "OK" if r["_warm_passed"] else "!!"
        return (
            f"[{icon}] {name}\n"
            f"       cold  {cold_e:.4f}s / threshold {cold_t}s  [{cold_icon}]\n"
            f"       warm  {warm_e:.4f}s / threshold {warm_t}s  [{warm_icon}]"
        )

    # FIX-C accuracy check (no timing threshold)
    if r["threshold"] == 0.0:
        return f"[{icon}] {name}  |  {r['notes']}"

    elapsed = r["elapsed"]
    threshold = r["threshold"]
    return f"[{icon}] {name:<45} {elapsed:.4f}s / threshold {threshold}s"


def main() -> int:
    parser = argparse.ArgumentParser(description="lcwiki performance benchmark")
    parser.add_argument(
        "--n",
        type=int,
        default=2000,
        help="Number of synthetic documents to generate (default: 2000)",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep synthetic KB after benchmark (default: delete)",
    )
    args = parser.parse_args()

    n_docs = args.n
    kb_root = _REPO_ROOT / "tests" / "bench" / ".synthetic_kb"

    # Clean up any previous run
    if kb_root.exists():
        shutil.rmtree(kb_root)

    sep = "=" * 60
    print(sep)
    print(f"lcwiki N={n_docs} Performance Benchmark")
    print(sep)

    # 1. Generate synthetic KB
    print(f"\nGenerating synthetic KB (n_docs={n_docs})...", flush=True)
    t_gen_start = time.perf_counter()
    generate_synthetic_kb(kb_root, n_docs=n_docs)
    t_gen = time.perf_counter() - t_gen_start
    print(f"KB generation: {t_gen:.2f}s\n")

    # 2. Run benchmarks
    results: list[dict] = []

    print("Running FIX-A: filename_index lookup...", flush=True)
    results.append(bench_fix_a_filename_index(kb_root))

    print("Running FIX-B: concepts reduce...", flush=True)
    results.append(bench_fix_b_concepts_writer(kb_root))

    print("Running FIX-C: aliases accuracy check...", flush=True)
    results.append(bench_fix_c_aliases_accuracy(kb_root))

    print("Running FIX-D: Leiden timeout fallback...", flush=True)
    results.append(bench_fix_d_leiden_timeout())

    print("Running FIX-E: tldr cache...", flush=True)
    results.append(bench_fix_e_tldr_cache(kb_root))

    # 3. Print summary
    print()
    print(sep)
    print(f"{'Results':^60}")
    print(sep)
    for r in results:
        print(_fmt_result(r))
        if r["notes"]:
            print(f"       notes: {r['notes']}")
    print()

    passed_count = sum(1 for r in results if r["passed"])
    total = len(results)
    print(f"{'PASSED' if passed_count == total else 'FAILED'}: {passed_count} / {total}")

    # 4. Cleanup
    if not args.keep and kb_root.exists():
        shutil.rmtree(kb_root)
        print(f"Synthetic KB cleaned up: {kb_root}")

    return 0 if passed_count == total else 1


if __name__ == "__main__":
    sys.exit(main())
