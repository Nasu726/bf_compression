from __future__ import annotations

"""One-copy, non-adjacent BF macro calls via a *real BF* phase dispatcher.

At a common data-pointer anchor A, consider the source fragment

    B Q[0] B Q[1] B ... Q[k-2] B

where every B and Q[i] returns its data pointer to A on termination.
The original whole program must be statically pointer-balanced and use
neither the dispatcher control cell nor any phase flag. Such cells are
witnessed by full-program footprint analysis and allocated strictly to
the right of the maximum visited original cell.

The transformed fragment stores B only ONCE in the BF source. A 1-valued
loop cell L and k one-hot phase flags execute B once per iteration. Phase
dispatch is visited in descending phase order. Thus phase i can set
phase i+1 without accidentally executing phase i+1 in the same iteration.

After phase i (i < k-1), Q[i] executes at A, and phase i+1 is armed.
The last phase clears L. All flags and L return to zero, and the pointer
returns to A. Each execution has the same B/Q sequence and I/O stream.
Divergence is preserved, since each B or Q is reached at exactly the
same point in the repeated sequence.

The dispatcher can be expensive, O(k^2 * distance) source characters
for a simple implementation. Therefore it is chosen ONLY when the
fully generated standard-BF source is strictly shorter than the
literal fragment. This is a niche direct-execution grammar, not a
general-purpose BF interpreter.

Required assumptions: zero-initialized 8-bit tape, standard BF loops,
the original program never accesses the private scratch region, every
macro/gap is pointer-balanced and starts at the same physical anchor.
"""

from dataclasses import dataclass

from global_scratch_reroll import analyze_global_static

BF = frozenset("><+-.,[]")


def _move(a: int, b: int) -> str:
    if a < 0 or b < 0:
        raise ValueError("negative data pointer")
    return ">" * (b - a) if b >= a else "<" * (a - b)


def _balanced_and_legal(fragment: str, anchor: int) -> bool:
    if any(ch not in BF for ch in fragment):
        return False
    depth = 0
    pointer = anchor
    level_pointer: list[int] = []
    for ch in fragment:
        if ch == ">":
            pointer += 1
        elif ch == "<":
            pointer -= 1
            if pointer < 0:
                return False
        elif ch == "[":
            level_pointer.append(pointer)
            depth += 1
        elif ch == "]":
            if not depth or level_pointer.pop() != pointer:
                return False
            depth -= 1
    return depth == 0 and pointer == anchor


@dataclass(frozen=True)
class PhaseResult:
    source: str
    literal_source: str
    selected: bool
    calls: int
    macro_chars: int
    scratch_control: int
    anchor: int


def phase_dispatcher(
    macro: str,
    gaps: tuple[str, ...],
    *,
    anchor: int,
    scratch_control: int,
) -> str:
    """Generate runnable BF at anchor, returning to anchor with scratch zero."""
    k = len(gaps) + 1
    if k < 2:
        raise ValueError("at least two calls are needed for sharing")
    if not _balanced_and_legal(macro, anchor):
        raise ValueError("macro is not statically balanced at anchor")
    if any(not _balanced_and_legal(g, anchor) for g in gaps):
        raise ValueError("gap is not statically balanced at anchor")
    if scratch_control <= anchor:
        raise ValueError("scratch must be strictly to the right of anchor")

    L = scratch_control
    setup = _move(anchor, L) + "+>+<"  # L=1, phase0=1, back to L
    body = [_move(L, anchor), macro, _move(anchor, L)]
    for phase in range(k - 1, -1, -1):
        p = L + phase + 1
        body.append(_move(L, p))
        body.append("[-")  # consume this phase flag
        if phase == k - 1:
            body.append(_move(p, L) + "-" + _move(L, p))
        else:
            next_phase = p + 1
            body.append(
                _move(p, anchor)
                + gaps[phase]
                + _move(anchor, next_phase)
                + "+"
                + _move(next_phase, p)
            )
        body.append("]")
        body.append(_move(p, L))
    return setup + "[" + "".join(body) + "]" + _move(L, anchor)


def construct_phase_reuse(
    prefix: str,
    macro: str,
    gaps: tuple[str, ...],
    suffix: str = "",
) -> PhaseResult:
    """Whole-program proof gate, followed by source-length portfolio choice.

    If the proof gate fails, return the original unchanged. The prospective
    source has the same external interface and contains no non-BF symbols.
    """
    if not gaps:
        raise ValueError("non-adjacent reuse needs at least two calls")
    literal_fragment = macro + "".join(g + macro for g in gaps)
    original = prefix + literal_fragment + suffix
    if any(ch not in BF for ch in original):
        raise ValueError("input must already be pure BF")
    footprint = analyze_global_static(original)
    if footprint is None:
        return PhaseResult(original, original, False, len(gaps) + 1, len(macro), -1, -1)

    prefix_state = analyze_global_static(prefix)
    if prefix_state is None:
        return PhaseResult(original, original, False, len(gaps) + 1, len(macro), -1, -1)
    anchor = prefix_state.final_pointer
    if not _balanced_and_legal(macro, anchor):
        return PhaseResult(original, original, False, len(gaps) + 1, len(macro), -1, anchor)
    if any(not _balanced_and_legal(gap, anchor) for gap in gaps):
        return PhaseResult(original, original, False, len(gaps) + 1, len(macro), -1, anchor)

    # The entire original (including suffix) must not touch these cells.
    # Restrict the selected scratch cells to the right of every original
    # pointer position as well, so no original static region overlaps them.
    control = footprint.peak_pointer + 1
    candidate_fragment = phase_dispatcher(
        macro, gaps, anchor=anchor, scratch_control=control
    )
    candidate = prefix + candidate_fragment + suffix
    if len(candidate) >= len(original):
        return PhaseResult(original, original, False, len(gaps) + 1, len(macro), control, anchor)
    assert all(ch in BF for ch in candidate)
    return PhaseResult(candidate, original, True, len(gaps) + 1, len(macro), control, anchor)
