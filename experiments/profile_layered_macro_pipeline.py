from __future__ import annotations

"""Measure composition of proven local semantic passes with macro compression.

Pipeline under test:

    compiler-optimized BF
      -> recursive relative-region known-zero
      -> conservative dead-affine target pruning
      -> repeat while literal size strictly decreases
      -> relational semantic macro grammar
      -> optional tiny extended LZSS
      -> verified BF-native payload channel

The fixed-point loop is only a research harness.  Production integration should
use fused dataflow/worklists rather than repeated whole-program rescans.
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dead_affine_target_opt import optimize_dead_affine_targets_with_stats
from profile_relational_macro_grammar import profile_text as profile_relational_text
from region_zero_opt import optimize_region_zero, strip_bf


def local_semantic_fixedpoint(text: str, max_cycles: int = 8) -> tuple[str, list[dict[str, int]]]:
    current = strip_bf(text)
    cycles: list[dict[str, int]] = []
    for cycle in range(1, max_cycles + 1):
        before = current
        after_zero = optimize_region_zero(before)
        after_dead, stats = optimize_dead_affine_targets_with_stats(after_zero)
        if len(after_dead) > len(before):
            raise AssertionError((len(before), len(after_dead)))
        cycles.append({
            "cycle": cycle,
            "input_bytes": len(before),
            "after_known_zero_bytes": len(after_zero),
            "after_dead_affine_bytes": len(after_dead),
            "saved_bytes": len(before) - len(after_dead),
            "pruned_target_updates": int(stats["pruned_target_updates"]),
        })
        current = after_dead
        if len(current) == len(before):
            return current, cycles
    raise AssertionError(f"local semantic fixed point did not converge in {max_cycles} cycles")


def profile(path: Path, max_cycles: int) -> dict[str, object]:
    original = strip_bf(path.read_text(encoding="ascii", errors="ignore"))
    local, cycles = local_semantic_fixedpoint(original, max_cycles=max_cycles)
    macro = profile_relational_text(local)
    return {
        "name": str(path),
        "original_bf_bytes": len(original),
        "post_local_bf_bytes": len(local),
        "local_saved_bytes": len(original) - len(local),
        "local_cycles": cycles,
        "post_local_semantic_tokens": macro["semantic_tokens"],
        "relational_macro_sweep": macro["sweep"],
        "best": macro["best"],
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
        return

    total = sum(int(r["original_bf_bytes"]) for r in rows)
    target = total // 10
    local_total = sum(int(r["post_local_bf_bytes"]) for r in rows)
    loader = sum(int(r["best"]["best_loader_chars"]) for r in rows)
    print(
        f"original={total:,} post_local={local_total:,} "
        f"payload_loader={loader:,} target10x={target:,} decoder_budget={target-loader:,}"
    )
    for r in rows:
        b = r["best"]
        print(
            f"{r['name']}: {r['original_bf_bytes']:,}->{r['post_local_bf_bytes']:,} "
            f"loader={b['best_loader_chars']:,} via={b['best_loader_channel']} "
            f"R={b['max_rules']} relations={b['add_relation_definitions']:,}"
        )


if __name__ == "__main__":
    main()
