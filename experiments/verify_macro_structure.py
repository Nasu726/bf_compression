from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_macro_structure import profile_code


def main() -> None:
    # Two identical balanced loop atoms form an exact tandem repeat.
    row = profile_code("[->+<][->+<]")
    assert row["literal_reroll"]["reroll_incremental_saved_bytes"] == 6, row
    assert row["semantic_reroll"]["reroll_incremental_saved_bytes"] == 6, row

    # These loops use different odd control generators but implement the same
    # terminating affine transfer x1 += x0; x0 = 0 over 8-bit cells.
    row = profile_code("[->+<][+>-<]")
    assert row["literal_reroll"]["reroll_incremental_saved_bytes"] == 0, row
    assert row["semantic_reroll"]["reroll_incremental_saved_bytes"] == 6, row

    # Straight arithmetic is canonicalized before atom matching; a run of plus
    # bytes is one ADD atom rather than fake repetition opportunity.
    row = profile_code("++++++++")
    assert row["semantic_reroll"]["reroll_incremental_saved_bytes"] == 0, row

    # Repeated pointer movement is not rerollable under the balanced-body gate.
    row = profile_code(">>>>>>>>" )
    assert row["semantic_reroll"]["reroll_incremental_saved_bytes"] == 0, row

    # Nested compression must not be credited twice.  Two identical loops each
    # contain the same internal tandem; outer reroll may discard one already-
    # compressed loop but the reported final cost must stay non-negative and no
    # larger than the canonical source.
    row = profile_code("[>+<- >+<-][>+<- >+<-]")
    assert row["semantic_reroll"]["optimistic_result_bytes_if_free_reroll"] >= 0, row
    assert row["semantic_reroll"]["optimistic_result_bytes_if_free_reroll"] <= row["canonical_ast_bytes"], row

    print("macro-structure profiler checks: OK")


if __name__ == "__main__":
    main()
