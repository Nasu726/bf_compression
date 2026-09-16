from __future__ import annotations

"""Profile conservative backward-demand opportunities after Level 1.

The first demanded-information experiment intentionally recognizes only a very
strong local proof pattern:

1. a flat pointer-balanced arithmetic loop updates one or more non-control
   target cells;
2. after the loop, in the same relative pointer frame, a target is not observed
   by output/input or used as any loop control;
3. before any unrecognized loop/barrier, that target is unconditionally cleared
   by ``[-]``.

Straight-line +/- updates to the target between the producer and its clear do
not make the earlier value live: their result is also discarded by the clear.
A clear of some other cell is safe to cross because 8-bit ``[-]`` terminates,
has no I/O, and returns to the same pointer.

For a proved-dead target, +/- commands at that offset inside the producer loop
can be deleted. Pointer moves are then canonicalized, so this profiler reports
the exact local loop-byte saving of that conservative rewrite. It does not
apply the rewrite yet.
"""

import argparse
import json
from collections import Counter
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
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


def flat_balanced_coeff(body: tuple[object, ...]) -> dict[int, int] | None:
    ptr = 0
    coeff: dict[int, int] = {}
    for node in body:
        if isinstance(node, Loop) or node in (",", "."):
            return None
        if node == ">":
            ptr += 1
        elif node == "<":
            ptr -= 1
        elif node == "+":
            coeff[ptr] = (coeff.get(ptr, 0) + 1) & 255
        elif node == "-":
            coeff[ptr] = (coeff.get(ptr, 0) - 1) & 255
        else:
            raise AssertionError(node)
    if ptr != 0:
        return None
    return {off: value for off, value in coeff.items() if value}


def is_clear(node: object) -> bool:
    return isinstance(node, Loop) and canonicalize(node.body) == ("-",)


def target_killed_before_observation(
    nodes: tuple[object, ...],
    start_index: int,
    *,
    start_ptr: int,
    target: int,
) -> tuple[bool, int]:
    """Return (proved_dead, distance_in_nodes) for one relative target.

    This deliberately stops at every non-clear loop. The proof therefore never
    depends on summarizing an intervening branch or moving-pointer loop.
    """
    ptr = start_ptr
    distance = 0
    for node in nodes[start_index:]:
        distance += 1
        if node == ">":
            ptr += 1
            continue
        if node == "<":
            ptr -= 1
            continue
        if node in ("+", "-"):
            # Arithmetic is a dead-state-preserving update if this cell is later
            # killed before observation. It need not make the old value live.
            continue
        if node == ".":
            if ptr == target:
                return False, distance
            continue
        if node == ",":
            # Under EOF-no-change semantics input can depend on the old cell.
            if ptr == target:
                return False, distance
            continue
        if not isinstance(node, Loop):
            raise AssertionError(node)

        if is_clear(node):
            if ptr == target:
                return True, distance
            # A clear at another offset is terminating, local, and pointer-balanced.
            continue

        # Any other loop may branch on or indirectly touch the target. Stop
        # rather than assuming an effect summary in this first profiler.
        return False, distance

    # Final tape state is kept conservative; reaching lexical/program end is not
    # treated as proving the value dead.
    return False, distance


def prune_targets(body: tuple[object, ...], dead_offsets: set[int]) -> tuple[object, ...]:
    ptr = 0
    out: list[object] = []
    for node in body:
        if node == ">":
            ptr += 1
            out.append(node)
        elif node == "<":
            ptr -= 1
            out.append(node)
        elif node in ("+", "-"):
            if ptr not in dead_offsets:
                out.append(node)
        else:
            # Caller only passes flat arithmetic bodies.
            out.append(node)
    return canonicalize(tuple(out))


def new_stats() -> dict[str, Any]:
    return {
        "lexical_sequences": 0,
        "flat_balanced_affine_loops": 0,
        "affine_target_updates": 0,
        "proved_dead_target_updates": 0,
        "producer_loops_with_dead_targets": 0,
        "producer_loops_all_targets_dead": 0,
        "estimated_loop_bytes_saved": 0,
        "producer_loop_bytes_before": 0,
        "producer_loop_bytes_after": 0,
        "dead_target_coefficients": Counter(),
        "clear_distance_nodes": Counter(),
        "savings_per_loop": Counter(),
    }


def analyze_sequence(nodes: tuple[object, ...], stats: dict[str, Any]) -> None:
    stats["lexical_sequences"] += 1
    ptr = 0
    for index, node in enumerate(nodes):
        if node == ">":
            ptr += 1
            continue
        if node == "<":
            ptr -= 1
            continue
        if not isinstance(node, Loop):
            continue

        body = canonicalize(node.body)
        coeff = flat_balanced_coeff(body)
        if coeff is not None and any(off != 0 for off in coeff):
            stats["flat_balanced_affine_loops"] += 1
            targets = {off: value for off, value in coeff.items() if off != 0}
            stats["affine_target_updates"] += len(targets)
            dead: set[int] = set()
            for off, value in targets.items():
                proved, distance = target_killed_before_observation(
                    nodes,
                    index + 1,
                    start_ptr=ptr,
                    target=ptr + off,
                )
                if proved:
                    dead.add(off)
                    stats["proved_dead_target_updates"] += 1
                    stats["dead_target_coefficients"][str(value)] += 1
                    stats["clear_distance_nodes"][str(distance)] += 1

            if dead:
                stats["producer_loops_with_dead_targets"] += 1
                if dead == set(targets):
                    stats["producer_loops_all_targets_dead"] += 1
                pruned = prune_targets(body, dead)
                before = 2 + len(stringify(body))
                after = 2 + len(stringify(pruned))
                saving = before - after
                if saving < 0:
                    raise AssertionError((body, dead, pruned))
                stats["estimated_loop_bytes_saved"] += saving
                stats["producer_loop_bytes_before"] += before
                stats["producer_loop_bytes_after"] += after
                stats["savings_per_loop"][str(saving)] += 1

        # Every body is also a lexical sequence. Relative offsets inside it are
        # meaningful even if the outer loop itself moves the pointer.
        analyze_sequence(body, stats)

        # Keep the same frame after a recursively balanced loop. A moving or
        # recursively dynamic loop destroys absolute identity, but on normal
        # exit Level 1 starts a fresh relative epoch at the exit pointer. Mirror
        # that rule here by resetting the sibling coordinate to relative zero.
        delta = body_static_delta(body)
        if delta is None or delta != 0:
            ptr = 0


def profile(path: Path) -> dict[str, Any]:
    raw = strip_bf(path.read_text(encoding="ascii", errors="ignore"))
    level1 = optimize_region_zero(raw)
    nodes = canonicalize(parse(precanonicalize(level1)))
    stats = new_stats()
    analyze_sequence(nodes, stats)
    for key in ("dead_target_coefficients", "clear_distance_nodes", "savings_per_loop"):
        stats[key] = dict(stats[key])
    return {
        "name": str(path),
        "original_bytes": len(raw),
        "level1_bytes": len(level1),
        **stats,
    }


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
                f"{row['name']}: affine_targets={row['affine_target_updates']:,} "
                f"dead={row['proved_dead_target_updates']:,} "
                f"producer_loops={row['producer_loops_with_dead_targets']:,} "
                f"estimated_saved={row['estimated_loop_bytes_saved']:,}"
            )


if __name__ == "__main__":
    main()
