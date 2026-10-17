from __future__ import annotations

"""Shortest BF for a fixed one-cell output trace in a loop-augmented grammar.

Input: A/O/C operations, starting with a single zero 8-bit cell.
Output: An equivalent standard Brainfuck source, final pointer and full
memory identical.

Allowed *target grammar*:
  * A shortest straight-line change between known byte values, potentially
    using one '[-]' clear;
  * '.' to emit one current byte;
  * '[.' DELTA ']' loops, where DELTA is a shortest nonzero +/- spelling,
    which emits a finite arithmetic progression of nonzero values and exits
    with the cell equal to 0.

This is a strictly richer grammar than the exact_one_cell_literal optimizer.
It is not an absolute BF optimum: other loop bodies, scratch cells, arbitrary
input, tape motion and conditional loops are outside this grammar.

Dynamic programming is exact within this grammar. The state after producing
i output bytes is either the last emitted byte (literal output) or zero
(terminated loop). Literal transitions use the proved shortest-change cost.
For '[.delta]' transitions, the progression must match an entire segment of
observations and reach 0 *exactly* after the last emitted byte.

A loop of >=2 outputs has a uniquely determined delta from its first two
outputs. A one-output loop must have delta=-first_byte mod 256. We therefore
need inspect at most two candidate deltas per DP position. Each progression
is bounded by the 256-byte state space. An acyclic shortest-path DP then
gives the global optimum within the stated grammar.
"""

from typing import Iterable

from exact_one_cell_literal import (
    exact_shortest_literal_for_observations,
    semantics,
    shortest_change,
)
from self_extracting_linear_vm import Op, shortest_delta_source


def loop_candidate(output: tuple[int, ...], begin: int, delta: int):
    """Return (end, BF loop body) if one full terminating [.delta] fits."""
    delta &= 255
    if delta == 0:
        return None
    value = output[begin]
    if value == 0:
        return None
    j = begin
    visited: set[int] = set()
    while value != 0 and j < len(output) and value not in visited:
        if output[j] != value:
            return None
        visited.add(value)
        value = (value + delta) & 255
        j += 1
    if value != 0:
        return None
    return j, "[." + shortest_delta_source(delta) + "]"


def exact_shortest_loop_grammar_from_observations(
    output: Iterable[int], final_cell: int
) -> str:
    trace = tuple(x & 255 for x in output)
    n = len(trace)
    # key: (number of emitted bytes, current cell value)
    # value: (BF source cost, predecessor key, source fragment)
    best: dict[tuple[int, int], tuple[int, tuple[int, int] | None, str]] = {
        (0, 0): (0, None, "")
    }

    def relax(
        newkey: tuple[int, int], previous: tuple[int, int], piece: str
    ) -> None:
        newcost = best[previous][0] + len(piece)
        old = best.get(newkey)
        if old is None or newcost < old[0]:
            best[newkey] = (newcost, previous, piece)

    for i in range(n):
        possible_states = [0]
        if i > 0 and trace[i - 1] != 0:
            possible_states.append(trace[i - 1])
        target = trace[i]
        candidates = {(-target) & 255}
        if i + 1 < n:
            candidates.add((trace[i + 1] - target) & 255)

        for old_state in possible_states:
            key = (i, old_state)
            if key not in best:
                continue
            prefix = shortest_change(old_state, target)
            relax((i + 1, target), key, prefix + ".")
            for delta in candidates:
                result = loop_candidate(trace, i, delta)
                if result is None:
                    continue
                end, loop = result
                relax((end, 0), key, prefix + loop)

    outcomes = [
        (best[(n, value)][0] + len(shortest_change(value, final_cell)),
         (n, value), shortest_change(value, final_cell))
        for value in (0, trace[-1] if n else 0)
        if (n, value) in best
    ]
    if not outcomes:
        raise AssertionError("every observed trace has a literal construction")
    _, key, suffix = min(outcomes)

    fragments = [suffix]
    while key != (0, 0):
        _, prev, piece = best[key]
        assert prev is not None
        fragments.append(piece)
        key = prev
    fragments.reverse()
    program = "".join(fragments)
    assert len(program) <= len(exact_shortest_literal_for_observations(trace, final_cell))
    return program


def exact_shortest_loop_grammar(ops: Iterable[Op]) -> str:
    trace, final = semantics(ops)
    return exact_shortest_loop_grammar_from_observations(trace, final)
