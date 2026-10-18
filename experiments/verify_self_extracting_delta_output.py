from __future__ import annotations

"""Full-state differential checks for the first self-contained BF executor."""

from random import Random

from bf_runtime import run_bf
from bfopt import optimize_bf
from self_extracting_delta_output import build_program, reference_program, source_accounting


def observable(result):
    return result.output, result.input_consumed, result.pointer, result.memory


def as_text(data: bytes) -> str:
    return data.decode("latin1")


def verify_case(data: bytes) -> tuple[int, int, int]:
    reference = reference_program(data)
    compressed = build_program(data)
    optimized = optimize_bf(compressed)

    memory_size = max(64, 3 * len(data) + 16)
    a = run_bf(reference, memory_size=memory_size, step_limit=50_000_000)
    b = run_bf(compressed, memory_size=memory_size, step_limit=50_000_000)
    c = run_bf(optimized, memory_size=memory_size, step_limit=50_000_000)

    expected = as_text(data)
    assert a.output == expected
    assert observable(a) == observable(b), (
        data,
        a.output,
        b.output,
        a.pointer,
        b.pointer,
        a.memory,
        b.memory,
    )
    assert observable(a) == observable(c), (
        data,
        a.output,
        c.output,
        a.pointer,
        c.pointer,
        a.memory,
        c.memory,
    )
    assert b.pointer == 0
    assert all(v == 0 for v in b.memory), (data, b.pointer, b.memory)
    assert all(v == 0 for v in c.memory), (data, c.pointer, c.memory)
    return len(reference), len(compressed), len(optimized)


def main() -> None:
    cases = [
        b"",
        b"A",
        b"AAAA",
        b"Hello, world!\n",
        b"Primes up to: ",
        bytes(range(16)),
        bytes([0, 255, 0, 128, 127, 1, 254]),
    ]
    rng = Random(0x51E1F)
    for n in (1, 2, 3, 8, 16, 32):
        cases.append(bytes(rng.randrange(256) for _ in range(n)))

    totals = [verify_case(data) for data in cases]
    longest = max(cases, key=len)
    accounting = source_accounting(longest)
    print(f"self-extracting delta-output cases passed: {len(cases)}")
    print(f"executor fixed overhead chars: {accounting['executor_chars']}")
    print(
        "longest-case source: "
        f"reference={len(reference_program(longest)):,} "
        f"self_extracting={len(build_program(longest)):,} "
        f"optimized={optimize_bf(build_program(longest)).__len__():,}"
    )
    print(
        f"aggregate raw source over test cases: reference={sum(x for x, _, _ in totals):,} "
        f"self_extracting={sum(y for _, y, _ in totals):,} "
        f"optimized_self_extracting={sum(z for _, _, z in totals):,}"
    )


if __name__ == "__main__":
    main()
