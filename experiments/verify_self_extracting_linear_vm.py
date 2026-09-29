from __future__ import annotations

"""Full-state differential checks for the tiny self-extracting semantic VM."""

from random import Random

from bf_runtime import run_bf
from bfopt import optimize_bf
from self_extracting_linear_vm import Op, add, build_program, clear, out, reference_program, source_accounting


def observable(result):
    return result.output, result.input_consumed, result.pointer, result.memory


def verify_case(ops: list[Op]) -> tuple[int, int, int]:
    reference = reference_program(ops)
    vm = build_program(ops)
    optimized = optimize_bf(vm)
    memory_size = max(64, 6 * len(ops) + 16)

    a = run_bf(reference, memory_size=memory_size, step_limit=50_000_000)
    b = run_bf(vm, memory_size=memory_size, step_limit=50_000_000)
    c = run_bf(optimized, memory_size=memory_size, step_limit=50_000_000)

    assert observable(a) == observable(b), (ops, observable(a), observable(b))
    assert observable(a) == observable(c), (ops, observable(a), observable(c))
    assert b.pointer == 0 and c.pointer == 0
    # Cell 0 is the materialized logical final state.  All VM metadata must be
    # gone, so every other cell remains indistinguishable from the reference.
    assert all(v == 0 for v in b.memory[1:]), (ops, b.memory)
    assert all(v == 0 for v in c.memory[1:]), (ops, c.memory)
    return len(reference), len(vm), len(optimized)


def main() -> None:
    cases: list[list[Op]] = [
        [],
        [add(65)],
        [add(65), out()],
        [add(65), out(), clear()],
        [add(255), out(), add(2), out()],
        [add(128), clear(), add(7), out(), add(250)],
        [out(), clear(), out()],
        [add(1)] * 20 + [out()],
    ]

    rng = Random(0x5E1F)
    for length in (1, 2, 4, 8, 16, 32, 64):
        seq: list[Op] = []
        for _ in range(length):
            kind = rng.randrange(3)
            if kind == 0:
                seq.append(add(rng.randrange(256)))
            elif kind == 1:
                seq.append(out())
            else:
                seq.append(clear())
        cases.append(seq)

    totals = [verify_case(case) for case in cases]
    longest = max(cases, key=len)
    accounting = source_accounting(longest)
    print(f"self-extracting linear-VM cases passed: {len(cases)}")
    print(f"fixed VM overhead chars: {accounting['executor_chars']}")
    print(
        "longest-case source: "
        f"reference={len(reference_program(longest)):,} "
        f"vm={len(build_program(longest)):,} "
        f"optimized_vm={len(optimize_bf(build_program(longest))):,}"
    )
    print(
        f"aggregate source: reference={sum(x for x, _, _ in totals):,} "
        f"vm={sum(y for _, y, _ in totals):,} "
        f"optimized_vm={sum(z for _, _, z in totals):,}"
    )


if __name__ == "__main__":
    main()
