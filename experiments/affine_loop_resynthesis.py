from __future__ import annotations

"""Exact-map resynthesis of flat, balanced, odd-control Brainfuck loops.

A flat loop may contain only +,-,<,>, and must leave the pointer where it
started. With net control increment c odd (mod 256), it terminates for
every possible initial 8-bit control value x. Each other cell j receives

    y_j' = y_j - x * a_j * inverse(c) (mod 256),

where a_j is the total per-iteration increment of target j. The control
cell ends at zero. Therefore any odd c' and updates

    a'_j = a_j * inverse(c) * c' (mod 256)

produce exactly the same final state for every possible entry tape.
No input or output occurs inside this loop.

Among flat loops that group every target's increment into a single block
and preserve the original relative pointer excursion [L,R], enumerate all
128 odd c' and choose minimal signed arithmetic cost. A monotone traversal
0->L->R->0 has the minimum possible pointer movement 2(R-L).
This obtains the exact shortest source in that normalized flat-loop
family, accounting for all bracket/move/arithmetic source chars.

The replacement is a context-independent exact affine map on 8-bit
wrapping cells. It preserves termination, final pointer, output, input
consumption, and final cell values for every loop entry state. An unbounded
rightward tape and conventional left-boundary fault model are assumed.

Even-control loops are not transformed: their termination may depend on
the initial control residue. Nested loops and I/O loops are also skipped.
For fully bounded tapes with observable fault timing, changing traversal
order could alter which invalid access occurs first; those models require
a stronger access-trace precondition, not merely matching extrema.
"""

from dataclasses import dataclass

COMMANDS = set("><+-.,[]")


def shortest_signed(delta: int) -> str:
    value = delta & 255
    if value <= 128:
        return "+" * value
    return "-" * (256 - value)


@dataclass(frozen=True)
class LoopProfile:
    control: int
    increments: tuple[tuple[int, int], ...]
    leftmost: int
    rightmost: int


def profile_flat_body(body: str) -> LoopProfile | None:
    if any(op not in "+-<>" for op in body):
        return None
    pointer = 0
    leftmost = 0
    rightmost = 0
    increments: dict[int, int] = {}
    for command in body:
        if command == ">":
            pointer += 1
        elif command == "<":
            pointer -= 1
        else:
            increments[pointer] = (
                increments.get(pointer, 0) + (1 if command == "+" else -1)
            ) & 255
            if not increments[pointer]:
                del increments[pointer]
        leftmost = min(leftmost, pointer)
        rightmost = max(rightmost, pointer)
    if pointer != 0:
        return None
    c = increments.pop(0, 0)
    if not (c & 1):
        return None
    return LoopProfile(c, tuple(sorted(increments.items())), leftmost, rightmost)


def _construct(profile: LoopProfile, chosen_control: int) -> str:
    factor = (pow(profile.control, -1, 256) * chosen_control) & 255
    amounts = {p: (delta * factor) & 255 for p, delta in profile.increments}
    amounts = {p: val for p, val in amounts.items() if val}
    current = 0
    parts = ["[", shortest_signed(chosen_control)]

    for location in sorted((x for x in amounts if x < 0), reverse=True):
        parts.append("<" * (current - location))
        parts.append(shortest_signed(amounts[location]))
        current = location
    if current > profile.leftmost:
        parts.append("<" * (current - profile.leftmost))
        current = profile.leftmost
    for location in sorted(x for x in amounts if x > 0):
        parts.append(">" * (location - current))
        parts.append(shortest_signed(amounts[location]))
        current = location
    if current < profile.rightmost:
        parts.append(">" * (profile.rightmost - current))
        current = profile.rightmost
    if current > 0:
        parts.append("<" * current)
    elif current < 0:
        parts.append(">" * (-current))
    parts.append("]")
    return "".join(parts)


def resynthesize_flat_loop(loop: str) -> str:
    if not loop.startswith("[") or not loop.endswith("]"):
        return loop
    profile = profile_flat_body(loop[1:-1])
    if profile is None:
        return loop
    inv = pow(profile.control, -1, 256)
    arithmetic_movement = 2 * (profile.rightmost - profile.leftmost)
    best_c = 1
    best_cost = 1 << 60
    for c in range(1, 256, 2):
        factor = (inv * c) & 255
        cost = 2 + arithmetic_movement + len(shortest_signed(c))
        cost += sum(
            len(shortest_signed((delta * factor) & 255))
            for _, delta in profile.increments
        )
        if cost < best_cost:
            best_cost = cost
            best_c = c
    if best_cost >= len(loop):
        return loop
    candidate = _construct(profile, best_c)
    assert len(candidate) == best_cost, (len(candidate), best_cost)
    return candidate


def optimize_affine_flat_loops(source: str) -> str:
    """Replace only strictly shrinking, context-independently equivalent loops."""
    if any(x not in COMMANDS for x in source):
        raise ValueError("expected filtered eight-command BF source")
    stack: list[int] = []
    partners: dict[int, int] = {}
    for i, ch in enumerate(source):
        if ch == "[":
            stack.append(i)
        elif ch == "]":
            if not stack:
                raise ValueError("unmatched closing bracket")
            start = stack.pop()
            partners[start] = i
    if stack:
        raise ValueError("unmatched opening bracket")
    i = 0
    chunks: list[str] = []
    while i < len(source):
        ch = source[i]
        if ch == "[":
            stop = partners[i]
            body = source[i + 1:stop]
            if "[" not in body and "]" not in body:
                chunks.append(resynthesize_flat_loop(source[i:stop + 1]))
                i = stop + 1
                continue
        chunks.append(ch)
        i += 1
    result = "".join(chunks)
    assert len(result) <= len(source)
    return result
