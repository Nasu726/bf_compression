from __future__ import annotations

"""Full-memory, complete-input differential verification of threaded macros."""

from itertools import product
from random import Random

from bf_runtime import run_bf
from threaded_window_macro_vm import (
    build_threaded, check_window_macro, choose_shorter, literal_program,
    threaded_executor,
)


def observe(result):
    return (result.output, result.input_consumed, result.pointer, result.memory)


def verify(macros, calls, width, inp=""):
    for body in macros:
        check_window_macro(body, width)
    original = literal_program(macros, calls)
    threaded = build_threaded(macros, calls, width)
    chosen, cost = choose_shorter(macros, calls, width)
    assert len(chosen) <= len(original)
    assert len(threaded) == cost.threaded_chars
    assert cost.threaded_chars == cost.payload_chars + cost.fixed_chars
    record_width = width + len(macros) + 1
    assert cost.payload_chars == (
        record_width + len(calls) * (record_width + 2) if calls else 0
    )
    assert cost.fixed_chars == (
        1 + len(threaded_executor(macros, width)) + width + len(macros)
        if calls else 0
    )

    tape = max(96, (len(calls) + 2) * record_width + 32)
    kw = dict(input_data=inp, memory_size=tape, step_limit=20_000_000)
    baseline = run_bf(original, **kw)
    actual = run_bf(threaded, **kw)
    selected = run_bf(chosen, **kw)
    assert observe(baseline) == observe(actual), (
        macros, calls, width, inp, observe(baseline)[:3], observe(actual)[:3]
    )
    assert observe(baseline) == observe(selected)
    assert actual.pointer == 0
    assert all(x == 0 for x in actual.memory[width:])
    return cost


def main():
    for bad, width in (
        (">", 1), ("<", 2), (">>", 2), ("[>]", 4),
        ("[->+>+<]", 3), (">+", 2), ("[[]", 2),
    ):
        try:
            check_window_macro(bad, width)
        except ValueError:
            pass
        else:
            raise AssertionError((bad, width))

    checks = 0
    for width, macros in (
        (1, ("+.", "[-]++.", "-.+.")),
        (2, (">+<.", "+[->+<]>.<", ",>[-]<.")),
        (3, (">+>++<<.", "++[->+>+<<]>.<", ",>.,>+.<<")),
    ):
        for n in range(6):
            for calls in product(range(3), repeat=n):
                verify(macros, calls, width, "ABCXYZ")
                checks += 1

    rng = Random(0xB0AB)
    macros2 = (">+<." * 70, ",>+.<" * 45, "+[->+<]>.<" * 30)
    for n in (1, 3, 16, 64, 128):
        calls = tuple(rng.randrange(3) for _ in range(n))
        cost = verify(macros2, calls, 2, "ABCD" * 90)
        print(
            f"window={cost.window_width} macros={cost.dictionary_size} n={cost.calls}: "
            f"raw={cost.literal_chars:,} full_vm={cost.threaded_chars:,} "
            f"selected={cost.selected_chars:,} ({cost.selected_family}), "
            f"payload={cost.payload_chars:,}, fixed={cost.fixed_chars:,}"
        )
        checks += 1

    multi3 = (
        ">+>+<<.>.<" * 40,
        ">,>[-]<<+>.<" * 35,
        "+[->+>+<<]>.<" * 25,
    )
    for n in (2, 12, 48, 96):
        calls = tuple(rng.randrange(3) for _ in range(n))
        verify(multi3, calls, 3, "SOMEDATA" * 50)
        checks += 1

    for _ in range(30):
        width = rng.randint(2, 5)
        k = rng.randint(2, 5)
        pieces = ("+", "-", ".", ",", "[-]", ">+<", ">-<", ">.<")
        macro_list = [
            "".join(rng.choice(pieces) for __ in range(rng.randint(1, 15)))
            for _ in range(k)
        ]
        calls = tuple(rng.randrange(k) for __ in range(rng.randint(1, 60)))
        verify(tuple(macro_list), calls, width, "some input")
        checks += 1

    print(f"threaded window grammar full-tape differential cases passed: {checks:,}")


if __name__ == "__main__":
    main()
