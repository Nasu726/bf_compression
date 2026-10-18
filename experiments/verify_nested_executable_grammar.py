from __future__ import annotations

"""Full-state and source-length verification of recursively executable RUNs."""

from random import Random

from bf_runtime import run_bf
from nested_executable_grammar import (
    Term, Run, best_two_level, compile_node, nested_run, repetitions,
    source_accounting,
)
from self_extracting_linear_vm import shortest_delta_source


def observable(result):
    return result.output, result.input_consumed, result.pointer, result.memory


def verify(body: str, counts: tuple[int, ...], start: int = 0):
    n = repetitions(counts)
    prefix = shortest_delta_source(start)
    compressed = prefix + nested_run(body, counts)
    literal = prefix + body * n
    width = max(64, len(counts) + 16)
    step_limit = max(4_000_000, (len(body) + 32 * len(counts) + 32) * n * 6)
    reference = run_bf(literal, memory_size=width, step_limit=step_limit)
    actual = run_bf(compressed, memory_size=width, step_limit=step_limit)
    assert observable(reference) == observable(actual), (
        body, counts, start, compressed,
        observable(reference)[:3], observable(actual)[:3]
    )
    assert actual.pointer == 0
    assert all(v == 0 for v in actual.memory[1:])
    # The nested construction is exact but not necessarily worthwhile for\n    # small counts. The costed portfolio must reject longer candidates.\n    return len(literal), len(compressed)


def main():
    cases = [
        (".", (255, 255), 0),
        ("+.", (255, 255), 17),
        ("+.", (16, 16), 0),
        ("[-].+", (64, 16), 83),
        ("-.", (11, 7, 9), 3),
        ("+.-.", (15, 17), 0),
        ("+++++[.-]", (15, 7), 5),
        (".", (255, 255, 2), 0),
        ("[-]", (30, 16), 255),
        ("[-].", (16, 16), 12),
    ]
    rng = Random(0x5EED)
    body_alphabet = ("+", "-", ".", "[-]")
    for depth in (1, 2, 3):
        for _ in range(35):
            body = "".join(rng.choice(body_alphabet) for _ in range(rng.randrange(1, 8)))
            counts = tuple(rng.randrange(2, 13) for _ in range(depth))
            start = rng.randrange(256)
            cases.append((body, counts, start))

    rows = [verify(body, counts, start) for body, counts, start in cases]
    print(f"nested executable grammar full-state cases passed: {len(rows)}")
    print(
        f"unrolled reference={sum(a for a, _ in rows):,}; "
        f"runnable nested={sum(b for _, b in rows):,}"
    )
    for body, counts in ((".", (255, 255)), ("+.", (255, 255)), ("+.-.", (17, 17))):
        x = source_accounting(body, counts)
        print(f"nested example body={body!r} counts={counts}: unrolled={x['unrolled_chars']:,} runnable={x['runnable_nested_chars']:,} ratio={x['unrolled_chars']/x['runnable_nested_chars']:.1f}x")
    for n in (2, 3, 8, 16, 100, 200, 255, 256, 289, 511, 1024, 65025):
        compiled, factors = best_two_level("+.", n)
        assert repetitions(factors) == n
        valid = ([(n,)] if n <= 255 else []) + [
            (a, n // a)
            for a in range(2, 256)
            if n % a == 0 and 2 <= n // a <= 255
        ]
        assert len(compiled) == min(
            len(nested_run("+.", tuple(factor))) for factor in valid
        ), (n, factors)
        assert compiled == nested_run("+.", factors)
    print("two-level exact factor cost selection: ok")


if __name__ == "__main__":
    main()
