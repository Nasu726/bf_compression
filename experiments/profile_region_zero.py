from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from region_zero_opt import optimize_region_zero_with_stats, strip_bf


def profile(path: Path) -> dict:
    source = path.read_text(encoding="ascii", errors="ignore")
    raw = strip_bf(source)
    optimized, stats = optimize_region_zero_with_stats(raw)
    baseline = stats["canonical_bytes"]
    saved = stats["saved_vs_canonical"]
    return {
        "name": str(path),
        "bf_bytes": len(raw),
        "canonical_bytes": baseline,
        "region_zero_bytes": len(optimized),
        "saved_vs_canonical": saved,
        "saved_percent_vs_canonical": (100.0 * saved / baseline) if baseline else 0.0,
        "removed_known_zero_loops": stats["removed_known_zero_loops"],
        "removed_known_zero_loop_bytes": stats["removed_known_zero_loop_bytes"],
        "moving_barriers_emitted": stats["moving_barriers_emitted"],
        "balanced_loops_emitted": stats["balanced_loops_emitted"],
        "removed_by_origin": stats["removed_by_origin"],
        "removed_bytes_by_origin": stats["removed_bytes_by_origin"],
        "removed_by_loop_kind": stats["removed_by_loop_kind"],
        "removed_bytes_by_loop_kind": stats["removed_bytes_by_loop_kind"],
        "original_loop_kinds": stats["original_loop_kinds"],
        "loop_kind_transitions": stats["loop_kind_transitions"],
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
                f"{row['name']}: canonical={row['canonical_bytes']:,} "
                f"region_zero={row['region_zero_bytes']:,} "
                f"saved={row['saved_vs_canonical']:,} "
                f"({row['saved_percent_vs_canonical']:.3f}%) "
                f"removed_loops={row['removed_known_zero_loops']:,} "
                f"origins={row['removed_by_origin']} "
                f"kinds={row['removed_by_loop_kind']} "
                f"transitions={row['loop_kind_transitions']}"
            )


if __name__ == "__main__":
    main()
