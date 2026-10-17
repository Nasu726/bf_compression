from __future__ import annotations

"""Self-contained, self-cleaning BF executor with fused balanced-nibble ADD.

Limited single-logical-cell ISA: ADD(byte), OUT, CLEAR.  A seven-cell
record stores [state, high-8, low-8, add_flag, out_flag, clear_flag, live].
Records are emitted in reverse execution order after a seven-cell zero
dummy.  The executor moves right-to-left over live flags and consumes all
metadata.  Its final state is cell 0, with pointer zero and every other
cell zero.

Crucially, ADD operands are never expanded into an intermediate byte
stream.  The moving dispatcher adds eight to each encoded signed nibble,
then transfers 16*high+low directly into logical state.  This avoids both
the direct 0..255 unary initializer and a separate byte decoder.

This is a constrained proof-of-concept, not a general BF interpreter: it
does not implement MOVE, INPUT, branching, or an arbitrary initial tape.
"""

from typing import Iterable

from self_extracting_linear_vm import Op, reference_program

WIDTH = 7

# Entry/exit: current live flag (record offset 6) -> preceding live flag.
#
# CLEAR flag at offset 5, OUT at 4, ADD at 3.  ADD's scratch nibble
# cells are at offsets 1 and 2.  The state is offset 0.  All cells are
# consumed; state transfers to preceding record state seven cells left.
ADD_DISPATCH = "[-<<++++++++>++++++++<[-<++++++++++++++++>]>[-<<+>>]>]"
EXECUTOR = (
    "["
    "-"                         # live := 0
    "<[-<<<<<[-]>>>>>]"         # CLEAR flag: clear logical state
    "<[-<<<<.>>>>]"             # OUT flag: print logical state
    "<" + ADD_DISPATCH         # ADD: decode and add nibble pair
    + "<<<[-<<<<<<<+>>>>>>>]<" # state -> previous state; previous live
    + "]"
)
CLEANUP = "<" * 6             # dummy live -> materialized cell 0


def signed_initializer(value: int) -> str:
    value &= 255
    return "+" * value if value <= 128 else "-" * (256 - value)


def nibble_initializer(nibble: int) -> str:
    assert 0 <= nibble < 16
    return signed_initializer((nibble - 8) & 255)


def payload_source(ops: Iterable[Op]) -> str:
    seq = list(ops)
    if not seq:
        return ""
    pieces = [">" * WIDTH]  # all-zero dummy record
    for op in reversed(seq):
        if op.kind not in ("A", "O", "C"):
            raise ValueError(op)
        pieces.append(">")     # high nibble
        if op.kind == "A":
            pieces.append(nibble_initializer((op.arg & 255) >> 4))
        pieces.append(">")     # low nibble
        if op.kind == "A":
            pieces.append(nibble_initializer(op.arg & 15))
        pieces.append(">")     # add flag
        if op.kind == "A":
            pieces.append("+")
        pieces.append(">")     # output flag
        if op.kind == "O":
            pieces.append("+")
        pieces.append(">")     # clear flag
        if op.kind == "C":
            pieces.append("+")
        pieces.append(">+>")   # live := 1; next record state
    return "".join(pieces)


def build_program(ops: Iterable[Op]) -> str:
    seq = list(ops)
    if not seq:
        return ""
    return payload_source(seq) + "<" + EXECUTOR + CLEANUP


def source_accounting(ops: Iterable[Op]) -> dict[str, int]:
    seq = list(ops)
    constructed = payload_source(seq)
    program = build_program(seq)
    return {
        "operations": len(seq),
        "reference_chars": len(reference_program(seq)),
        "payload_constructor_chars": len(constructed),
        "fixed_executor_chars": 1 + len(EXECUTOR) + len(CLEANUP) if seq else 0,
        "total_chars": len(program),
    }


def cheapest_verified_family(ops: Iterable[Op]) -> tuple[str, str]:
    """Portfolio of directly executable, independently verified BF families."""
    from self_extracting_linear_vm import build_program as legacy_vm

    seq = list(ops)
    options = {
        "literal": reference_program(seq),
        "direct_byte_vm": legacy_vm(seq),
        "fused_nibble_vm": build_program(seq),
    }
    family = min(options, key=lambda name: len(options[name]))
    return family, options[family]
