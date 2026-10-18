from __future__ import annotations

"""Profile how much compiler BF size is tape-routing rather than computation.

The seven-artifact macro profile showed that >92% of emitted commands are
pointer movement.  This profiler decomposes those movement runs by enclosing
loop context and records a deliberately optimistic routing oracle.

Contexts:
- static: no moving/dynamic ancestor;
- periodic: at least one statically moving ancestor and no dynamic ancestor;
- dynamic: at least one recursively dynamic ancestor.

The ``one_step_per_run`` oracle replaces every non-empty contiguous pointer run
by one move while leaving all non-movement commands untouched.  It is not
claimed achievable: a one-dimensional tape generally cannot make every pair of
logical cells adjacent simultaneously.  It is useful because it gives the
right scale for a 10x target and tells us whether layout is even worth pursuing.
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
    parse,
    precanonicalize,
    stringify,
    strip_bf,
)


CONTEXTS = ("static", "periodic", "dynamic")
THRESHOLDS = (4, 8, 16, 32, 64, 128, 256, 512, 1024)


def loop_kind(body: tuple[object, ...]) -> str:
    delta = body_static_delta(body)
    if delta is None:
        return "dynamic"
    if delta == 0:
        return "balanced"
    return "moving"


def child_context(parent: str, kind: str) -> str:
    if parent == "dynamic" or kind == "dynamic":
        return "dynamic"
    if parent == "periodic" or kind == "moving":
        return "periodic"
    return "static"


def new_context_stats() -> dict[str, Any]:
    return {
        "movement_bytes": 0,
        "movement_run_count": 0,
        "movement_run_max": 0,
        "movement_bytes_in_runs_ge": {str(t): 0 for t in THRESHOLDS},
        "movement_runs_ge": {str(t): 0 for t in THRESHOLDS},
    }


def record_run(stats: dict[str, Any], length: int) -> None:
    if length <= 0:
        return
    stats["movement_bytes"] += length
    stats["movement_run_count"] += 1
    stats["movement_run_max"] = max(stats["movement_run_max"], length)
    for t in THRESHOLDS:
        if length >= t:
            stats["movement_bytes_in_runs_ge"][str(t)] += length
            stats["movement_runs_ge"][str(t)] += 1


def relative_touched_offsets(body: tuple[object, ...]) -> set[int] | None:
    """Offsets touched in one iteration when all child loops are balanced.

    Loop controls count as touches.  Returns None if a nested moving/dynamic loop
    makes one-iteration static coordinates unavailable.
    """
    ptr = 0
    touched: set[int] = {0}
    for node in body:
        if node == ">":
            ptr += 1
            touched.add(ptr)
        elif node == "<":
            ptr -= 1
            touched.add(ptr)
        elif node in ("+", "-", ".", ","):
            touched.add(ptr)
        elif isinstance(node, Loop):
            child = canonicalize(node.body)
            if body_static_delta(child) != 0:
                return None
            child_offsets = relative_touched_offsets(child)
            if child_offsets is None:
                return None
            touched.update(ptr + off for off in child_offsets)
        else:
            raise AssertionError(node)
    return touched


def profile_code(text: str) -> dict[str, Any]:
    raw = strip_bf(text)
    nodes = canonicalize(parse(precanonicalize(raw)))
    canonical_bytes = len(stringify(nodes))
    contexts = {name: new_context_stats() for name in CONTEXTS}
    loops = Counter()
    moving_stride = Counter()
    moving_span = Counter()
    moving_stride_ge = Counter()
    moving_loop_source_bytes = 0

    def walk(seq: tuple[object, ...], context: str) -> None:
        nonlocal moving_loop_source_bytes
        run = 0

        def flush() -> None:
            nonlocal run
            record_run(contexts[context], run)
            run = 0

        for node in seq:
            if node in (">", "<"):
                run += 1
                continue
            flush()
            if not isinstance(node, Loop):
                continue

            body = canonicalize(node.body)
            kind = loop_kind(body)
            loops[kind] += 1
            if kind == "moving":
                delta = body_static_delta(body)
                assert delta is not None and delta != 0
                stride = abs(delta)
                moving_stride[str(stride)] += 1
                for t in (2, 4, 8, 16, 32, 64, 128):
                    if stride >= t:
                        moving_stride_ge[str(t)] += 1
                touched = relative_touched_offsets(body)
                if touched:
                    span = max(touched) - min(touched) + 1
                    moving_span[str(span)] += 1
                moving_loop_source_bytes += 2 + len(stringify(body))

            walk(body, child_context(context, kind))
        flush()

    walk(nodes, "static")

    total_move = sum(contexts[c]["movement_bytes"] for c in CONTEXTS)
    total_runs = sum(contexts[c]["movement_run_count"] for c in CONTEXTS)
    nonmove = canonical_bytes - total_move
    if nonmove < 0:
        raise AssertionError((canonical_bytes, total_move))

    cap_oracles = {}
    # For each cap, charge min(run_length, cap).  Reconstruct from threshold
    # histograms only for cap=1 via exact run count; other caps are measured by
    # a second lightweight traversal below.
    capped_move = {cap: 0 for cap in (1, 2, 4, 8, 16, 32)}

    def walk_caps(seq: tuple[object, ...]) -> None:
        run = 0

        def flush() -> None:
            nonlocal run
            if run:
                for cap in capped_move:
                    capped_move[cap] += min(run, cap)
                run = 0

        for node in seq:
            if node in (">", "<"):
                run += 1
            else:
                flush()
                if isinstance(node, Loop):
                    walk_caps(canonicalize(node.body))
        flush()

    walk_caps(nodes)
    for cap, move_cost in capped_move.items():
        cap_oracles[str(cap)] = {
            "movement_bytes": move_cost,
            "result_bytes": nonmove + move_cost,
        }

    return {
        "bf_bytes": len(raw),
        "canonical_bytes": canonical_bytes,
        "movement_bytes": total_move,
        "movement_fraction": total_move / canonical_bytes if canonical_bytes else 0.0,
        "nonmovement_bytes": nonmove,
        "movement_run_count": total_runs,
        "mean_movement_run_length": total_move / total_runs if total_runs else 0.0,
        "one_step_per_run_oracle_bytes": nonmove + total_runs,
        "capped_run_oracles": cap_oracles,
        "contexts": contexts,
        "loop_kinds": dict(loops),
        "moving_loop_source_bytes": moving_loop_source_bytes,
        "moving_stride_histogram": dict(moving_stride),
        "moving_stride_ge": dict(moving_stride_ge),
        "moving_span_histogram": dict(moving_span),
    }


def profile(path: Path) -> dict[str, Any]:
    return {
        "name": str(path),
        **profile_code(path.read_text(encoding="ascii", errors="ignore")),
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
            ctx = row["contexts"]
            print(
                f"{row['name']}: move={row['movement_bytes']:,} "
                f"runs={row['movement_run_count']:,} "
                f"oracle1={row['one_step_per_run_oracle_bytes']:,} "
                f"static={ctx['static']['movement_bytes']:,} "
                f"periodic={ctx['periodic']['movement_bytes']:,} "
                f"dynamic={ctx['dynamic']['movement_bytes']:,}"
            )


if __name__ == "__main__":
    main()
