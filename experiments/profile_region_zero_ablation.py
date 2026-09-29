from __future__ import annotations

"""Ablation: relative-base known-zero analysis at lexical depth 0 only.

This intentionally leaves every loop body unchanged. Comparing it with the full
recursive pass isolates how much of the measured gain comes from applying the
same dataflow inside loop bodies rather than merely surviving moving barriers at
the outer level.
"""

import argparse
import json
from pathlib import Path
import sys

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


def optimize_shallow(code: str) -> str:
    nodes = canonicalize(parse(precanonicalize(strip_bf(code))))
    baseline = stringify(nodes)
    values: dict[int, int | None] = {}
    logical_ptr = 0
    emitted_ptr = 0
    out: list[object] = []
    default_value: int | None = 0

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
            values[logical_ptr] = (
                (cur + (1 if node == "+" else -1)) & 255
                if cur is not UNKNOWN else UNKNOWN
            )
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
        if cur == 0:
            continue

        flush_move()
        if body == ("-",):
            out.append(Loop(("-",)))
            values[logical_ptr] = 0
            continue

        delta = body_static_delta(body)
        if delta == 0:
            _end, touched = balanced_effects(body, logical_ptr)
            out.append(Loop(body))
            for cell in touched:
                values[cell] = UNKNOWN
            values[logical_ptr] = 0
            continue

        out.append(Loop(body))
        logical_ptr = 0
        emitted_ptr = 0
        values = {0: 0}
        default_value = UNKNOWN

    flush_move()
    result = stringify(canonicalize(tuple(out)))
    return result if len(result) <= len(baseline) else baseline


def profile(path: Path) -> dict:
    raw = strip_bf(path.read_text(encoding="ascii", errors="ignore"))
    shallow = optimize_shallow(raw)
    full = optimize_region_zero(raw)
    return {
        "name": str(path),
        "baseline_bytes": len(raw),
        "shallow_bytes": len(shallow),
        "full_recursive_bytes": len(full),
        "shallow_saved": len(raw) - len(shallow),
        "full_saved": len(raw) - len(full),
        "additional_recursive_saved": len(shallow) - len(full),
        "recursive_share_of_total_percent": (
            100.0 * (len(shallow) - len(full)) / (len(raw) - len(full))
            if len(raw) != len(full) else 0.0
        ),
    }


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
                f"{row['name']}: baseline={row['baseline_bytes']:,} "
                f"shallow={row['shallow_bytes']:,} full={row['full_recursive_bytes']:,} "
                f"shallow_saved={row['shallow_saved']:,} "
                f"additional_recursive={row['additional_recursive_saved']:,} "
                f"recursive_share={row['recursive_share_of_total_percent']:.2f}%"
            )


if __name__ == "__main__":
    main()
