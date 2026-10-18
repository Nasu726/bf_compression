from __future__ import annotations

"""Shorten clear loops when the current 8-bit cell value is known exactly.

This is a follow-up pass for compiler-generated Brainfuck after region-zero
optimization.  If the current value is known, ``[-]`` (3 bytes) can be replaced
by the shortest direct +/- path to zero whenever that path is shorter.  For an
8-bit wrapping cell this is profitable for values 1, 2, 254, and 255.

The pass uses the same relative-base barrier discipline as region_zero_opt:
balanced loops preserve absolute offsets inside the current epoch; a
moving/dynamic loop discards absolute identity but establishes that the new
relative current cell is zero on normal exit.
"""

import argparse
import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from region_zero_opt import (
    Loop,
    UNKNOWN,
    balanced_effects,
    body_static_delta,
    canonicalize,
    optimize_region_zero,
    parse,
    precanonicalize,
    stringify,
    strip_bf,
)


def _direct_zero(value: int) -> tuple[str, ...]:
    value &= 255
    if value <= 128:
        return tuple("-" for _ in range(value))
    return tuple("+" for _ in range(256 - value))


def _optimize_sequence(
    nodes: tuple[object, ...],
    *,
    default_value: int | None,
    initial_values: dict[int, int | None] | None,
    stats: dict[str, Any],
) -> tuple[object, ...]:
    values: dict[int, int | None] = dict(initial_values or {})
    logical_ptr = 0
    emitted_ptr = 0
    out: list[object] = []

    def value_at(cell: int) -> int | None:
        return values[cell] if cell in values else default_value

    def flush_move() -> None:
        nonlocal emitted_ptr
        delta = logical_ptr - emitted_ptr
        if delta > 0:
            out.extend(">" for _ in range(delta))
        elif delta < 0:
            out.extend("<" for _ in range(-delta))
        emitted_ptr = logical_ptr

    for node in nodes:
        if node == ">":
            logical_ptr += 1
            continue
        if node == "<":
            logical_ptr -= 1
            continue
        if node in ("+", "-"):
            flush_move()
            cur = value_at(logical_ptr)
            if cur is not UNKNOWN:
                values[logical_ptr] = (cur + (1 if node == "+" else -1)) & 255
            else:
                values[logical_ptr] = UNKNOWN
            out.append(node)
            continue
        if node == ",":
            flush_move()
            values[logical_ptr] = UNKNOWN
            out.append(node)
            continue
        if node == ".":
            flush_move()
            out.append(node)
            continue
        if not isinstance(node, Loop):
            raise AssertionError(node)

        body = canonicalize(node.body)
        cur = value_at(logical_ptr)
        if body == ("-",):
            flush_move()
            if cur is not UNKNOWN:
                direct = _direct_zero(cur)
                if len(direct) < 3:
                    out.extend(direct)
                    stats["rewritten_known_clears"] += 1
                    stats["literal_bytes_saved"] += 3 - len(direct)
                    key = str(cur)
                    stats["rewrites_by_entry_value"][key] = (
                        stats["rewrites_by_entry_value"].get(key, 0) + 1
                    )
                else:
                    out.append(Loop(("-",)))
            else:
                out.append(Loop(("-",)))
            values[logical_ptr] = 0
            continue

        # Body-local facts must hold on every executed iteration.  Do not seed
        # the recursive body with a one-time exact outer entry value.
        optimized_body = _optimize_sequence(
            body,
            default_value=UNKNOWN,
            initial_values=None,
            stats=stats,
        )
        optimized_body = canonicalize(optimized_body)

        flush_move()
        delta = body_static_delta(optimized_body)
        if delta == 0:
            _end, touched = balanced_effects(optimized_body, logical_ptr)
            out.append(Loop(optimized_body))
            for cell in touched:
                values[cell] = UNKNOWN
            values[logical_ptr] = 0
            continue

        out.append(Loop(optimized_body))
        logical_ptr = 0
        emitted_ptr = 0
        values = {0: 0}
        default_value = UNKNOWN

    flush_move()
    return tuple(out)


def optimize_known_clear_with_stats(code: str) -> tuple[str, dict[str, Any]]:
    original = strip_bf(code)
    nodes = canonicalize(parse(precanonicalize(original)))
    baseline = stringify(nodes)
    stats: dict[str, Any] = {
        "rewritten_known_clears": 0,
        "literal_bytes_saved": 0,
        "rewrites_by_entry_value": {},
    }
    optimized = _optimize_sequence(
        nodes,
        default_value=0,
        initial_values=None,
        stats=stats,
    )
    result = stringify(canonicalize(optimized))
    if len(result) > len(baseline):
        result = baseline
    stats["baseline_bytes"] = len(baseline)
    stats["result_bytes"] = len(result)
    stats["actual_saved_bytes"] = len(baseline) - len(result)
    return result, stats


def optimize_known_clear(code: str) -> str:
    return optimize_known_clear_with_stats(code)[0]


def optimize_region_zero_known_clear_with_stats(code: str) -> tuple[str, dict[str, Any]]:
    region = optimize_region_zero(code)
    result, stats = optimize_known_clear_with_stats(region)
    stats["original_bytes"] = len(strip_bf(code))
    stats["region_zero_bytes"] = len(region)
    stats["combined_bytes"] = len(result)
    stats["incremental_saved_after_region_zero"] = len(region) - len(result)
    stats["total_saved_from_original"] = len(strip_bf(code)) - len(result)
    return result, stats


def profile(path: Path) -> dict[str, Any]:
    raw = strip_bf(path.read_text(encoding="ascii", errors="ignore"))
    _result, stats = optimize_region_zero_known_clear_with_stats(raw)
    return {"name": str(path), **stats}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rows = [profile(Path(p)) for p in args.files]
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        for row in rows:
            print(
                f"{row['name']}: region_zero={row['region_zero_bytes']:,} "
                f"known_clear={row['combined_bytes']:,} "
                f"incremental={row['incremental_saved_after_region_zero']:,} "
                f"rewrites={row['rewritten_known_clears']:,} "
                f"values={row['rewrites_by_entry_value']}"
            )


if __name__ == "__main__":
    main()
