from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_dead_affine_targets import analyze_sequence, new_stats
from region_zero_opt import canonicalize, optimize_region_zero, parse, precanonicalize


def profile_text(code: str) -> dict:
    level1 = optimize_region_zero(code)
    nodes = canonicalize(parse(precanonicalize(level1)))
    stats = new_stats()
    analyze_sequence(nodes, stats)
    return stats


def main() -> None:
    # Classic transfer into a cell that is cleared before any observation.
    s = profile_text("+[->+<]>[-]<")
    assert s["proved_dead_target_updates"] == 1, s
    assert s["producer_loops_with_dead_targets"] == 1, s
    assert s["estimated_loop_bytes_saved"] >= 1, s

    # Straight-line arithmetic on the target remains dead if the entire value is
    # subsequently killed by a guaranteed clear.
    s = profile_text("+[->+<]>++[-]<")
    assert s["proved_dead_target_updates"] == 1, s

    # Output observes the target and must block the proof.
    s = profile_text("+[->+<]>.[-]<")
    assert s["proved_dead_target_updates"] == 0, s

    # Input at the target is also an observation under EOF-no-change semantics.
    s = profile_text("+[->+<]>,[-]<")
    assert s["proved_dead_target_updates"] == 0, s

    # A non-clear loop before the kill is deliberately a conservative barrier.
    s = profile_text("+[->+<]>+[>+<-][-]<")
    assert s["proved_dead_target_updates"] == 0, s

    # A clear of another cell is safe to cross.
    s = profile_text("+[->+>+<<]>>[-]<[-]<")
    assert s["proved_dead_target_updates"] >= 1, s

    # Reaching the end without a clear is not treated as dead because final tape
    # state is retained as a conservative observable in this research baseline.
    s = profile_text("+[->+<]>")
    assert s["proved_dead_target_updates"] == 0, s

    print("dead-affine-target opportunity checks: OK")


if __name__ == "__main__":
    main()
