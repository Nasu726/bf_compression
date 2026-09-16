from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from region_zero_opt import (
    canonicalize,
    optimize_region_zero,
    parse,
    precanonicalize,
    stringify,
    strip_bf,
)


def profile(path: Path) -> dict[str, int | float | str]:
    source = path.read_text(encoding="ascii", errors="ignore")
    raw = strip_bf(source)
    baseline = stringify(canonicalize(parse(precanonicalize(raw))))
    optimized = optimize_region_zero(raw)
    saved = len(baseline) - len(optimized)
    return {
        "name": str(path),
        "bf_bytes": len(raw),
        "canonical_bytes": len(baseline),
        "region_zero_bytes": len(optimized),
        "saved_vs_canonical": saved,
        "saved_percent_vs_canonical": (100.0 * saved / len(baseline)) if baseline else 0.0,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rows = [profile(Path(p)) for p in args.files]
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            print(
                f"{row['name']}: canonical={row['canonical_bytes']:,} "
                f"region_zero={row['region_zero_bytes']:,} "
                f"saved={row['saved_vs_canonical']:,} "
                f"({row['saved_percent_vs_canonical']:.3f}%)"
            )


if __name__ == "__main__":
    main()
