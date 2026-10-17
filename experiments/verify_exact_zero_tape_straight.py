from __future__ import annotations

"""Exhaustive small-program and differential tests for exact straight BF."""

from itertools import product
from random import Random

from bf_runtime import run_bf
from bfopt import optimize_bf
from exact_zero_tape_straight import (
    StraightState,
    exact_shortest_straight,
    optimal_length_from_state,
    summarize,
)


def full_state(result):
    return result.output, result.input_consumed, result.pointer, result.memory


def verify_exhaustive() -> tuple[int, int]:
    best_seen: dict[StraightState, int] = {}
    valid = 0
    for length in range(8):
        for seq in product("+-<>", repeat=length):
            src = "".join(seq)
            try:
                state = summarize(src)
            except ValueError:
                continue
            valid += 1
            best_seen[state] = min(best_seen.get(state, 1 << 60), len(src))

    for state, best_len in best_seen.items():
        optimum = optimal_length_from_state(state)
        assert optimum == best_len, (state, optimum, best_len)
    return valid, len(best_seen)


def verify_case(original: str) -> tuple[int, int, int]:
    candidate = exact_shortest_straight(original)
    optimized = optimize_bf(candidate)
    state = summarize(original)
    max_addr = max(
        state.pointer,
        max((a for a, _ in state.nonzero), default=0),
        16,
    )
    # The reference may visit far cells and return without modifying them.
    # Tape allocation must cover the full execution trace, not only
    # the nonzero final state and final pointer.
    pos = peak = 0
    for ch in original:
        if ch == ">":
            pos += 1
            peak = max(peak, pos)
        elif ch == "<":
            pos -= 1
    memsize = max(64, max_addr + 64, peak + 64)
    baseline = run_bf(original, memory_size=memsize, step_limit=5_000_000)
    result = run_bf(candidate, memory_size=memsize, step_limit=5_000_000)
    assert full_state(result) == full_state(baseline), (original, candidate)

    # Legacy optimize_bf may drop terminal routing because its contract does
    # not preserve the final data pointer.  Do NOT conflate that optimizer's
    # weaker observation model with the full-state criterion here.
    legacy = run_bf(optimized, memory_size=memsize, step_limit=5_000_000)
    assert (legacy.output, legacy.input_consumed, legacy.memory) == (
        baseline.output, baseline.input_consumed, baseline.memory
    ), (original, optimized)
    pointer_drift = int(legacy.pointer != baseline.pointer)
    return len(original), len(candidate), pointer_drift


def main() -> None:
    valid, distinct = verify_exhaustive()
    samples = [
        "",
        "+",
        ">" * 400 + "<" * 400,
        "+" * 255,
        ("+" * 128 + "-" * 128) * 20,
        ">" * 100 + "+" * 7 + "<" * 98,
        "+" + ">" * 90 + "-" * 3 + "<" * 89 + "+" * 4,
        ">" * 1000 + "+" * 120 + ">" * 200 + "<" * 1200,
    ]
    rng = Random(0x57A1)
    for n in (1, 3, 8, 16, 64, 128, 256, 512):
        for _ in range(10):
            pointer = 0
            tokens = []
            for _ in range(n):
                char = rng.choice("++--<>")
                if char == "<" and pointer == 0:
                    char = ">"
                tokens.append(char)
                pointer += (char == ">") - (char == "<")
            samples.append("".join(tokens))
    rows = [verify_case(sample) for sample in samples]
    print(f"straight BF brute-force: {valid:,} valid short programs; {distinct:,} distinct final states")
    print(f"straight BF differential cases passed: {len(rows)}")
    print(f"aggregate reference={sum(a for a, _, _ in rows):,} exact={sum(b for _, b, _ in rows):,}")
    print(f"legacy optimizer final-pointer drift cases: {sum(c for _, _, c in rows):,}/{len(rows):,}")
    print(f"far travel test: original={len(samples[2]):,} exact={len(exact_shortest_straight(samples[2])):,}")


if __name__ == "__main__":
    main()
