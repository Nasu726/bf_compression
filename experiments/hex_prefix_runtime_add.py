from __future__ import annotations

"""Runtime-lane DATA->TOTAL add for the stored-prefix specialization.

In the current prefix reader, original DATA is dead immediately after it has
been added into TOTAL: `_split_total_into_prefix_and_next` overwrites DATA with
the inclusive prefix sum.  LEFT is also scratch at this point.  We can exploit
both facts to replace sixteen statically emitted nibble add/mapping blocks with
one moving BF loop over lanes 1..14 plus two endpoint blocks.

LEFT[i] serves two roles at disjoint times:
- before lane i executes: a one-bit traversal marker;
- after lane i executes: the radix carry consumed by lane i+1.

Postcondition: TOTAL = old TOTAL + old DATA mod 2**64, DATA is zero, LEFT is
zero. ANS/BACK/record marker are untouched.  This is intentionally specific to
the stored-prefix reader; it is not a drop-in replacement where DATA must live.
"""

from bfhexradixfast import map_total_base16_threshold
from bfhexseq import DATA, HEX_DIGITS, LEFT, TOTAL, _RelativeBuilder


def _lane_add(
    r: _RelativeBuilder,
    i: int,
    *,
    carry_in: int | None,
    carry_out: int,
) -> None:
    data = DATA + i
    total = TOTAL + i
    # Consume TOTAL into already-live DATA. Values stay <= 30 before carry.
    r.transfer(total, data)
    if carry_in is not None:
        r.transfer(carry_in, data)
    map_total_base16_threshold(r, data, total, carry_out)


def destructive_add_data_to_total_runtime(r: _RelativeBuilder) -> None:
    # Endpoint zero has no incoming carry. LEFT[0] is initially zero scratch.
    r.clear(LEFT)
    _lane_add(r, 0, carry_in=None, carry_out=LEFT)

    # Pre-arm lanes 1..14. LEFT[15] is the zero sentinel for the moving loop;
    # lane 15 is handled once after the loop to avoid needing a 17th marker.
    for i in range(1, HEX_DIGITS - 1):
        r.set_const(LEFT + i, 1)
    r.clear(LEFT + HEX_DIGITS - 1)

    # Build one generic body relative to current LEFT[i]. The physical layout
    # keeps DATA/TOTAL/LEFT as equal-width contiguous 16-cell blocks, so all
    # field offsets are invariant while the loop walks one cell right per lane.
    body = _RelativeBuilder()
    body.clear(0)  # consume traversal marker; this cell will receive carry-out
    data = DATA - LEFT
    total = TOTAL - LEFT
    prev_carry = -1
    body.transfer(total, data)
    body.transfer(prev_carry, data)
    map_total_base16_threshold(body, data, total, 0)
    body.move(1)

    r.move(LEFT + 1)
    r.emit("[" + body.code() + "]")
    r.pos = LEFT + HEX_DIGITS - 1

    # Final lane consumes carry from lane 14 and discards fixed-width overflow.
    _lane_add(
        r,
        HEX_DIGITS - 1,
        carry_in=LEFT + HEX_DIGITS - 2,
        carry_out=LEFT + HEX_DIGITS - 1,
    )
    r.clear(LEFT + HEX_DIGITS - 1)
    r.move(0)


__all__ = ["destructive_add_data_to_total_runtime"]
