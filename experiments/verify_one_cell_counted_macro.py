from __future__ import annotations

"""Independent full-memory checks of executable counted macro grammar."""

from itertools import product
from random import Random

from bf_runtime import run_bf
from exact_one_cell_literal import exact_shortest_literal
from exact_one_cell_loop_grammar import exact_shortest_loop_grammar
from one_cell_counted_macro import (
    build_program,
    counted_macro,
    shortest_run_decomposition,
    source_accounting,
)
from self_extracting_linear_vm import Op, add, clear, out, reference_program


def observables(result):
    return result.output, result.input_consumed, result.pointer, result.memory


def check(ops: list[Op], max_period: int = 8) -> tuple[int, int]:
    reference = reference_program(ops)
    candidate, runs = shortest_run_decomposition(ops, max_period)
    assert candidate == build_program(ops, max_period)
    assert len(candidate) <= len(reference)
    a = run_bf(reference, memory_size=64, step_limit=6_000_000)
    b = run_bf(candidate, memory_size=64, step_limit=6_000_000)
    assert observables(a) == observables(b), (ops, reference, candidate)
    assert all(v == 0 for v in b.memory[1:]), (ops, candidate)
    assert b.pointer == 0
    for r in runs:
        assert 2 <= r["repeats"] <= 255
        assert r["literal_chars"] > r["source_chars"]
    return len(reference), len(candidate)


def independent_min_cost(ops: tuple[Op, ...], max_period: int = 4) -> int:
    """Small exhaustive grammar enumeration independent of suffix DP."""
    from functools import lru_cache
    from self_extracting_linear_vm import shortest_delta_source

    literals = [reference_program([op]) for op in ops]

    @lru_cache(None)
    def solve(i: int) -> int:
        if i == len(ops):
            return 0
        answer = len(literals[i]) + solve(i + 1)
        for period in range(1, min(max_period, (len(ops)-i)//2) + 1):
            block = ops[i:i+period]
            for repeats in range(2, min(255, (len(ops)-i)//period) + 1):
                stop = i + period*repeats
                if ops[i:stop] != block*repeats:
                    break
                body = reference_program(block)
                cost = len(counted_macro(body, repeats)) + solve(stop)
                answer = min(answer, cost)
        return answer

    return solve(0)


def main():
    alphabet = (add(1), add(255), out(), clear())
    exhaustive = 0
    for n in range(6):
        for ops in product(alphabet, repeat=n):
            source, records = shortest_run_decomposition(ops, max_period=4)
            assert len(source) == independent_min_cost(ops, max_period=4), ops
            exhaustive += 1

    cases = [
        [],
        [out()],
        [clear()],
        [add(1), out()] * 255,
        [add(255), out(), add(1), out()] * 128,
        [add(65)] + [out(), add(1), out(), add(1), out(), add(254)] * 255,
        [out()] * 255,
        [clear()] * 255,
        [add(1), out(), clear()] * 255,
        [add(7), out(), add(249), out()] * 130,
        ([add(5), out(), add(251), out()] * 120) + [add(15)],
    ]
    rng = Random(0xA771)
    for n in (1, 2, 4, 8, 16, 32, 64, 128, 256):
        for _ in range(8):
            ops = [
                add(rng.randrange(256))
                if kind == "A" else out() if kind == "O" else clear()
                for kind in (rng.choice("AAOC") for _ in range(n))
            ]
            cases.append(ops)
    for k in range(2, 21):
        period = [
            add(rng.randrange(256))
            if kind == "A" else out() if kind == "O" else clear()
            for kind in (rng.choice("AAOC") for _ in range(k))
        ]
        cases.append(period * rng.randrange(2, 90))

    totals = [check(ops, max_period=8) for ops in cases]
    print(f"counted-macro exhaustive grammar enumeration: {exhaustive:,} short inputs")
    print(f"counted-macro full-state differential cases passed: {len(cases):,}")
    print(
        f"counted-macro source aggregate: reference={sum(a for a, _ in totals):,} "
        f"macro={sum(b for _, b in totals):,}"
    )

    examples = {
        "periodic_ABC": cases[5],
        "repeated_output": [out()] * 255,
        "counter_progression": [add(1), out()] * 255,
    }
    for label, ops in examples.items():
        m = source_accounting(ops, max_period=8)
        exact = exact_shortest_literal(ops)
        loops = exact_shortest_loop_grammar(ops)
        print(
            f"{label}: raw={m['reference_chars']:,} "
            f"macro={m['runnable_run_chars']:,} "
            f"exact_literal={len(exact):,} "
            f"loop_grammar={len(loops):,} "
            f"runs={m['run_records']:,}"
        )


if __name__ == "__main__":
    main()
