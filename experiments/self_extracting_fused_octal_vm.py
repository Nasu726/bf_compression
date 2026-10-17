from __future__ import annotations

"""Fused radix-8/8/4 ADD decoder and self-cleaning straight-line BF VM.

One logical data cell supports A(delta), O, C.  The opcode-record layout,
from left to right, is

  [state, top2-2, mid3-4, low3-4, add_flag, out_flag, clear_flag, live]

with an all-zero dummy record on the left and real records stored in reverse
execution order.  The runtime body decodes its three balanced octal digits
straight into state by Horner evaluation, then consumes flags and transfers
state into the previous record.  No intermediate byte stream is materialized.
All scratch cells are zero and pointer is 0 upon termination.

This code assumes standard 8-bit wrapping cells and a zero-initialized tape.
It is not a complete interpreter for all eight Brainfuck commands.
"""

from typing import Iterable

from self_extracting_linear_vm import Op, reference_program

WIDTH = 8

# Entry: record ADD flag (offset 4); exit at the same flag.
# Top, mid, low are offsets 1,2,3; state is offset 0.
# 1. Restore balanced digits: top += 2, mid += 4, low += 4.
# 2. Horner: mid += 8*top; low += 8*mid; state += low.
# 3. All three digit cells and ADD flag are consumed.
ADD_DISPATCH = "[-<<<++>++++>++++<<[->++++++++<]>[->++++++++<]>[-<<<+>>>]>]"

# Entry/exit: record live flag (offset 7) -> previous record live flag.
EXECUTOR = (
    "["
    "-"                            # live := 0
    "<[-<<<<<<[-]>>>>>>]"          # clear flag (6) -> state (0)
    "<[-<<<<<.>>>>>]"              # out flag (5) -> state (0)
    "<" + ADD_DISPATCH            # add flag (4), consumes encoded digits
    + "<<<<[-<<<<<<<<+>>>>>>>>]<" # transfer state to previous record
    + "]"
)
CLEANUP = "<" * 7                 # dummy live -> materialized cell 0


def signed_initializer(value: int) -> str:
    value &= 255
    return "+" * value if value <= 128 else "-" * (256 - value)


def payload_source(ops: Iterable[Op]) -> str:
    seq = list(ops)
    if not seq:
        return ""
    pieces = [">" * WIDTH]
    for op in reversed(seq):
        if op.kind not in ("A", "O", "C"):
            raise ValueError(op)
        value = op.arg & 255
        pieces.append(">")
        if op.kind == "A":
            pieces.append(signed_initializer(((value >> 6) & 3) - 2))
        pieces.append(">")
        if op.kind == "A":
            pieces.append(signed_initializer(((value >> 3) & 7) - 4))
        pieces.append(">")
        if op.kind == "A":
            pieces.append(signed_initializer((value & 7) - 4))
        pieces.append(">")
        if op.kind == "A":
            pieces.append("+")
        pieces.append(">")
        if op.kind == "O":
            pieces.append("+")
        pieces.append(">")
        if op.kind == "C":
            pieces.append("+")
        pieces.append(">+>")
    return "".join(pieces)


def build_program(ops: Iterable[Op]) -> str:
    seq = list(ops)
    if not seq:
        return ""
    return payload_source(seq) + "<" + EXECUTOR + CLEANUP


def source_accounting(ops: Iterable[Op]) -> dict[str, int]:
    seq = list(ops)
    payload = payload_source(seq)
    return {
        "operations": len(seq),
        "reference_chars": len(reference_program(seq)),
        "payload_constructor_chars": len(payload),
        "fixed_executor_chars": 1 + len(EXECUTOR) + len(CLEANUP) if seq else 0,
        "total_chars": len(build_program(seq)),
    }
