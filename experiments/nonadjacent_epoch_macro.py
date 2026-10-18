from __future__ import annotations

"""Proof-carrying *local* zero-scratch sharing after moving-loop barriers.

Global freshness is sufficient but unnecessarily strong.  A macro can
borrow existing tape cells during a finite source interval provided:
(1) each borrowed relative cell has value zero when entering the interval,
(2) the original interval neither reads nor writes those cells,
(3) the dispatcher returns every borrowed cell to zero before exiting.

This module proves (1) by a conservative forward exact/unknown value
abstract interpreter in relative-pointer epochs. For a terminating
moving/dynamic loop, absolute coordinates are forgotten, but the exit
control cell at relative 0 is known zero. This is valid for arbitrary
8-bit BF loops: the final loop test only exits on value 0. Conditions
(2) and pointer balance are checked syntactically, recursively through
nested loops. Condition (3) follows from the phase dispatcher invariant.

The proof is *local*: prefix and suffix may use the borrowed tape cells,
and the prefix may have moving/dynamic loops. The output BF is a standard
self-contained program. No assumptions about comma as unconditional
overwrite are made: input always makes a cell unknown in the analysis.

This is a sufficient-condition optimizer; inability to prove a zero cell
results in no rewrite. It is not a general BF minimal-source algorithm.
"""

from dataclasses import dataclass

from nonadjacent_phase_macro import PhaseResult, phase_dispatcher, _balanced_and_legal
from region_zero_opt import Loop, parse, body_static_delta, balanced_effects

UNKNOWN = None
BF = frozenset("><+-.,[]")


@dataclass(frozen=True)
class EpochFacts:
    pointer: int
    default: int | None
    overrides: dict[int, int | None]
    barriers: int

    def value(self, relative_offset: int) -> int | None:
        cell = self.pointer + relative_offset
        return self.overrides.get(cell, self.default)


def analyze_prefix(prefix: str) -> EpochFacts:
    """Conservative, termination-conditional exact byte facts at a boundary."""
    nodes = parse(prefix)
    known: dict[int, int | None] = {}
    default: int | None = 0
    ptr = 0
    barriers = 0

    def value_at(cell: int) -> int | None:
        return known.get(cell, default)

    for node in nodes:
        if node == ">":
            ptr += 1
            continue
        if node == "<":
            ptr -= 1
            continue
        if node in ("+", "-"):
            old = value_at(ptr)
            known[ptr] = None if old is None else (old + (1 if node == "+" else -1)) & 255
            continue
        if node == ",":
            known[ptr] = None
            continue
        if node == ".":
            continue
        if not isinstance(node, Loop):
            raise AssertionError(node)

        if value_at(ptr) == 0:
            # A loop with control already known zero is skipped; it can
            # contain arbitrary moving or nested control flow.
            continue
        delta = body_static_delta(node.body)
        if delta == 0:
            _, changed = balanced_effects(node.body, ptr)
            for offset in changed:
                known[offset] = None
            known[ptr] = 0
        else:
            # Control at loop exit is zero, but its physical position is
            # not statically identifiable after a moving loop.
            ptr = 0
            known = {0: 0}
            default = None
            barriers += 1

    return EpochFacts(ptr, default, known, barriers)


def relative_accesses(fragment: str) -> set[int] | None:
    """All relative cells read/written by any execution of a balanced body."""
    try:
        nodes = parse(fragment)
    except ValueError:
        return None
    if body_static_delta(nodes) != 0:
        return None
    visited: set[int] = set()

    def recurse(seq, base: int) -> int:
        loc = base
        for node in seq:
            if node == ">":
                loc += 1
            elif node == "<":
                loc -= 1
            elif isinstance(node, Loop):
                visited.add(loc)  # control test reads this cell
                if body_static_delta(node.body) != 0:
                    raise ValueError("dynamic child")
                after = recurse(node.body, loc)
                if after != loc:
                    raise ValueError("unbalanced child")
            else:
                visited.add(loc)  # includes I/O reads and updates
        return loc

    try:
        if recurse(nodes, 0) != 0:
            return None
    except ValueError:
        return None
    return visited


def construct_epoch_phase_reuse(
    prefix: str,
    macro: str,
    gaps: tuple[str, ...],
    suffix: str = "",
    *,
    max_scratch_offset: int = 96,
) -> PhaseResult:
    if not gaps:
        raise ValueError("need >=2 occurrences of the same macro")
    original = prefix + macro + "".join(g + macro for g in gaps) + suffix
    if any(c not in BF for c in original):
        raise ValueError("expected filtered BF source")
    touched = relative_accesses(macro)
    if touched is None:
        return PhaseResult(original, original, False, len(gaps)+1, len(macro), -1, -1)
    for gap in gaps:
        extra = relative_accesses(gap)
        if extra is None:
            return PhaseResult(original, original, False, len(gaps)+1, len(macro), -1, -1)
        touched.update(extra)

    facts = analyze_prefix(prefix)
    calls = len(gaps) + 1
    anchor = 256  # synthetic nonnegative coordinates for code generation
    for distance in range(1, max_scratch_offset - calls):
        scratch = set(range(distance, distance + calls + 1))
        if scratch & touched:
            continue
        if any(facts.value(d) != 0 for d in scratch):
            continue
        # The phase dispatcher generates *relative moves*. The synthetic
        # anchor is not the physical pointer and does not impose a global
        # coordinate system after a moving-loop barrier.
        if not _balanced_and_legal(macro, anchor) or any(
            not _balanced_and_legal(g, anchor) for g in gaps
        ):
            continue
        body = phase_dispatcher(macro, gaps, anchor=anchor, scratch_control=anchor+distance)
        result = prefix + body + suffix
        if len(result) < len(original):
            return PhaseResult(result, original, True, calls, len(macro), distance, 0)

    return PhaseResult(original, original, False, calls, len(macro), -1, 0)
