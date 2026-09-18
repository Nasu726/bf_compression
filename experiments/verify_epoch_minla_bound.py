from __future__ import annotations

from collections import Counter

from profile_epoch_minla_bound import EpochGraph, exact_minla, profile_text, star_lower_bound


def graph(n: int, weighted_edges: list[tuple[int, int, int]]) -> EpochGraph:
    edges: Counter[tuple[int, int]] = Counter()
    current = 0
    for a, b, w in weighted_edges:
        if a > b:
            a, b = b, a
        edges[(a, b)] += w
        current += w * abs(a - b)
    return EpochGraph("static", set(range(n)), edges, current)


def main() -> None:
    # Unit path: its natural order is optimal.
    g = graph(3, [(0, 1, 1), (1, 2, 1)])
    assert exact_minla(g) == 2
    assert star_lower_bound(g) <= 2

    # Triangle: every ordering has distances 1, 1, 2.
    g = graph(3, [(0, 1, 1), (1, 2, 1), (0, 2, 1)])
    assert exact_minla(g) == 4
    assert star_lower_bound(g) <= 4

    # Four-leaf star: exact optimum is 1+1+2+2 = 6.  The independent-star
    # lower bound is 5 after double-count correction, so this also verifies
    # that we do not accidentally present the cheap bound as exact.
    g = graph(5, [(0, 1, 1), (0, 2, 1), (0, 3, 1), (0, 4, 1)])
    assert exact_minla(g) == 6
    assert star_lower_bound(g) == 5

    # Source-level example: current layout puts logical cell 4 far away, but
    # only cells {0,1,4} matter.  Free relayout can make 0 adjacent to both.
    row = profile_text(">>>>+<<<<+>+<")
    assert row["movement_bytes"] == 10, row
    assert row["all_adjacent_movement_lower_bound"] == 4, row
    assert row["rigorous_relaxed_movement_lower_bound"] == 4, row

    # A moving-loop body becomes a periodic relaxed epoch; movement accounting
    # must still cover every literal pointer command exactly once.
    row = profile_text("+[>]")
    assert row["movement_bytes"] == 1, row
    assert row["contexts"]["periodic"]["current_movement_bytes"] == 1, row

    print("epoch MinLA verification: ok")


if __name__ == "__main__":
    main()
