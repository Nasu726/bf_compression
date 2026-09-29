from __future__ import annotations

"""A first self-contained compressed-BF execution kernel.

This intentionally implements only one semantic family: an input-independent
byte-output island.  The point is not that constant output is the final VM, but
that the compressed payload is *actually constructed and executed by standard
Brainfuck*, while the payload, executor scratch, final pointer, and final tape
state are all cleaned back to the reference state.

Payload layout
--------------

Cell 0..2 is a zero dummy record.  Every real record has three cells:

    [accumulator, delta, live-flag]

Records are written in reverse execution order.  The executor starts at the
rightmost flag and walks records right-to-left.  In one fixed BF loop body it:

1. clears the current live flag;
2. destructively adds ``delta`` to the current accumulator;
3. emits the accumulator byte;
4. transfers the accumulator three cells left into the next record;
5. lands on that record's live flag for the next loop test.

The final transfer lands in dummy accumulator cell 0; after the loop that cell
is cleared and the data pointer is restored to cell 0.  Thus all payload cells
are zero after execution.

This is a deliberately tiny example of the runtime-lane / moving-state idea
needed by the full compressed semantic VM.
"""


def shortest_delta_source(value: int) -> str:
    """Shortest +/- spelling of one byte value from a known-zero cell."""
    value &= 255
    if value <= 128:
        return "+" * value
    return "-" * (256 - value)


def output_deltas(data: bytes) -> list[int]:
    previous = 0
    out: list[int] = []
    for value in data:
        out.append((value - previous) & 255)
        previous = value
    return out


def reference_program(data: bytes) -> str:
    """Direct zero-initialized BF spelling with the same final zero tape."""
    if not data:
        return ""
    pieces: list[str] = []
    for delta in output_deltas(data):
        pieces.append(shortest_delta_source(delta))
        pieces.append(".")
    pieces.append("[-]")
    return "".join(pieces)


# The executor body is independent of payload length and values.
# It starts on a live-flag cell and exits on the dummy record's zero flag.
EXECUTOR = "[-<[-<+>]<.[<<<+>>>]<]"
CLEANUP = "<<[-]"


def payload_source(data: bytes) -> str:
    """Construct reversed three-cell records, ending just right of the payload."""
    if not data:
        return ""
    pieces = [">>>"]  # skip the all-zero dummy record
    # Execution walks right-to-left, so physical records are reversed.
    for delta in reversed(output_deltas(data)):
        pieces.append(">")  # accumulator -> delta
        pieces.append(shortest_delta_source(delta))
        pieces.append(">+>")  # delta -> live flag (=1) -> next accumulator
    return "".join(pieces)


def build_program(data: bytes) -> str:
    if not data:
        return ""
    # payload_source ends one cell right of the rightmost live flag.
    return payload_source(data) + "<" + EXECUTOR + CLEANUP


def source_accounting(data: bytes) -> dict[str, int]:
    payload = payload_source(data)
    full = build_program(data)
    return {
        "bytes_out": len(data),
        "payload_constructor_chars": len(payload),
        "executor_chars": 1 + len(EXECUTOR) + len(CLEANUP),
        "total_chars": len(full),
        "reference_chars": len(reference_program(data)),
    }
