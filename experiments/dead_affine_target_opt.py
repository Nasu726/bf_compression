from __future__ import annotations

"""Prune affine-loop target updates killed by a later guaranteed clear.

This pass is deliberately narrower than a general liveness analysis.  It runs
after Level-1 recursive relative-region known-zero optimization and applies only
the proof pattern measured by ``profile_dead_affine_targets.py``:

- producer is a flat pointer-balanced arithmetic loop;
- target is not the producer control cell;
- before an unrecognized loop/barrier, the target is cleared by ``[-]``;
- no intervening output/input observes that target.

Deleting the producer's modular additions to such a target cannot affect the
producer's control evolution or pointer path.  On terminating paths, the later
clear makes the target states converge before any observation.  Straight-line
+/- updates in between remain unobserved and may therefore depend on the changed
intermediate value without changing later observable state.
"""

import argparse
import json
from collections import Counter
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_dead_affine_targets import (
    flat_balanced_coeff,
    prune_targets,
    target_killed_before_observation,
)
from region_zero_opt import (
    Loop,
    body_static_delta,
    canonicalize,
    optimize_region_zero,
    parse,
    precanonicalize,
    stringify,
    strip_bf,
)


def new_stats() -> dict[str, Any]:
    return {
        "rewritten_producer_loops": 0,
        "pruned_target_updates": 0,
        "producer_loops_all_targets_pruned": 0,
        "local_loop_bytes_saved": 0,
        "savings_per_loop": Counter(),
    }


def transform_sequence(nodes: tuple[object, ...], stats: dict[str, Any]) -> tuple[object, ...]:
    ptr = 0
    out: list[object] = []

    for index, node in enumerate(nodes):
        if node == ">":
            ptr += 1
            out.append(node)
            continue
        if node == "<":
            ptr -= 1
            out.append(node)
            continue
        if not isinstance(node, Loop):
            out.append(node)
            continue

        original_body = canonicalize(node.body)
        coeff = flat_balanced_coeff(original_body)
        transformed_body = original_body

        if coeff is not None and any(off != 0 for off in coeff):
            targets = {off: value for off, value in coeff.items() if off != 0}
            dead: set[int] = set()
            for off in targets:
                proved, _distance = target_killed_before_observation(
                    nodes,
                    index + 1,
                    start_ptr=ptr,
                    target=ptr + off,
                )
                if proved:
                    dead.add(off)

            if dead:
                transformed_body = prune_targets(original_body, dead)
                before = 2 + len(stringify(original_body))
                after = 2 + len(stringify(transformed_body))
                saving = before - after
                if saving <= 0:
                    raise AssertionError((original_body, dead, transformed_body, saving))
                stats["rewritten_producer_loops"] += 1
                stats["pruned_target_updates"] += len(dead)
                if dead == set(targets):
                    stats["producer_loops_all_targets_pruned"] += 1
                stats["local_loop_bytes_saved"] += saving
                stats["savings_per_loop"][str(saving)] += 1
        else:
            # Non-flat/nested bodies can contain independent local opportunities.
            transformed_body = transform_sequence(original_body, stats)

        out.append(Loop(transformed_body))

        # Mirror Level 1's relative-frame rule for sibling coordinates.
        delta = body_static_delta(original_body)
        if delta is None or delta != 0:
            ptr = 0

    return canonicalize(tuple(out))


def optimize_dead_affine_targets_with_stats(code: str) -> tuple[str, dict[str, Any]]:
    original = strip_bf(code)
    nodes = canonicalize(parse(precanonicalize(original)))
    stats = new_stats()
    transformed = transform_sequence(nodes, stats)
    result = stringify(transformed)
    stats["savings_per_loop"] = dict(stats["savings_per_loop"])
    stats["input_bytes"] = len(original)
    stats["result_bytes"] = len(result)
    stats["actual_saved_bytes"] = len(original) - len(result)
    if stats["actual_saved_bytes"] < 0:
        raise AssertionError((len(original), len(result)))
    return result, stats


def optimize_dead_affine_targets(code: str) -> str:
    return optimize_dead_affine_targets_with_stats(code)[0]


def optimize_region_zero_dead_affine_with_stats(code: str) -> tuple[str, dict[str, Any]]:
    raw = strip_bf(code)
    level1 = optimize_region_zero(raw)
    result, dead_stats = optimize_dead_affine_targets_with_stats(level1)
    stats = {
        "original_bytes": len(raw),
        "level1_bytes": len(level1),
        "combined_bytes": len(result),
        "level1_saved_bytes": len(raw) - len(level1),
        "incremental_dead_affine_saved_bytes": len(level1) - len(result),
        "total_saved_bytes": len(raw) - len(result),
        **dead_stats,
    }
    return result, stats


def optimize_region_zero_dead_affine(code: str) -> str:
    return optimize_region_zero_dead_affine_with_stats(code)[0]


def profile(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="ascii", errors="ignore")
    _result, stats = optimize_region_zero_dead_affine_with_stats(raw)
    return {"name": str(path), **stats}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rows = [profile(Path(name)) for name in args.files]
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        for row in rows:
            print(
                f"{row['name']}: level1={row['level1_bytes']:,} "
                f"combined={row['combined_bytes']:,} "
                f"incremental={row['incremental_dead_affine_saved_bytes']:,} "
                f"loops={row['rewritten_producer_loops']:,} "
                f"targets={row['pruned_target_updates']:,}"
            )


if __name__ == "__main__":
    main()
