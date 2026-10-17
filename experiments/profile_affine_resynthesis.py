from __future__ import annotations

"""Measure exact-map affine loop resynthesis on compiler-generated BF corpus."""

import argparse
import json
from pathlib import Path
import re

from affine_loop_resynthesis import (
    optimize_affine_flat_loops,
    profile_flat_body,
    resynthesize_flat_loop,
)


def profile_text(raw: str):
    bf = "".join(ch for ch in raw if ch in "><+-.,[]")
    loops = list(re.finditer(r"\[[^\[\]]*\]", bf))
    eligible = 0
    changed = 0
    local_savings = 0
    max_saving = 0
    for m in loops:
        loop = m.group()
        if profile_flat_body(loop[1:-1]) is None:
            continue
        eligible += 1
        new = resynthesize_flat_loop(loop)
        saving = len(loop) - len(new)
        if saving > 0:
            changed += 1
            local_savings += saving
            max_saving = max(max_saving, saving)
    optimized = optimize_affine_flat_loops(bf)
    assert len(bf) - len(optimized) == local_savings
    # Strict-shrink/idempotence checks make all profiles self-contained.
    assert len(optimized) <= len(bf)
    assert optimize_affine_flat_loops(optimized) == optimized
    return {
        "baseline_bytes": len(bf),
        "rewritten_bytes": len(optimized),
        "saved_bytes": local_savings,
        "fraction_saved": local_savings / len(bf) if bf else 0.0,
        "flat_loops": len(loops),
        "eligible_odd_control_loops": eligible,
        "changed_loops": changed,
        "largest_single_loop_saving": max_saving,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    rows = []
    for filename in args.files:
        p = Path(filename)
        rows.append({"name": str(p), **profile_text(p.read_text(encoding="ascii", errors="ignore"))})
    if args.json:
        print(json.dumps(rows, sort_keys=True, indent=2))
    else:
        for row in rows:
            print(
                f"{row['name']}: "
                f"{row['baseline_bytes']:,}->{row['rewritten_bytes']:,}; "
                f"saved={row['saved_bytes']:,} ({row['fraction_saved']:.3%}); "
                f"changed={row['changed_loops']:,}/{row['eligible_odd_control_loops']:,}"
            )


if __name__ == "__main__":
    main()
