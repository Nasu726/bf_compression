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


def verify_case(original: str) -> tuple[int, int]:
    candidate = exact_shortest_straight(original)
    optimized = optimize_bf(candidate)
    state = summarize(original)
    max_addr = max(
        state.pointer,
        max((a for a, _ in state.nonzero), default=0),
        16,
    )
    memsize = max(64, max_addr + 64)
    baseline = run_bf(original, memory_size=memsize, step_limit=5_000_000)
    for source in (candidate, optimized):
        result = run_bf(source, memory_size=memsize, step_limit=5_000_000)
        assert full_state(result) == full_state(baseline), (original, source)
    return len(original), len(candidate)


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
    print(f"aggregate reference={sum(a for a, _ in rows):,} exact={sum(b for _, b in rows):,}")
    print(f"far travel test: original={len(samples[2]):,} exact={len(exact_shortest_straight(samples[2])):,}")


if __name__ == "__main__":
    main()
