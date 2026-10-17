from __future__ import annotations

"""Provably shortest BF over {+,-,<,>} for a zero-initialized tape.

Inputs are straight-line BF programs using only four listed instructions,
executed with initial pointer 0, all 8-bit cells zero, and a nonnegative
pointer (crossing left of cell zero is rejected).

Outputs preserve *the entire final tape and the final data pointer*. There
are no I/O events. The optimizer returns the shortest source over the same
four-letter alphabet that yields these observations.

Theorem: Let v_i be the final value at cell i, p the final pointer, and
R=max{i:v_i!=0} (R=0 if all v_i=0). Set T=max(R,p) and
d(v)=min(v,256-v). Then the optimum number of BF commands is

    L* = sum_i d(v_i) + 2*T - p.

Proof: each cell's desired residue independently requires >=d(v_i)
increment/decrement commands. The pointer starts at 0, must visit every
nonzero cell (hence T) and terminate at p; this requires >=2*T-p
movements on the integer line. The construction writes each cell on a single
monotone rightward pass to T and then returns to p, meeting both lower
bounds simultaneously.

This theorem is intentionally for this restricted instruction set and
zero-initial conditions. Using loops as arithmetic macro instructions, I/O,
unknown initial cell values or semantics beyond the current fragment is out
of scope. It is not an absolute shortest-BF theorem.
"""

from dataclasses import dataclass


COMMANDS = frozenset("+-<>")


@dataclass(frozen=True)
class StraightState:
    pointer: int
    nonzero: tuple[tuple[int, int], ...]


def summarize(program: str) -> StraightState:
    pointer = 0
    cells: dict[int, int] = {}
    for symbol in program:
        if symbol not in COMMANDS:
            raise ValueError(f"unsupported instruction: {symbol!r}")
        if symbol == ">":
            pointer += 1
        elif symbol == "<":
            pointer -= 1
            if pointer < 0:
                raise ValueError("program moves left of the first tape cell")
        else:
            step = 1 if symbol == "+" else -1
            value = (cells.get(pointer, 0) + step) & 255
            if value:
                cells[pointer] = value
            else:
                cells.pop(pointer, None)
    return StraightState(pointer, tuple(sorted(cells.items())))


def shortest_delta_from_zero(byte: int) -> str:
    byte &= 255
    return "+" * byte if byte <= 128 else "-" * (256 - byte)


def optimal_length_from_state(state: StraightState) -> int:
    p = state.pointer
    if p < 0:
        raise ValueError("negative final pointer")
    farthest = state.nonzero[-1][0] if state.nonzero else 0
    t = max(p, farthest)
    arithmetic = sum(min(v, 256 - v) for _, v in state.nonzero)
    return arithmetic + 2 * t - p


def exact_shortest_straight(program: str) -> str:
    state = summarize(program)
    p = state.pointer
    farthest = state.nonzero[-1][0] if state.nonzero else 0
    t = max(p, farthest)
    chunks: list[str] = []
    location = 0
    for address, byte in state.nonzero:
        chunks.append(">" * (address - location))
        chunks.append(shortest_delta_from_zero(byte))
        location = address
    chunks.append(">" * (t - location))
    chunks.append("<" * (t - p))
    result = "".join(chunks)
    assert len(result) == optimal_length_from_state(state)
    assert summarize(result) == state
    assert len(result) <= len(program)
    return result


def saved_bytes(program: str) -> int:
    return len(program) - len(exact_shortest_straight(program))
