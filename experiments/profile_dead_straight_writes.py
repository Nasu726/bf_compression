from __future__ import annotations

"""Profile residual straight-line dead writes after the combined fixed point.

Input is expected to have already reached the Level-1/dead-affine fixed point.
The proof pattern is intentionally strict.  A maximal straight +/- run at the
current relative cell is dead when, before any non-clear loop/barrier:

- the same cell is unconditionally cleared by ``[-]``;
- neither ``.`` nor ``,`` touches that cell first;
- only pointer moves, +/- arithmetic, I/O on other cells, or clears of other
  cells intervene.

Deleting such arithmetic cannot affect control flow or pointer movement, and
the guaranteed terminating clear makes the cell states reconverge before any
permitted observation.  Final tape state is kept observable: reaching lexical
or program end is never treated as a kill.

The opportunity scan is linear in the parsed BF size.  Each lexical sequence is
first annotated with relative pointer positions, then scanned once backwards.
For each relative cell we retain the nearest future clear that is still safe to
reach.  Observation of that cell removes the fact; every non-clear loop clears
all facts.  Nested lexical scopes are processed recursively, so every BF node is
visited O(1) times overall.

This file is opportunity measurement, not the production optimizer.  It also
constructs the conservatively pruned candidate internally so the reported
canonicalized byte saving includes secondary +/- and pointer cancellation.
"""

import argparse
import json
from collections import Counter
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_dead_affine_targets import is_clear
from region_zero_opt import (
    Loop,
    body_static_delta,
    canonicalize,
    parse,
    precanonicalize,
    stringify,
    strip_bf,
)


def new_stats() -> dict[str, Any]:
    return {
        "lexical_sequences": 0,
        "straight_arithmetic_runs": 0,
        "straight_arithmetic_bytes": 0,
        "proved_dead_runs": 0,
        "proved_dead_arithmetic_bytes": 0,
        "clear_distance_nodes": Counter(),
        "dead_run_lengths": Counter(),
    }


def pointer_positions(nodes: tuple[object, ...]) -> list[int]:
    """Relative pointer position immediately before each node.

    Pointer-balanced loops preserve the current relative frame.  A moving or
    recursively dynamic loop starts a fresh frame for following siblings.  The
    backward proof treats every non-clear loop as a barrier anyway, so no cell
    fact crosses an uncertain frame boundary.
    """
    ptr = 0
    positions: list[int] = []
    for node in nodes:
        positions.append(ptr)
        if node == ">":
            ptr += 1
        elif node == "<":
            ptr -= 1
        elif isinstance(node, Loop):
            body = canonicalize(node.body)
            delta = body_static_delta(body)
            if delta is None or delta != 0:
                ptr = 0
    return positions


def transform_sequence(nodes: tuple[object, ...], stats: dict[str, Any]) -> tuple[object, ...]:
    stats["lexical_sequences"] += 1
    nodes = canonicalize(nodes)
    positions = pointer_positions(nodes)

    # Recurse independently into every lexical child.  A child may contain
    # opportunities even though its enclosing loop is a barrier to sibling
    # demand facts.
    child_bodies: dict[int, tuple[object, ...]] = {}
    for index, node in enumerate(nodes):
        if isinstance(node, Loop):
            child_bodies[index] = transform_sequence(canonicalize(node.body), stats)

    # Nearest still-valid guaranteed clear for each relative cell.  Values are
    # node indices so we can report how far a dead arithmetic run is from its
    # killing clear without rescanning the suffix.
    future_clear: dict[int, int] = {}
    dead_kill: dict[int, int] = {}

    for index in range(len(nodes) - 1, -1, -1):
        node = nodes[index]
        ptr = positions[index]

        if isinstance(node, Loop):
            if is_clear(node):
                # `[-]` terminates on the 8-bit wrapping ABI, touches no other
                # cell, and returns to the same pointer.
                future_clear[ptr] = index
            else:
                # First experiment deliberately refuses to summarize any other
                # loop, even a pointer-balanced affine loop.
                future_clear.clear()
            continue

        if node in (".", ","):
            # Output observes the value.  Input is also conservative because
            # EOF-no-change can preserve and therefore depend on the old value.
            future_clear.pop(ptr, None)
            continue

        if node in ("+", "-") and ptr in future_clear:
            dead_kill[index] = future_clear[ptr]

    # Count maximal arithmetic runs.  Canonical input means one run operates at
    # one relative cell, so its commands must be uniformly dead or live.
    index = 0
    while index < len(nodes):
        if nodes[index] not in ("+", "-"):
            index += 1
            continue
        end = index + 1
        while end < len(nodes) and nodes[end] in ("+", "-"):
            end += 1
        run_len = end - index
        stats["straight_arithmetic_runs"] += 1
        stats["straight_arithmetic_bytes"] += run_len
        flags = [i in dead_kill for i in range(index, end)]
        if any(flags) and not all(flags):
            raise AssertionError((index, end, flags))
        if all(flags):
            kill = dead_kill[index]
            if any(dead_kill[i] != kill for i in range(index, end)):
                raise AssertionError((index, end, dead_kill))
            stats["proved_dead_runs"] += 1
            stats["proved_dead_arithmetic_bytes"] += run_len
            stats["clear_distance_nodes"][str(kill - end + 1)] += 1
            stats["dead_run_lengths"][str(run_len)] += 1
        index = end

    out: list[object] = []
    for index, node in enumerate(nodes):
        if node in ("+", "-") and index in dead_kill:
            continue
        if isinstance(node, Loop):
            out.append(Loop(child_bodies[index]))
        else:
            out.append(node)
    return canonicalize(tuple(out))


def profile_code(code: str) -> tuple[str, dict[str, Any]]:
    original = strip_bf(code)
    nodes = canonicalize(parse(precanonicalize(original)))
    stats = new_stats()
    transformed = transform_sequence(nodes, stats)
    result = stringify(transformed)
    for key in ("clear_distance_nodes", "dead_run_lengths"):
        stats[key] = dict(stats[key])
    stats["input_bytes"] = len(original)
    stats["candidate_bytes"] = len(result)
    stats["canonicalized_candidate_saved_bytes"] = len(original) - len(result)
    stats["secondary_cancellation_bytes"] = (
        stats["canonicalized_candidate_saved_bytes"]
        - stats["proved_dead_arithmetic_bytes"]
    )
    stats["scan_complexity"] = "O(parsed BF bytes)"
    if stats["canonicalized_candidate_saved_bytes"] < stats["proved_dead_arithmetic_bytes"]:
        raise AssertionError(stats)
    return result, stats


def profile(path: Path) -> dict[str, Any]:
    code = path.read_text(encoding="ascii", errors="ignore")
    _candidate, stats = profile_code(code)
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
                f"{row['name']}: dead_runs={row['proved_dead_runs']:,} "
                f"dead_arithmetic={row['proved_dead_arithmetic_bytes']:,} "
                f"candidate_saved={row['canonicalized_candidate_saved_bytes']:,}"
            )


if __name__ == "__main__":
    main()
