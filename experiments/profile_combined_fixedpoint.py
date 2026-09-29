from __future__ import annotations

"""Measure whether Level 1 and dead-target pruning unlock each other.

One cycle is:

    recursive relative-region known-zero -> conservative dead affine targets

The experiment repeats cycles only while literal BF size strictly decreases.
It is a profiler, not the production entry point: the purpose is to determine
whether a second semantic cycle is justified before adding repeated passes to
the optimizer architecture.
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dead_affine_target_opt import optimize_dead_affine_targets_with_stats
from region_zero_opt import optimize_region_zero, strip_bf


def profile(path: Path, max_cycles: int) -> dict:
    original = strip_bf(path.read_text(encoding="ascii", errors="ignore"))
    current = original
    cycles = []

    for cycle in range(1, max_cycles + 1):
        before = current
        after_level1 = optimize_region_zero(before)
        after_dead, dead_stats = optimize_dead_affine_targets_with_stats(after_level1)
        cycles.append(
            {
                "cycle": cycle,
                "input_bytes": len(before),
                "after_level1_bytes": len(after_level1),
                "level1_saved_bytes": len(before) - len(after_level1),
                "after_dead_affine_bytes": len(after_dead),
                "dead_affine_saved_bytes": len(after_level1) - len(after_dead),
                "cycle_saved_bytes": len(before) - len(after_dead),
                "rewritten_producer_loops": dead_stats["rewritten_producer_loops"],
                "pruned_target_updates": dead_stats["pruned_target_updates"],
            }
        )
        current = after_dead
        if len(current) == len(before):
            break
        if len(current) > len(before):
            raise AssertionError((len(before), len(current)))
    else:
        raise AssertionError(f"did not converge within {max_cycles} cycles: {path}")

    return {
        "name": str(path),
        "original_bytes": len(original),
        "fixedpoint_bytes": len(current),
        "total_saved_bytes": len(original) - len(current),
        "cycles": cycles,
        "converged": len(cycles) < max_cycles or cycles[-1]["cycle_saved_bytes"] == 0,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--max-cycles", type=int, default=8)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rows = [profile(Path(name), args.max_cycles) for name in args.files]
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        for row in rows:
            productive = [c for c in row["cycles"] if c["cycle_saved_bytes"]]
            print(
                f"{row['name']}: {row['original_bytes']:,} -> {row['fixedpoint_bytes']:,} "
                f"saved={row['total_saved_bytes']:,} productive_cycles={len(productive)}"
            )


if __name__ == "__main__":
    main()
