from __future__ import annotations

"""Select the shortest proven payload representation per artifact.

Inputs are profiler JSON files produced by the research workflows. This is a
portfolio selector, not a compressor itself: every candidate must already have
its own exact round-trip / semantic proof obligations. The selector simply
chooses the smallest measured BF-native payload-constructor length per artifact.

Current candidate families:
- bound-macro grammar on original compiler BF;
- relational-macro grammar on original compiler BF;
- relational-macro grammar after the validated local semantic fixed point;
- relational grammar plus affine runs of same-symbol calls;
- relational grammar plus short periodic affine call patterns.

A future final source-size comparison must add the actual decoder/VM source and
cleanup epilogue rather than treating payload-loader length as the complete
program.
"""

import argparse
import json
from pathlib import Path


def load(path: str):
    return json.loads(Path(path).read_text())


def key_by_name(rows):
    return {Path(r["name"]).name: r for r in rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bound", required=True)
    ap.add_argument("--relational", required=True)
    ap.add_argument("--layered", required=True)
    ap.add_argument("--affine-runs", required=True)
    ap.add_argument("--periodic-runs", required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    bound = key_by_name(load(args.bound))
    relational = key_by_name(load(args.relational))
    layered = key_by_name(load(args.layered))
    affine = key_by_name(load(args.affine_runs))
    periodic = key_by_name(load(args.periodic_runs))
    names = sorted(set(bound) & set(relational) & set(layered) & set(affine) & set(periodic))

    rows = []
    for name in names:
        candidates = {
            "bound_raw": int(bound[name]["best"]["best_loader_chars"]),
            "relational_raw": int(relational[name]["best"]["best_loader_chars"]),
            "relational_after_local": int(layered[name]["best"]["best_loader_chars"]),
            "relational_affine_runs": int(affine[name]["best"]["best_loader_chars"]),
            "relational_periodic_runs": int(periodic[name]["best"]["best_loader_chars"]),
        }
        choice = min(candidates, key=candidates.get)
        original = int(relational[name]["bf_bytes"])
        rows.append({
            "name": name,
            "original_bf_bytes": original,
            "candidates": candidates,
            "selected": choice,
            "selected_loader_chars": candidates[choice],
        })

    total = sum(r["original_bf_bytes"] for r in rows)
    selected = sum(r["selected_loader_chars"] for r in rows)
    summary = {
        "artifacts": rows,
        "original_bf_bytes": total,
        "target_10x_chars": total // 10,
        "selected_loader_chars": selected,
        "payload_only_compression_ratio": total / selected,
        "decoder_vm_cleanup_budget_chars": total // 10 - selected,
    }

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(
            f"original={total:,} target10x={total//10:,} selected_loader={selected:,} "
            f"payload_ratio={total/selected:.3f}x "
            f"decoder_vm_cleanup_budget={total//10-selected:,}"
        )
        for r in rows:
            print(
                f"{r['name']}: {r['selected_loader_chars']:,} via {r['selected']} "
                f"{r['candidates']}"
            )


if __name__ == "__main__":
    main()
