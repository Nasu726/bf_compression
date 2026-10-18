from __future__ import annotations

"""Exact shortest one-cell literal program for the A/O/C semantic fragment.

Assumptions:
* Standard 8-bit wraparound BF, zero-initialized tape, pointer at cell 0.
* Input semantic operations: A(delta), O, C; no INPUT or MOVE.
* Output language: the straight-line literal alphabet '+', '-', '.', '[-]'.
  The only loop allowed is the three-character clear. In particular this is
  NOT a claim of global optimality among all eight BF instructions.

Every source in this restricted language has fixed pointer 0 and no input
consumption. Its observations consist only of the output-byte sequence and
the final byte in cell 0. The optimal length follows from decomposing source
at output instructions. To change known byte s to t between outputs:

   shortest(s,t) = min(d(s,t), 3 + d(0,t)),

where d(s,t)=min((t-s) mod 256,(s-t) mod 256).

Proof: Any segment without a clear must accumulate a congruent signed
delta, requiring at least d(s,t) arithmetic commands. If there is a clear,
discard the prefix through the LAST clear. That suffix starts at 0 and needs
at least d(0,t) arithmetic commands; the clear costs 3. Both constructions
are achievable. Exactly one '.' per desired output event is necessary in
this language. Finally apply the same bound to the terminal segment. Thus
concatenating shortest segments is globally optimal *within this language*.

This is stronger than a local peephole: the compiler can discard every
intermediate arithmetic update and clear between observable output events
while preserving full final tape state.
"""

from typing import Iterable

from self_extracting_linear_vm import Op, shortest_delta_source


def semantics(ops: Iterable[Op]) -> tuple[tuple[int, ...], int]:
    state = 0
    output: list[int] = []
    for op in ops:
        if op.kind == "A":
            state = (state + op.arg) & 255
        elif op.kind == "O":
            output.append(state)
        elif op.kind == "C":
            state = 0
        else:
            raise ValueError(op)
    return tuple(output), state


def shortest_change(source: int, target: int) -> str:
    source &= 255
    target &= 255
    delta = shortest_delta_source((target - source) & 255)
    via_clear = "[-]" + shortest_delta_source(target)
    return delta if len(delta) <= len(via_clear) else via_clear


def exact_shortest_literal_for_observations(
    output: Iterable[int], final_cell: int
) -> str:
    pieces: list[str] = []
    state = 0
    for observed in output:
        byte = observed & 255
        pieces.append(shortest_change(state, byte))
        pieces.append(".")
        state = byte
    pieces.append(shortest_change(state, final_cell))
    return "".join(pieces)


def exact_shortest_literal(ops: Iterable[Op]) -> str:
    output, final_cell = semantics(ops)
    return exact_shortest_literal_for_observations(output, final_cell)


def exact_shortest_length(ops: Iterable[Op]) -> int:
    return len(exact_shortest_literal(ops))


def source_accounting(ops: Iterable[Op]) -> dict[str, int]:
    seq = list(ops)
    from self_extracting_linear_vm import reference_program

    exact = exact_shortest_literal(seq)
    return {
        "operations": len(seq),
        "reference_chars": len(reference_program(seq)),
        "exact_literal_chars": len(exact),
        "output_events": len(semantics(seq)[0]),
    }
