from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_dead_straight_writes import profile_code
from verify_region_zero import run


def same(code: str, inputs=(b"", b"A")):
    candidate, stats = profile_code(code)
    assert len(candidate) <= len(code), (code, candidate, stats)
    for eof in ("nochange", "255", "0"):
        for data in inputs:
            a = run(code, data, eof=eof)
            b = run(candidate, data, eof=eof)
            assert a == b, (code, candidate, eof, data, a, b, stats)
    return candidate, stats


def main() -> None:
    candidate, stats = same("+++[-]")
    assert stats["proved_dead_arithmetic_bytes"] == 3, (candidate, stats)
    assert stats["canonicalized_candidate_saved_bytes"] >= 3, (candidate, stats)

    # Output from the same cell observes the value and blocks deletion.
    candidate, stats = same("+++.[-]")
    assert stats["proved_dead_arithmetic_bytes"] == 0, (candidate, stats)

    # Input on the same cell is conservative because EOF-no-change can depend
    # on the old value; do not treat comma as an unconditional overwrite.
    candidate, stats = same("+++ ,[-]", inputs=(b"", b"\x00", b"A", b"\xff"))
    assert stats["proved_dead_arithmetic_bytes"] == 0, (candidate, stats)

    # A clear on another cell is safe to cross on the way to the target kill.
    candidate, stats = same(">+++<[-]>[-]")
    assert stats["proved_dead_arithmetic_bytes"] == 3, (candidate, stats)

    # I/O on another cell is observable but independent of the dead value.
    candidate, stats = same("+++>.<[-]")
    assert stats["proved_dead_arithmetic_bytes"] == 3, (candidate, stats)

    # A genuine non-clear transfer loop is an analysis barrier in this first
    # experiment.  `[+]` is intentionally not used here: on 8-bit wrapping
    # cells it is itself a clear loop and canonicalizes to `[-]`.
    candidate, stats = same("+++>+[->+<]<[-]")
    assert stats["proved_dead_arithmetic_bytes"] == 0, (candidate, stats)

    # Nested lexical scopes are analyzed recursively; the outer control update
    # at the end remains live while the inner-cell arithmetic is killed.
    candidate, stats = same("++[>+++[-]<-]")
    assert stats["proved_dead_arithmetic_bytes"] == 3, (candidate, stats)

    print("dead-straight-write opportunity checks: OK")


if __name__ == "__main__":
    main()
