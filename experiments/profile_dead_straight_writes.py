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
from profile_dead_affine_targets import target_killed_before_observation
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


def transform_sequence(nodes: tuple[object, ...], stats: dict[str, Any]) -> tuple[object, ...]:
    stats["lexical_sequences"] += 1
    ptr = 0
    out: list[object] = []
    index = 0

    while index < len(nodes):
        node = nodes[index]
        if node == ">":
            ptr += 1
            out.append(node)
            index += 1
            continue
        if node == "<":
            ptr -= 1
            out.append(node)
            index += 1
            continue

        if node in ("+", "-"):
            # canonicalize() has already collapsed a contiguous modular add to
            # one sign, but retain generic maximal-run handling here.
            end = index + 1
            while end < len(nodes) and nodes[end] in ("+", "-"):
                end += 1
            run = nodes[index:end]
            run_len = len(run)
            stats["straight_arithmetic_runs"] += 1
            stats["straight_arithmetic_bytes"] += run_len
            proved, distance = target_killed_before_observation(
                nodes,
                end,
                start_ptr=ptr,
                target=ptr,
            )
            if proved:
                stats["proved_dead_runs"] += 1
                stats["proved_dead_arithmetic_bytes"] += run_len
                stats["clear_distance_nodes"][str(distance)] += 1
                stats["dead_run_lengths"][str(run_len)] += 1
            else:
                out.extend(run)
            index = end
            continue

        if isinstance(node, Loop):
            body = canonicalize(node.body)
            transformed_body = transform_sequence(body, stats)
            out.append(Loop(transformed_body))

            # Arithmetic deletion never changes pointer delta.  Mirror the
            # relative-frame rule used by the forward/backward research passes.
            delta = body_static_delta(body)
            if delta is None or delta != 0:
                ptr = 0
            index += 1
            continue

        out.append(node)
        index += 1

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
