from __future__ import annotations

"""Self-extracting byte channel with a tiny standard-BF decoder.

A standalone BF program cannot read its own source, so static compressed bytes
must first be constructed on the tape.  The high-rate prefix16 channel is good
for payload size, but its real BF decoder has nontrivial bit-buffer/state cost.
This experiment provides a deliberately simpler comparison point.

Each byte is split into high/low nibbles.  Nibble n is stored as the balanced
signed byte n-8, so construction of one nibble costs only ``1+abs(n-8)`` BF
characters including the move to the next cell.  Every payload record is:

    [high-8, low-8, live]

with a zero dummy record to the left.  Records are constructed in source order.
The decoder starts at the rightmost live cell and walks right-to-left.  It:

1. consumes the live marker;
2. adds 8 to both encoded nibbles;
3. accumulates ``16*high + low`` into the former live cell;
4. leaves high/low zero;
5. moves to the previous record's live cell.

Thus after decoding each record is ``[0, 0, original_byte]``.  The decoder exits
at pointer 0 after the dummy record.  There is no per-byte dispatcher source:
all bytes share one moving-loop body.

This is not yet the semantic VM.  It measures a realizable point on the
payload-density / decoder-complexity tradeoff and yields a stride-3 byte stream
that a later grammar VM can consume directly.
"""


def shortest_signed_source(value: int) -> str:
    if not -128 <= value <= 127:
        raise ValueError(value)
    if value >= 0:
        return "+" * value
    return "-" * (-value)


def encode_nibble(nibble: int) -> int:
    if not 0 <= nibble < 16:
        raise ValueError(nibble)
    return nibble - 8


def nibble_fragment(nibble: int) -> str:
    """Initialize one fresh zero cell to nibble-8, then advance one cell."""
    return shortest_signed_source(encode_nibble(nibble)) + ">"


# Entry: a real record's live cell.
# Exit: previous record's live cell, so the closing bracket itself performs the
# moving walk.  Current live is reused as the decoded byte accumulator.
#
#   -                         live := 0
#   <<++++++++                high := high + 8
#   >++++++++                 low  := low + 8
#   <[->>++++++++++++++++<<]  live += 16*high; high := 0
#   >[->+<]                   live += low; low := 0
#   <<                        previous live
DECODER = "[-<<++++++++>++++++++<[->>++++++++++++++++<<]>[->+<]<<]"
CLEANUP = "<<"  # dummy live -> dummy first cell
FIXED_DECODER_CHARS = 1 + len(DECODER) + len(CLEANUP)  # initial '<' + body + cleanup


def payload_constructor_chars(blob: bytes) -> int:
    """Exact BF source length without constructing the source string."""
    if not blob:
        return 0
    total = 3  # skip dummy record
    for value in blob:
        high = (value >> 4) - 8
        low = (value & 15) - 8
        # Each signed nibble has abs(value) +/- commands and one '>'.  The
        # record then needs '+>' for its live marker.
        total += abs(high) + 1 + abs(low) + 1 + 2
    return total


def total_channel_chars(blob: bytes) -> int:
    if not blob:
        return 0
    return payload_constructor_chars(blob) + FIXED_DECODER_CHARS


def payload_source(blob: bytes) -> str:
    if not blob:
        return ""
    pieces = [">>>"]  # skip all-zero dummy [0,0,0]
    for value in blob:
        pieces.append(nibble_fragment(value >> 4))
        pieces.append(nibble_fragment(value & 15))
        # Now at fresh live cell.  Mark it and advance to next record's high.
        pieces.append("+>")
    source = "".join(pieces)
    assert len(source) == payload_constructor_chars(blob)
    return source


def build_program(blob: bytes) -> str:
    if not blob:
        return ""
    payload = payload_source(blob)
    # Constructor ends at the cell immediately right of the rightmost live.
    program = payload + "<" + DECODER + CLEANUP
    assert len(program) == total_channel_chars(blob)
    return program


def decoded_cell_index(byte_index: int) -> int:
    """Tape cell containing byte i after successful decoding."""
    return 3 * (byte_index + 1) + 2


def source_accounting(blob: bytes) -> dict[str, int | float]:
    payload_chars = payload_constructor_chars(blob)
    full_chars = total_channel_chars(blob)
    return {
        "bytes": len(blob),
        "payload_constructor_chars": payload_chars,
        "fixed_decoder_chars": FIXED_DECODER_CHARS if blob else 0,
        "total_chars": full_chars,
        "chars_per_byte": (full_chars / len(blob)) if blob else 0.0,
    }
