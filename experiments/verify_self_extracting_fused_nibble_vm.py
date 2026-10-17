from __future__ import annotations

"""Full-state differential verification for the fused nibble semantic VM."""

from random import Random

from bf_runtime import run_bf
from bfopt import optimize_bf
from self_extracting_linear_vm import Op, add, clear, out, reference_program
from self_extracting_fused_nibble_vm import (
    EXECUTOR,
    build_program,
    cheapest_verified_family,
    source_accounting,
)


def observable(result):
    return result.output, result.input_consumed, result.pointer, result.memory


def verify_case(ops: list[Op]) -> tuple[int, int, int]:
    reference = reference_program(ops)
    candidate = build_program(ops)
    optimized = optimize_bf(candidate)
    family, portfolio = cheapest_verified_family(ops)
    memsize = max(64, 7 * (len(ops) + 2) + 16)

    expected = run_bf(reference, memory_size=memsize, step_limit=50_000_000)
    for label, source in (
        ("fused", candidate),
        ("optimized_fused", optimized),
        (family, portfolio),
    ):
        actual = run_bf(source, memory_size=memsize, step_limit=50_000_000)
        assert observable(expected) == observable(actual), (
            label, ops, observable(expected), observable(actual)
        )
        assert actual.pointer == 0
        assert all(x == 0 for x in actual.memory[1:]), (label, ops)
    assert len(portfolio) <= min(len(reference), len(candidate))
    return len(reference), len(candidate), len(portfolio)


def main():
    cases: list[list[Op]] = [
        [],
        [add(0)],
        [add(65), out()],
        [add(255), out(), add(2), out()],
        [add(128), clear(), add(7), out(), add(250)],
        [out(), clear(), out()],
        [add(1)] * 20 + [out()],
        [clear()] * 32,
        [out()] * 32,
        [add(255), add(1), out(), clear(), add(128), out()],
    ]
    # Exhaustive single-byte ADD inputs, including 0, 128, and 255.
    cases.extend([[add(value), out()] for value in range(256)])

    rng = Random(0xF05ED)
    for n in (1, 2, 4, 8, 16, 32, 64, 128):
        for _ in range(10):
            choices = [
                add(rng.randrange(256)) if k == "A" else out() if k == "O" else clear()
                for k in (rng.choice("AAOC") for _ in range(n))
            ]
            cases.append(choices)

    measured = [verify_case(ops) for ops in cases]
    print(f"fused-nibble differential cases passed: {len(cases)}")
    print(f"fixed executor chars: {1 + len(EXECUTOR) + 6}")
    print(
        "aggregate source: "
        f"reference={sum(a for a, _, _ in measured):,} "
        f"fused={sum(b for _, b, _ in measured):,} "
        f"portfolio={sum(c for _, _, c in measured):,}"
    )
    for n in (16, 64, 256):
        rng = Random(0xA11 + n)
        ops = [add(rng.randrange(256)) for _ in range(n)]
        verify_case(ops)
        metrics = source_accounting(ops)
        family, chosen = cheapest_verified_family(ops)
        print(
            f"add-only {n}: reference={metrics['reference_chars']:,} "
            f"fused={metrics['total_chars']:,} "
            f"selected={len(chosen):,} ({family})"
        )


if __name__ == "__main__":
    main()
