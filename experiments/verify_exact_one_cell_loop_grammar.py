from __future__ import annotations

"""Differential verification of globally costed one-cell loop grammar."""

from random import Random

from bf_runtime import run_bf
from bfopt import optimize_bf
from exact_one_cell_literal import exact_shortest_literal, semantics
from exact_one_cell_loop_grammar import (
    exact_shortest_loop_grammar,
    exact_shortest_loop_grammar_from_observations,
)
from self_extracting_linear_vm import Op, add, clear, out, reference_program


def ops_for_trace(trace: list[int], final: int = 0) -> list[Op]:
    seq: list[Op] = []
    cell = 0
    for b in trace:
        seq.append(add((b - cell) & 255))
        seq.append(out())
        cell = b
    seq.append(add((final - cell) & 255))
    return seq


def verify_case(ops: list[Op]) -> tuple[int, int, int]:
    raw = reference_program(ops)
    literal = exact_shortest_literal(ops)
    loop = exact_shortest_loop_grammar(ops)
    assert len(loop) <= len(literal) <= len(raw)
    memory_size = 64
    expected = run_bf(raw, memory_size=memory_size, step_limit=10_000_000)
    for variant in (loop, optimize_bf(loop)):
        actual = run_bf(variant, memory_size=memory_size, step_limit=10_000_000)
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
        ), (ops, loop, variant)
    return len(raw), len(literal), len(loop)


def main() -> None:
    cases = [
        [],
        [out()],
        [add(5), out(), add(255), out()],
        [add(255), out(), clear(), out()],
        [clear(), out(), add(128), out(), clear()],
    ]
    # Arithmetic progression outputs ending exactly when control reaches 0.
    for start in (1, 2, 5, 17, 64, 100, 128, 254, 255):
        cases.append(ops_for_trace(list(range(start, 0, -1))))
    for start, delta in ((3, -1), (65, -5), (99, 3), (8, -2), (128, -128)):
        state = start
        trace = []
        seen = set()
        while state and state not in seen:
            seen.add(state)
            trace.append(state)
            state = (state + delta) & 255
        if state == 0:
            cases.append(ops_for_trace(trace))

    rng = Random(0x10C0)
    for n in (1, 2, 4, 8, 16, 32, 64, 128):
        for _ in range(12):
            seq: list[Op] = []
            for _ in range(n):
                kind = rng.choice("AAOCC")
                seq.append(
                    add(rng.randrange(256))
                    if kind == "A" else out() if kind == "O" else clear()
                )
            cases.append(seq)

    # Exhaust all short output traces from a small byte alphabet and several
    # final byte values; verifies the constructed BF execution against an
    # independent reference rather than only round-trip through the DP.
    from itertools import product
    for length in range(5):
        for trace in product((0, 1, 2, 255), repeat=length):
            for final in (0, 1, 255):
                cases.append(ops_for_trace(list(trace), final=final))

    rows = [verify_case(ops) for ops in cases]
    countdown = ops_for_trace([5, 4, 3, 2, 1], final=0)
    synthesized = exact_shortest_loop_grammar(countdown)
    assert synthesized == "+++++[.-]", synthesized
    assert len(synthesized) == 9

    print(f"loop-grammar differential cases passed: {len(rows):,}")
    print(
        f"source aggregate: reference={sum(a for a, _, _ in rows):,} "
        f"exact_literal={sum(b for _, b, _ in rows):,} "
        f"loop_grammar={sum(c for _, _, c in rows):,}"
    )
    print(
        "countdown 5..1: "
        f"exact_literal={len(exact_shortest_literal(countdown))} "
        f"loop_grammar={len(synthesized)} code={synthesized}"
    )


if __name__ == "__main__":
    main()
