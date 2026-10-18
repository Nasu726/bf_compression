from __future__ import annotations

"""Synthetic exact-map and full-memory tests of odd affine loop resynthesis."""

from random import Random

from bf_runtime import run_bf
from affine_loop_resynthesis import (
    optimize_affine_flat_loops,
    profile_flat_body,
    resynthesize_flat_loop,
    shortest_signed,
)


def semantic_coefficients(loop: str):
    profile = profile_flat_body(loop[1:-1])
    assert profile is not None
    inv = pow(profile.control, -1, 256)
    return {
        location: (-delta * inv) & 255
        for location, delta in profile.increments
        if delta
    }


def initialize(entrance: int, initial: dict[int, int]) -> str:
    current = 0
    parts = []
    for address, value in sorted(initial.items()):
        parts.append(">" * (address - current))
        parts.append(shortest_signed(value))
        current = address
    parts.append(">" * (entrance - current) if current <= entrance else "<" * (current - entrance))
    return "".join(parts)


def verify_loop(loop: str, rng: Random, full: bool = False) -> tuple[int, int]:
    optimized = resynthesize_flat_loop(loop)
    original = profile_flat_body(loop[1:-1])
    if original is None:
        assert optimized == loop
        return len(loop), len(optimized)
    new = profile_flat_body(optimized[1:-1])
    assert new is not None
    assert semantic_coefficients(loop) == semantic_coefficients(optimized)
    assert original.leftmost == new.leftmost and original.rightmost == new.rightmost
    assert len(optimized) <= len(loop)

    entrance = max(8, -original.leftmost + 3)
    touched = list(range(original.leftmost, original.rightmost + 1))
    inputs = list(range(256)) if full else [0, 1, 2, 127, 128, 255]
    for control in inputs:
        initial = {entrance + k: rng.randrange(256) for k in touched if k}
        initial[entrance] = control
        prefix = initialize(entrance, initial)
        memory_size = entrance + original.rightmost + 32
        reference = run_bf(prefix + loop, memory_size=memory_size, step_limit=15_000_000)
        result = run_bf(prefix + optimized, memory_size=memory_size, step_limit=15_000_000)
        assert (
            reference.output,
            reference.input_consumed,
            reference.pointer,
            reference.memory,
        ) == (
            result.output,
            result.input_consumed,
            result.pointer,
            result.memory,
        ), (loop, optimized, control)
    return len(loop), len(optimized)


def main() -> None:
    rng = Random(0xAFF1)
    loops = [
        "[-]",
        "[+]",
        "[->+<]",
        "[-" + ">" + "+" * 85 + "<]",
        "[+" + ">" + "+" * 85 + "<]",
        "[->++<]",
        "[--->+<]",
        "[<++>->+<]",
        "[>+<<++>-]",
        "[-<++++>>>--<<]",
        "[--->>++<<]",
    ]
    loops.extend([
        "[-->+<]",                 # even control, must be untouched
        "[->+>]",                  # moving pointer, must be untouched
        "[+>+<[-]]",               # nested, not flat
    ])
    for _ in range(50):
        c = rng.randrange(1, 256, 2)
        target_a = rng.randrange(256)
        target_b = rng.randrange(256)
        loop = "[" + shortest_signed(c) + ">" + shortest_signed(target_a) + ">"
        loop += shortest_signed(target_b) + "<<]"
        loops.append(loop)

    rows = []
    for i, loop in enumerate(loops):
        rows.append(verify_loop(loop, rng, full=(i == 3)))
    # Check the rewriter in compound programs (I/O remains untouched).
    compound = ",>+[->+<]<.>>+[->+<]<<"
    rewritten = optimize_affine_flat_loops(compound)
    assert rewritten.count(",") == compound.count(",") == 1
    assert rewritten.count(".") == compound.count(".") == 1
    assert len(rewritten) <= len(compound)

    assert resynthesize_flat_loop("[-->+<]") == "[-->+<]"
    assert resynthesize_flat_loop("[->+>]") == "[->+>]"
    print(f"affine-loop symbolic/full-memory test families passed: {len(rows)}")
    print(f"total flat-loop source: old={sum(a for a, _ in rows):,} new={sum(b for _, b in rows):,}")
    case = "[-" + ">" + "+" * 85 + "<]"
    print(f"affine coefficient 85: old={len(case)}, new={len(resynthesize_flat_loop(case))} source={resynthesize_flat_loop(case)}")


if __name__ == "__main__":
    main()
