from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dead_affine_target_opt import optimize_region_zero_dead_affine_with_stats
from verify_region_zero import run


def same(code: str, inputs=(b"", b"A")) -> tuple[str, dict]:
    optimized, stats = optimize_region_zero_dead_affine_with_stats(code)
    assert len(optimized) <= len(code), (code, optimized, stats)
    for eof in ("nochange", "255", "0"):
        for data in inputs:
            a = run(code, data, eof=eof)
            b = run(optimized, data, eof=eof)
            assert a == b, (code, optimized, eof, data, a, b, stats)
    return optimized, stats


def main() -> None:
    optimized, stats = same("+[->+<]>[-]<")
    assert stats["pruned_target_updates"] == 1, (optimized, stats)
    assert stats["incremental_dead_affine_saved_bytes"] > 0, (optimized, stats)

    # Straight-line target arithmetic before the clear is also discarded state.
    optimized, stats = same("+[->+<]>++[-]<")
    assert stats["pruned_target_updates"] == 1, (optimized, stats)

    # Observation blocks the target rewrite.
    optimized, stats = same("+[->+<]>.[-]<")
    assert stats["pruned_target_updates"] == 0, (optimized, stats)

    # EOF-no-change makes input depend on the old target value, so it blocks.
    optimized, stats = same(",+[->+<]>,[-]<", inputs=(b"", b"\x00", b"A", b"\xff"))
    assert stats["pruned_target_updates"] == 0, (optimized, stats)

    # Two independently killed targets can both be pruned from one producer.
    optimized, stats = same("+[->+>+<<]>>[-]<[-]<")
    assert stats["pruned_target_updates"] == 2, (optimized, stats)

    # Nested lexical scopes are transformed recursively.  Keep the enclosing
    # loop terminating so full final-state differential comparison is meaningful:
    # cell 0 counts two outer iterations; each iteration creates a one-shot
    # transfer on cells 1->2 and then clears cell 2 before returning to cell 0.
    optimized, stats = same("++[>+[->+<]>[-]<<-]")
    assert stats["pruned_target_updates"] >= 1, (optimized, stats)

    # A moving loop starts a fresh relative frame; a later local transfer/clear
    # pattern must still be recognized without recovering stale absolute identity.
    optimized, stats = same("+[>]+[->+<]>[-]<")
    assert stats["pruned_target_updates"] == 1, (optimized, stats)

    print("dead-affine-target differential checks: OK")


if __name__ == "__main__":
    main()
