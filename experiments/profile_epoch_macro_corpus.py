from __future__ import annotations

"""Bounded opportunity study for epoch-aware nonadjacent BF source sharing.

The pass compiles its candidate as *actual runnable standard BF* with a
local-zero proof; if no supported region is found, it returns the original
without changing a character. This profile is intentionally restricted to
the root lexical scope and bounded atom groups. The result is a measured
lower bound on achievable savings from this particular implementation,
not an upper bound on all recursive/source-sharing methods.
"""

import argparse
import json
from pathlib import Path

from mine_epoch_nonadjacent_macro import lexical_epochs, mine_epoch_macros


def profile(path: Path):
    bf="".join(ch for ch in path.read_text(encoding="ascii",errors="ignore") if ch in "><+-.,[]")
    max_atoms=2_500
    epochs=lexical_epochs(bf)
    eligible=sum(1 for atoms,_,_ in epochs if len(atoms)<=max_atoms)
    candidate=mine_epoch_macros(
        bf, max_atoms_per_epoch=max_atoms, max_period=128,
        max_groups_per_epoch=8, max_calls=5, min_macro_chars=60
    )
    assert len(candidate.source)<=len(bf)
    return {
        "name": str(path),
        "baseline_chars": len(bf),
        "candidate_chars": candidate.result_chars,
        "saved_chars": candidate.saved_chars,
        "selected": candidate.selected,
        "macro_chars": candidate.macro_chars,
        "macro_calls": candidate.call_count,
        "root_epochs": len(epochs),
        "bounded_eligible_root_epochs": eligible,
        "inspected_repeat_groups": candidate.considered_groups,
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("files",nargs="+")
    p.add_argument("--json",action="store_true")
    args=p.parse_args()
    rows=[profile(Path(path)) for path in args.files]
    if args.json:
        print(json.dumps(rows,indent=2,sort_keys=True))
    else:
        total=sum(x["baseline_chars"] for x in rows)
        saved=sum(x["saved_chars"] for x in rows)
        print(f"epoch-macro corpus total={total:,}; saved={saved:,}; result={total-saved:,}; saved_ratio={saved/total:.6%}")
        for row in rows:
            print(
                f"{row['name']}: {row['baseline_chars']:,}->{row['candidate_chars']:,}; "
                f"saved={row['saved_chars']:,}, selected={row['selected']}; "
                f"root_epochs={row['root_epochs']}, "
                f"bounded_eligible={row['bounded_eligible_root_epochs']}; "
                f"groups={row['inspected_repeat_groups']}"
            )


if __name__=="__main__":
    main()
