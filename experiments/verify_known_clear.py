from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from known_clear_opt import optimize_region_zero_known_clear_with_stats
from verify_region_zero import run


def same(code: str, inputs=(b"", b"A")) -> None:
    optimized, _stats = optimize_region_zero_known_clear_with_stats(code)
    assert len(optimized) <= len(code), (code, optimized)
    for eof in ("nochange", "255", "0"):
        for data in inputs:
            a = run(code, data, eof=eof)
            b = run(optimized, data, eof=eof)
            assert a == b, (code, optimized, eof, data, a, b)


def main() -> None:
    # Exact small values make a 3-byte clear longer than direct arithmetic.
    for code in ("+[-]", "++[-]", "--[-]", "-[-]"):
        same(code)
        optimized, stats = optimize_region_zero_known_clear_with_stats(code)
        assert len(optimized) < len(code), (code, optimized, stats)

    # Unknown input must keep the generic clear loop.
    optimized, stats = optimize_region_zero_known_clear_with_stats(",[-]")
    assert "[-]" in optimized, (optimized, stats)
    same(",[-]", inputs=(b"", b"\x00", b"\x01", b"\xff"))

    # A moving-loop exit starts a fresh relative epoch with current cell zero;
    # after a known +1, the following clear can collapse with that increment.
    same("+[>]+[-]")

    # Body-local exact facts may shorten later clears, but the body is analyzed
    # with unknown iteration-entry state, so one-time outer facts are not reused
    # unsafely on subsequent iterations.
    same("+[[ - ]+[-]>]".replace(" ", ""))

    # Multiple barriers/epochs should compose without recovering stale absolute
    # addresses.
    same("+[>]+[-]+[>>]--[-]")

    print("known-clear differential checks: OK")


if __name__ == "__main__":
    main()
