from __future__ import annotations

"""Differential + exhaustive short-program tests for exact one-cell literals."""

from itertools import product
from random import Random

from bf_runtime import run_bf
from bfopt import optimize_bf
from self_extracting_linear_vm import Op, add, clear, out, reference_program
from exact_one_cell_literal import (
    exact_shortest_literal,
    exact_shortest_literal_for_observations,
    semantics,
    shortest_change,
)


def observe_source(program: str) -> tuple[tuple[int, ...], int]:
    # Independent tiny semantics for the restricted target language.
    state = 0
    result: list[int] = []
    i = 0
    while i < len(program):
        if program.startswith("[-]", i):
            state = 0
            i += 3
            continue
        char = program[i]
        if char == "+":
            state = (state + 1) % 256
        elif char == "-":
            state = (state - 1) % 256
        elif char == ".":
            result.append(state)
        else:
            raise AssertionError((program, i, char))
        i += 1
    return tuple(result), state


def verify_bruteforce() -> int:
    # Enumerate *all* token strings of up to 7 tokens of the four permitted
    # instructions. For each observed behavior, shortest_literal must be no
    # longer than any such candidate; an optimum may use >7 tokens.
    symbols = ("+", "-", ".", "[-]")
    seen: dict[tuple[tuple[int, ...], int], int] = {}
    candidates = 0
    for length in range(8):
        for tokens in product(symbols, repeat=length):
            text = "".join(tokens)
            behavior = observe_source(text)
            seen[behavior] = min(seen.get(behavior, 1 << 30), len(text))
            candidates += 1
    for (output, final), smallest in seen.items():
        opt = exact_shortest_literal_for_observations(output, final)
        assert observe_source(opt) == (output, final)
        # Enumeration bounds the *number of tokens*, not source characters.\n        # A shortest representation can contain more cheap single-character\n        # tokens than a longer candidate that contains several '[-]' tokens.\n        assert len(opt) <= smallest, (output, final, len(opt), smallest)
    return candidates


def verify_case(seq: list[Op]) -> tuple[int, int]:
    source = reference_program(seq)
    shortest = exact_shortest_literal(seq)
    assert observe_source(shortest) == semantics(seq)
    assert len(shortest) <= len(source)
    memory_size = 64
    expected = run_bf(source, memory_size=memory_size, step_limit=5_000_000)
    for candidate in (shortest, optimize_bf(shortest)):
        actual = run_bf(candidate, memory_size=memory_size, step_limit=5_000_000)
        assert (
            expected.output,
            expected.input_consumed,
            expected.pointer,
            expected.memory,
        ) == (
            actual.output,
            actual.input_consumed,
            actual.pointer,
            actual.memory,
        ), (seq, source, shortest)
    return len(source), len(shortest)


def main() -> None:
    brute_cases = verify_bruteforce()
    # Explicit proof conditions for every ordered s,t, including all wraparounds.
    for s in range(256):
        for t in range(256):
            expr = shortest_change(s, t)
            assert len(expr) == min(
                min((t - s) % 256, (s - t) % 256),
                3 + min(t, 256 - t),
            )
    cases: list[list[Op]] = [
        [],
        [add(0)],
        [out()],
        [clear()],
        [add(17), add(238), out()],
        [add(1)] * 256,
        [add(255)] * 256,
        [add(128), out(), add(128), out()],
        [add(128), clear(), out(), add(200)],
        [add(252), out(), add(5), out(), clear(), out()],
        [out()] * 256,
    ]
    # All 256 single-byte behaviors.
    cases.extend([[add(i), out()] for i in range(256)])

    rng = Random(0xBF0)
    for n in (2, 4, 8, 16, 32, 64, 128, 256):
        for _ in range(12):
            seq = []
            for _ in range(n):
                kind = rng.choice("AAAOCC")
                seq.append(
                    add(rng.randrange(256))
                    if kind == "A" else out() if kind == "O" else clear()
                )
            cases.append(seq)

    rows = [verify_case(ops) for ops in cases]
    print(f"literal brute-force candidates checked: {brute_cases:,}")
    print("all 65,536 state-pair costs verified")
    print(f"one-cell semantic differential cases passed: {len(rows):,}")
    print(
        f"one-cell total: reference={sum(x for x, _ in rows):,} "
        f"exact_literal={sum(y for _, y in rows):,}"
    )
    for n in (16, 64, 256):
        ops = [add((i * 73 + 29) & 255) for i in range(n)]
        print(
            f"ADD only n={n}: reference={len(reference_program(ops)):,} "
            f"exact_literal={len(exact_shortest_literal(ops)):,}"
        )


if __name__ == "__main__":
    main()
