from __future__ import annotations

"""Measure which physical tape distances dominate emitted pointer routing.

The 10x track found that >92% of compiler BF is `<`/`>`.  This profiler counts
canonical contiguous movement runs by signed displacement and by absolute
length, split into static/periodic/dynamic structural contexts.  Peaks at known
ABI widths (for example 99-cell Quad words or 66-cell sequence records) show
that source size is exposing representation width directly.
"""

import argparse
import json
from collections import Counter
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from region_zero_opt import Loop, body_static_delta, canonicalize, parse, precanonicalize, strip_bf


def loop_kind(body):
    delta = body_static_delta(body)
    if delta is None:
        return "dynamic"
    return "balanced" if delta == 0 else "moving"


def child_context(parent: str, kind: str) -> str:
    if parent == "dynamic" or kind == "dynamic":
        return "dynamic"
    if parent == "periodic" or kind == "moving":
        return "periodic"
    return "static"


def profile_code(text: str) -> dict:
    nodes = canonicalize(parse(precanonicalize(strip_bf(text))))
    abs_hist = {c: Counter() for c in ("static", "periodic", "dynamic")}
    signed_hist = {c: Counter() for c in ("static", "periodic", "dynamic")}

    def walk(seq, context: str):
        signed = 0

        def flush():
            nonlocal signed
            if signed:
                abs_hist[context][abs(signed)] += 1
                signed_hist[context][signed] += 1
                signed = 0

        for node in seq:
            if node == ">":
                signed += 1
            elif node == "<":
                signed -= 1
            else:
                flush()
                if isinstance(node, Loop):
                    body = canonicalize(node.body)
                    walk(body, child_context(context, loop_kind(body)))
        flush()

    walk(nodes, "static")

    def summarize(counter: Counter, limit=40):
        return [
            {"distance": int(distance), "runs": runs, "movement_bytes": abs(int(distance)) * runs}
            for distance, runs in sorted(
                counter.items(), key=lambda kv: (abs(int(kv[0])) * kv[1], kv[1]), reverse=True
            )[:limit]
        ]

    result = {}
    for context in ("static", "periodic", "dynamic"):
        result[context] = {
            "top_absolute_by_byte_mass": summarize(abs_hist[context]),
            "top_signed_by_byte_mass": summarize(signed_hist[context]),
            "distinct_absolute_distances": len(abs_hist[context]),
            "runs": sum(abs_hist[context].values()),
            "movement_bytes": sum(d * n for d, n in abs_hist[context].items()),
        }
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rows = []
    for name in args.files:
        path = Path(name)
        rows.append({"name": str(path), **profile_code(path.read_text(encoding="ascii", errors="ignore"))})
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        for row in rows:
            print(row["name"])
            for context in ("static", "periodic", "dynamic"):
                top = row[context]["top_absolute_by_byte_mass"][:10]
                print(context, [(x["distance"], x["runs"], x["movement_bytes"]) for x in top])


if __name__ == "__main__":
    main()
