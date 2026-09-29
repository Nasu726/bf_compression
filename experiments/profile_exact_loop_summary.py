from __future__ import annotations

"""Profile exact-entry opportunities for summarizing flat balanced loops.

Run after the Level-1 region-zero pass.  The profiler follows the same
relative-base dataflow discipline and records cases where a nontrivial flat
balanced arithmetic loop is entered with an exact nonzero 8-bit control value.

For body effect

    control += c
    target[i] += a_i

per iteration, an exact entry x determines termination iff
`gcd(c, 256)` divides x.  In that case the iteration count k is determined
modulo 256/g, and the entire loop has the extensional effect

    control = 0
    target[i] += k * a_i  (mod 256)

with the pointer returning to the control cell.  This lets us estimate a safe
straight-line representative without assuming target entry values.

The cost model is deliberately conservative/simple: shortest +/- literals for
each constant update, min(`[-]`, direct arithmetic) for zeroing the known
control, and the optimal closed walk on the one-dimensional tape through all
nonzero target offsets.
"""

import argparse
import json
import math
from collections import Counter
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


def q(value: int) -> int:
    value &= 255
    return min(value, 256 - value)


def inv_mod_odd(a: int, modulus: int) -> int:
    # After division by gcd(c, 256), the coefficient is odd and invertible.
    return pow(a % modulus, -1, modulus)


def flat_balanced_effect(body: tuple[object, ...]) -> dict[int, int] | None:
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


def closed_route_cost(offsets: list[int]) -> int:
    if not offsets:
        return 0
    lo = min(0, *offsets)
    hi = max(0, *offsets)
    return 2 * (hi - lo)


def summarize_candidate(body: tuple[object, ...], entry: int) -> dict[str, Any] | None:
    coeff = flat_balanced_effect(body)
    if coeff is None:
        return None
    c = coeff.get(0, 0)
    if c == 0 or entry == 0:
        return None
    g = math.gcd(c, 256)
    if entry % g:
        return {
            "terminates": False,
            "gcd": g,
            "entry": entry,
            "control_coeff": c,
        }
    modulus = 256 // g
    k = ((-entry // g) * inv_mod_odd(c // g, modulus)) % modulus
    if k == 0:
        # entry != 0 makes this unreachable when the congruence reasoning above
        # is correct; keep the guard explicit for profiler robustness.
        return None
    targets = {
        off: (coef * k) & 255
        for off, coef in coeff.items()
        if off != 0 and ((coef * k) & 255)
    }
    zero_cost = min(3, q(entry))
    straight_cost = zero_cost + sum(q(v) for v in targets.values()) + closed_route_cost(list(targets))
    original_cost = 2 + len(stringify(body))
    return {
        "terminates": True,
        "gcd": g,
        "entry": entry,
        "iterations": k,
        "control_coeff": c,
        "target_count": len(targets),
        "original_cost": original_cost,
        "straight_cost": straight_cost,
        "saving": max(0, original_cost - straight_cost),
        "profitable": straight_cost < original_cost,
    }


def new_stats() -> dict[str, Any]:
    return {
        "loops_seen": 0,
        "loop_entries_exact_zero": 0,
        "loop_entries_exact_nonzero": 0,
        "loop_entries_unknown": 0,
        "flat_balanced_exact_nonzero": 0,
        "flat_balanced_exact_terminating": 0,
        "flat_balanced_exact_nonterminating": 0,
        "profitable_exact_summaries": 0,
        "estimated_savings": 0,
        "estimated_original_bytes_of_profitable": 0,
        "entry_values": Counter(),
        "iteration_counts": Counter(),
        "savings_histogram": Counter(),
    }


def walk(
    nodes: tuple[object, ...],
    *,
    default_value: int | None,
    initial_values: dict[int, int | None] | None,
    stats: dict[str, Any],
) -> None:
    values: dict[int, int | None] = dict(initial_values or {})
    ptr = 0

    def value_at(cell: int) -> int | None:
        return values[cell] if cell in values else default_value

    for node in nodes:
        if node == ">":
            ptr += 1
            continue
        if node == "<":
            ptr -= 1
            continue
        if node in ("+", "-"):
            cur = value_at(ptr)
            values[ptr] = UNKNOWN if cur is UNKNOWN else (cur + (1 if node == "+" else -1)) & 255
            continue
        if node == ",":
            values[ptr] = UNKNOWN
            continue
        if node == ".":
            continue
        if not isinstance(node, Loop):
            raise AssertionError(node)

        body = canonicalize(node.body)
        cur = value_at(ptr)
        stats["loops_seen"] += 1
        if cur is UNKNOWN:
            stats["loop_entries_unknown"] += 1
        elif cur == 0:
            stats["loop_entries_exact_zero"] += 1
        else:
            stats["loop_entries_exact_nonzero"] += 1
            stats["entry_values"][str(cur)] += 1
            cand = summarize_candidate(body, cur)
            if cand is not None:
                stats["flat_balanced_exact_nonzero"] += 1
                if cand["terminates"]:
                    stats["flat_balanced_exact_terminating"] += 1
                    stats["iteration_counts"][str(cand["iterations"])] += 1
                    if cand["profitable"]:
                        stats["profitable_exact_summaries"] += 1
                        stats["estimated_savings"] += cand["saving"]
                        stats["estimated_original_bytes_of_profitable"] += cand["original_cost"]
                        stats["savings_histogram"][str(cand["saving"])] += 1
                else:
                    stats["flat_balanced_exact_nonterminating"] += 1

        # A loop whose control is exactly zero is skipped.  Level 1 should have
        # removed these already, but modeling it makes the profiler standalone.
        if cur == 0:
            continue

        # Recurse with unknown iteration-entry state: the exact outer first-entry
        # value cannot be reused on subsequent iterations.
        walk(body, default_value=UNKNOWN, initial_values=None, stats=stats)

        delta = body_static_delta(body)
        if delta == 0:
            _end, touched = balanced_effects(body, ptr)
            for cell in touched:
                values[cell] = UNKNOWN
            values[ptr] = 0
        else:
            # Relative-base barrier after normal loop exit.
            ptr = 0
            values = {0: 0}
            default_value = UNKNOWN


def profile(path: Path) -> dict[str, Any]:
    raw = strip_bf(path.read_text(encoding="ascii", errors="ignore"))
    level1 = optimize_region_zero(raw)
    nodes = canonicalize(parse(precanonicalize(level1)))
    stats = new_stats()
    walk(nodes, default_value=0, initial_values=None, stats=stats)
    for key in ("entry_values", "iteration_counts", "savings_histogram"):
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
                f"{row['name']}: exact_nonzero={row['loop_entries_exact_nonzero']:,} "
                f"flat={row['flat_balanced_exact_nonzero']:,} "
                f"profitable={row['profitable_exact_summaries']:,} "
                f"estimated_saved={row['estimated_savings']:,}"
            )


if __name__ == "__main__":
    main()
