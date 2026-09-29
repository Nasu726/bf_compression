from __future__ import annotations

"""Self-contained standard-BF VM for a tiny straight-line semantic ISA.

Supported semantic operations act on one logical current cell:

    A(delta)  add an 8-bit delta
    O         output the current byte
    C         clear the current byte

The purpose is to measure the *real BF source cost* of data-driven dispatch,
state carry, payload cleanup, and final-state materialization.  It is not meant
to replace the richer grammar VM yet.

Tape record layout
------------------

Cell 0..5 is an all-zero dummy record.  Every real record is six cells:

    [state, arg, add-flag, out-flag, clear-flag, live-flag]

Records are stored in reverse execution order.  The VM starts at the rightmost
live flag and walks right-to-left.  The logical cell value is transferred from
each record's state cell into the previous record's state cell.  After the last
operation it is transferred into dummy state cell 0, which is therefore the
materialized final logical tape value.  All opcode flags, arguments, live flags,
and non-dummy state cells are consumed to zero.  The VM exits at data pointer 0.

The one-hot opcode representation is intentionally simple: it keeps the first
real dispatcher small and makes every cleanup invariant explicit.  Later work
can compare this with denser numeric opcodes / prefix-coded bytecode.
"""

from dataclasses import dataclass
from typing import Iterable, Literal


Kind = Literal["A", "O", "C"]


@dataclass(frozen=True)
class Op:
    kind: Kind
    arg: int = 0


def add(delta: int) -> Op:
    return Op("A", delta & 255)


def out() -> Op:
    return Op("O")


def clear() -> Op:
    return Op("C")


def shortest_delta_source(value: int) -> str:
    value &= 255
    if value <= 128:
        return "+" * value
    return "-" * (256 - value)


def reference_program(ops: Iterable[Op]) -> str:
    pieces: list[str] = []
    for op in ops:
        if op.kind == "A":
            pieces.append(shortest_delta_source(op.arg))
        elif op.kind == "O":
            pieces.append(".")
        elif op.kind == "C":
            pieces.append("[-]")
        else:  # pragma: no cover - guarded by the dataclass type in normal use
            raise ValueError(op)
    return "".join(pieces)


# Entry: current record live flag (offset +5 from its state).
# Exit: dummy live flag (cell 5), whose value is zero.
#
# Per-record body:
#   clear live
#   dispatch CLEAR, OUT, ADD via one-hot flags
#   transfer logical state six cells left
#   move one cell left onto previous live flag
EXECUTOR = (
    "["
    "-"                         # live := 0
    "<[-<<<<[-]>>>>]"           # CLEAR flag: clear state
    "<[-<<<.>>>]"               # OUT flag: emit state
    "<[-<[-<+>]>]"              # ADD flag: arg -> state
    "<<[-<<<<<<+>>>>>>]"        # state -> previous record state
    "<"                          # previous record live flag
    "]"
)

# Outer loop exits at dummy live flag cell 5; dummy metadata is zero and dummy
# state cell 0 is the desired final logical cell value.
CLEANUP = "<<<<<"


def payload_source(ops: Iterable[Op]) -> str:
    seq = list(ops)
    if not seq:
        return ""
    pieces = [">>>>>>" ]  # skip all-zero dummy record; now at first real state
    for op in reversed(seq):
        # state -> arg
        pieces.append(">")
        if op.kind == "A":
            pieces.append(shortest_delta_source(op.arg))
        # arg -> add flag
        pieces.append(">")
        if op.kind == "A":
            pieces.append("+")
        # add -> out flag
        pieces.append(">")
        if op.kind == "O":
            pieces.append("+")
        # out -> clear flag
        pieces.append(">")
        if op.kind == "C":
            pieces.append("+")
        # clear -> live -> next state
        pieces.append(">+>")
    return "".join(pieces)


def build_program(ops: Iterable[Op]) -> str:
    seq = list(ops)
    if not seq:
        return ""
    payload = payload_source(seq)
    # Constructor ends one cell right of the rightmost live flag.
    return payload + "<" + EXECUTOR + CLEANUP


def source_accounting(ops: Iterable[Op]) -> dict[str, int]:
    seq = list(ops)
    payload = payload_source(seq)
    full = build_program(seq)
    return {
        "operations": len(seq),
        "payload_constructor_chars": len(payload),
        "executor_chars": (1 + len(EXECUTOR) + len(CLEANUP)) if seq else 0,
        "total_chars": len(full),
        "reference_chars": len(reference_program(seq)),
    }
