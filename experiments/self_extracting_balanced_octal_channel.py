from __future__ import annotations

"""Self-extracting mixed-radix 8/8/4 byte channel.

Within the simple family

    split each byte into fixed power-of-two digits;
    encode each digit as a balanced signed fresh-cell value;
    add one live marker per byte;
    decode all records with one moving BF loop,

the uniform-byte constructor cost for a k-bit digit is

    1 + 2**(k-2)

characters on average (one move plus the mean absolute balanced digit value).
Enumerating integer partitions of eight bits gives a minimum of 10 chars/byte,
achieved by bit partitions 3+3+2 and 2+2+2+2.  The former uses fewer tape cells,
so this module implements mixed radix 8/8/4.

Record layout is:

    [top2-2, mid3-4, low3-4, live]

The moving decoder uses Horner evaluation

    ((top * 8) + mid) * 8 + low

and reuses the consumed live marker as the decoded byte.  All digit cells are
zero afterwards.  A zero dummy record on the left terminates the moving loop;
the decoder exits at pointer zero.
"""


def shortest_signed_source(value: int) -> str:
    if value >= 0:
        return "+" * value
    return "-" * (-value)


def digit_fragment(value: int, center: int) -> str:
    return shortest_signed_source(value - center) + ">"


# Entry: live cell of one real record.  Exit: previous record's live cell.
# The closing bracket therefore performs a moving right-to-left walk.
#
# Decode balanced digits, then Horner-fold them toward the live/byte cell:
#   mid += 8*top
#   low += 8*mid
#   live += low
DECODER = "[-<<<++>++++>++++<<[->++++++++<]>[->++++++++<]>[->+<]<<<]"
CLEANUP = "<<<"  # dummy live (cell 3) -> cell 0
FIXED_DECODER_CHARS = 1 + len(DECODER) + len(CLEANUP)


def payload_constructor_chars(blob: bytes) -> int:
    if not blob:
        return 0
    total = 4  # skip dummy record
    for byte in blob:
        top = (byte >> 6) & 0x3
        mid = (byte >> 3) & 0x7
        low = byte & 0x7
        total += abs(top - 2) + 1
        total += abs(mid - 4) + 1
        total += abs(low - 4) + 1
        total += 2  # +> live marker
    return total


def total_channel_chars(blob: bytes) -> int:
    if not blob:
        return 0
    return payload_constructor_chars(blob) + FIXED_DECODER_CHARS


def payload_source(blob: bytes) -> str:
    if not blob:
        return ""
    pieces = [">>>>"]
    for byte in blob:
        pieces.append(digit_fragment((byte >> 6) & 0x3, 2))
        pieces.append(digit_fragment((byte >> 3) & 0x7, 4))
        pieces.append(digit_fragment(byte & 0x7, 4))
        pieces.append("+>")
    source = "".join(pieces)
    assert len(source) == payload_constructor_chars(blob)
    return source


def build_program(blob: bytes) -> str:
    if not blob:
        return ""
    program = payload_source(blob) + "<" + DECODER + CLEANUP
    assert len(program) == total_channel_chars(blob)
    return program


def decoded_cell_index(byte_index: int) -> int:
    return 4 * (byte_index + 1) + 3


def source_accounting(blob: bytes) -> dict[str, int | float]:
    payload = payload_constructor_chars(blob)
    total = total_channel_chars(blob)
    return {
        "bytes": len(blob),
        "payload_constructor_chars": payload,
        "fixed_decoder_chars": FIXED_DECODER_CHARS if blob else 0,
        "total_chars": total,
        "chars_per_byte": (total / len(blob)) if blob else 0.0,
    }
