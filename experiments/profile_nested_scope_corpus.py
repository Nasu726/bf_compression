from __future__ import annotations

"""Measure proof-gated nested lexical-scope sharing on real BF artifacts.

A bounded root-scope study previously saved zero characters on the seven
compiler outputs. This extends the runnable-source transformation search
into nested loops with UNKNOWN initial tape, retaining only candidates
whose scratch precondition can be proven. It is not a lower bound on
unrestricted grammar compression or a complete search of all scopes.
"""

import argparse
import json
from pathlib import Path

from mine_nested_scope_macro import mine_nested_once


def profile(path: Path, max_scopes: int):
    raw = "".join(ch for ch in path.read_text(
        encoding="ascii", errors="ignore"
    ) if ch in "><+-.,[]")
    result = mine_nested_once(raw, max_scopes=max_scopes)
    assert result.result_chars <= result.original_chars
    return {
        "name": str(path),
        "original_chars": len(raw),
        "result_chars": len(result.source),
        "saved_chars": result.saved_chars,
        "eligible_lexical_loops": result.lexical_loops,
        "considered_scopes": result.considered_scopes,
        "selected": result.selected,
        "selected_scope_depth": result.chosen_depth,
        "selected_scope_body_chars": result.chosen_body_chars,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--max-scopes", type=int, default=72)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rows = [profile(Path(path), args.max_scopes) for path in args.files]
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        total = sum(r["original_chars"] for r in rows)
        result = sum(r["result_chars"] for r in rows)
        print(f"nested scope runnable BF: {total:,}->{result:,}; "
              f"saved={total-result:,} ({(total-result)/total:.4%})")
        for row in rows:
            print(f"{row['name']}: {row['original_chars']:,}->"
                  f"{row['result_chars']:,}; "
                  f"loops={row['eligible_lexical_loops']:,}; "
                  f"checked={row['considered_scopes']:,}")


if __name__ == "__main__":
    main()
