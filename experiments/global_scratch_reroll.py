from __future__ import annotations

"""Globally witnessed unused-tape scratch for executable BF repetition.

This experimental compressor searches repeated top-level BF *lexical atoms*.
A complete bracketed loop is one atom; primitives are single atoms. All
loop bodies must be statically pointer-balanced, which makes the entire
program's pointer path / touched cells statically bounded. A cell S which
the original program never reads or writes is initially zero and may be
borrowed as a transient repetition counter, even if pointer movements
pass through it.

At an atom boundary whose pointer is A, any repeated balanced block B may
be replaced, for count k in 2..255, by

    MOVE(A,S) + INIT(k) +
    '[' + MOVE(S,A) + B + MOVE(A,S) + '-' + ']' + MOVE(S,A).

Here B is a complete balanced BF program fragment, so its execution
returns to A on termination; original code never touches S. Count is
initialized modulo 256 with a shortest signed representation. Original
program and replacement therefore have identical behavior on all input
streams, including I/O and EOF, under a fixed zero-initialized unbounded
8-bit tape model; they also agree in divergence, final memory and pointer.

Any dynamic/moving loop, left-boundary excursion, or source above the
configured research atom bound is conservatively left unchanged.

The region selector uses exact BF source length and a suffix DP. This is
a research prototype; production should replace naive O(n*P*K) repeated
block discovery with hashed token runs / indexing, and use certified
zero-scratch dataflow for programs with moving loops.
"""

from dataclasses import dataclass
from typing import Sequence

from self_extracting_linear_vm import shortest_delta_source

BF = frozenset("><+-.,[]")


@dataclass(frozen=True)
class Footprint:
    final_pointer: int
    peak_pointer: int
    touched: frozenset[int]
    partners: dict[int, int]


def analyze_global_static(source: str) -> Footprint | None:
    """Static pointer-balanced whole-program precondition and touched set."""
    pointer = 0
    max_pos = 0
    touched: set[int] = set()
    stack: list[tuple[int, int]] = []
    partners: dict[int, int] = {}

    for i, ch in enumerate(source):
        if ch not in BF:
            raise ValueError(f"unfiltered BF source at offset {i}")
        if ch == ">":
            pointer += 1
            max_pos = max(max_pos, pointer)
        elif ch == "<":
            pointer -= 1
            if pointer < 0:
                return None
        elif ch == "[":
            touched.add(pointer)
            stack.append((i, pointer))
        elif ch == "]":
            touched.add(pointer)
            if not stack:
                raise ValueError("unmatched closing bracket")
            start, at = stack.pop()
            partners[start] = i
            if pointer != at:
                return None
        else:
            touched.add(pointer)

    if stack:
        raise ValueError("unmatched opening bracket")
    return Footprint(pointer, max_pos, frozenset(touched), partners)


def top_level_atoms(source: str, footprint: Footprint):
    atoms: list[str] = []
    starts: list[int] = []
    i = 0
    pointer = 0
    while i < len(source):
        starts.append(pointer)
        if source[i] == "[":
            j = footprint.partners[i]
            atoms.append(source[i:j+1])
            i = j+1
        else:
            c = source[i]
            atoms.append(c)
            pointer += (c == ">") - (c == "<")
            i += 1
    starts.append(pointer)
    assert pointer == footprint.final_pointer
    return atoms, starts


def nearest_unused(anchor: int, footprint: Footprint) -> int:
    touched = footprint.touched
    left = anchor
    while left >= 0 and left in touched:
        left -= 1
    right = anchor
    while right in touched:
        right += 1
    if left >= 0 and anchor - left <= right - anchor:
        return left
    return right


def reroll(source: str, max_period: int = 16, max_atoms: int = 200_000):
    if max_period < 1 or max_atoms < 1:
        raise ValueError((max_period, max_atoms))
    footprint = analyze_global_static(source)
    if footprint is None:
        return source, [], "moving-loop-or-boundary"
    atoms, positions = top_level_atoms(source, footprint)
    if len(atoms) > max_atoms:
        return source, [], "atom-budget"

    n = len(atoms)
    costs = [0] * (n + 1)
    chosen: list[tuple[int, str, int] | None] = [None] * n

    for i in range(n - 1, -1, -1):
        costs[i] = len(atoms[i]) + costs[i+1]
        chosen[i] = (i+1, atoms[i], 1)

        anchor = positions[i]
        scratch = nearest_unused(anchor, footprint)
        d = scratch - anchor
        to_scratch = ">" * d if d >= 0 else "<" * (-d)
        back_to_anchor = "<" * d if d >= 0 else ">" * (-d)

        for period in range(1, min(max_period, (n-i)//2)+1):
            if positions[i+period] != anchor:
                continue
            block = atoms[i:i+period]
            if block != atoms[i+period:i+2*period]:
                continue
            body = "".join(block)
            max_repeat = min(255, (n-i)//period)
            for count in range(2, max_repeat+1):
                end = i+period*count
                if atoms[end-period:end] != block:
                    break
                candidate = (
                    to_scratch + shortest_delta_source(count) +
                    "[" + back_to_anchor + body + to_scratch + "-]" +
                    back_to_anchor
                )
                trial = len(candidate) + costs[end]
                if trial < costs[i]:
                    costs[i] = trial
                    chosen[i] = (end, candidate, count)

    out: list[str] = []
    events: list[dict[str, int]] = []
    i = 0
    while i < n:
        selected = chosen[i]
        assert selected is not None
        end, text, count = selected
        out.append(text)
        if count > 1:
            events.append({
                "from_atom": i, "to_atom": end,
                "repetitions": count, "period_atoms": (end-i)//count,
                "saved_chars": sum(map(len, atoms[i:end])) - len(text),
                "scratch_cell": nearest_unused(positions[i], footprint),
            })
        i = end
    result = "".join(out)
    assert len(result) == costs[0]
    assert len(result) <= len(source)
    return result, events, "ok"
