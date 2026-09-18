from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from region_zero_opt import optimize_region_zero_with_stats, strip_bf


def profile(path: Path, max_passes: int) -> dict:
    current = strip_bf(path.read_text(encoding="ascii", errors="ignore"))
    initial = len(current)
    passes = []
    for i in range(1, max_passes + 1):
        nxt, stats = optimize_region_zero_with_stats(current)
        saved = len(current) - len(nxt)
        passes.append({
            "pass": i,
            "input_bytes": len(current),
            "output_bytes": len(nxt),
            "saved_bytes": saved,
            "removed_known_zero_loops": stats["removed_known_zero_loops"],
            "moving_barriers_emitted": stats["moving_barriers_emitted"],
            "loop_kind_transitions": stats["loop_kind_transitions"],
        })
        if nxt == current:
            current = nxt
            break
        current = nxt
    return {
        "name": str(path),
        "initial_bytes": initial,
        "fixedpoint_bytes": len(current),
        "total_saved_bytes": initial - len(current),
        "total_saved_percent": (100.0 * (initial - len(current)) / initial) if initial else 0.0,
        "passes": passes,
        "converged": bool(passes and passes[-1]["saved_bytes"] == 0),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--max-passes", type=int, default=8)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rows = [profile(Path(p), args.max_passes) for p in args.files]
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        for row in rows:
            savings = [p["saved_bytes"] for p in row["passes"]]
            print(
                f"{row['name']}: {row['initial_bytes']:,} -> {row['fixedpoint_bytes']:,} "
                f"saved={row['total_saved_bytes']:,} ({row['total_saved_percent']:.3f}%) "
                f"pass_savings={savings} converged={row['converged']}"
            )


if __name__ == "__main__":
    main()
