from __future__ import annotations

"""Full tape and I/O differential tests for numeric and RLE grammar VMs."""

from itertools import product
from random import Random
from bf_runtime import run_bf
from threaded_window_macro_vm import check_window_macro, literal_program
from threaded_grammar_portfolio import (
    choose_shortest, compress_calls, normalize_dictionary, numeric_payload,
    numeric_program, rle_numeric_payload, rle_numeric_program,
    rle_onehot_payload, rle_onehot_program, signed_initializer,
)


def observable(result):
    return result.output, result.input_consumed, result.pointer, result.memory


def verify(macros, calls, width, data="Hello World!"):
    ref = literal_program(macros, calls)
    bodies, sequence = normalize_dictionary(macros, calls, width)
    variants = {
        "numeric": numeric_program(bodies, sequence, width) if bodies else "",
        "rle_onehot": rle_onehot_program(bodies, sequence, width) if bodies else "",
        "rle_numeric": rle_numeric_program(bodies, sequence, width) if bodies else "",
    }
    selected, cost = choose_shortest(macros, calls, width)
    assert len(selected) == cost.selected_chars <= cost.baseline_chars
    assert cost.selected_chars == min(value for name, value in cost.candidates)
    memory_size = max(128, (len(calls) + 3) * (width + len(macros) + 6) + 128)
    kwargs = dict(input_data=data, memory_size=memory_size, step_limit=16_000_000)
    expected = run_bf(ref, **kwargs)
    for label, source in [*variants.items(), ("portfolio", selected)]:
        actual = run_bf(source, **kwargs)
        assert observable(actual) == observable(expected), (
            label, macros, calls, observable(expected)[:3],
            observable(actual)[:3],
        )
        if label != "portfolio":
            assert all(v == 0 for v in actual.memory[width:])
    return cost


def verify_constructor_sizes():
    rng = Random(1234)
    for k in (1, 2, 5, 16, 64, 128):
        for width in (1, 2, 3):
            macros = tuple("+-.+" * 3 + "+" * j for j in range(k))
            for n in (0, 1, 2, 16, 64):
                calls = tuple(rng.randrange(k) for _ in range(n))
                r = width + 4
                numeric = numeric_payload(macros, calls, width)
                expected = r + sum(r + 1 + len(signed_initializer(i)) for i in calls) if n else 0
                assert len(numeric) == expected
                runs = compress_calls(calls, k, width)
                r1 = width + k + 2
                onehot = rle_onehot_payload(macros, calls, width)
                expected = r1 + sum(r1 + 2 + len(signed_initializer(count))
                                    for symbol, count in runs) if n else 0
                assert len(onehot) == expected
                r2 = width + 5
                numeric_runs = compress_calls(
                    calls, k, width,
                    cost_per_record=lambda symbol, count: (
                        width + 6 + len(signed_initializer(symbol))
                        + len(signed_initializer(count))
                    ),
                )
                numeric_run = rle_numeric_payload(macros, calls, width)
                expected = r2 + sum(width + 6 + len(signed_initializer(s))
                                    + len(signed_initializer(c))
                                    for s, c in numeric_runs) if n else 0
                assert len(numeric_run) == expected


def main():
    verify_constructor_sizes()
    checks = 0
    dictionaries = (
        (1, ("+.", "[-]+.", ",.")),
        (2, (">+<.", "+[->+<]>.<", ",>[-]<.")),
        (3, (">+>++<<.", "++[->+>+<<]>.<", ",>.,>+.<<")),
    )
    for width, macros in dictionaries:
        for n in range(4):
            for calls in product(range(3), repeat=n):
                verify(macros, calls, width, "ABC123")
                checks += 1

    rng = Random(0xCB00)
    tokens = {
        1: ("+", "-", ".", "[-]", ",", "+."),
        2: ("+", "-", ".", "[-]", ",", ">+<", ">.<", ">[->+<]<"),
        3: ("+", "-", ".", "[-]", ",", ">+<", ">.<", ">[->+<]<"),
    }
    for width in (1, 2, 3):
        for k in (1, 2, 3, 5, 8, 12):
            for _ in range(7):
                macros = []
                for _ in range(k):
                    while True:
                        body = "".join(rng.choice(tokens[width])
                                       for __ in range(rng.randint(1, 6)))
                        try:
                            check_window_macro(body, width)
                        except ValueError:
                            continue
                        macros.append(body)
                        break
                n = rng.randint(1, 65)
                calls = [rng.randrange(k) for _ in range(n)]
                if n >= 8 and rng.randrange(3) == 0:
                    start = rng.randrange(n // 2)
                    calls[start:] = [calls[0]] * (n - start)
                verify(tuple(macros), tuple(calls), width, "abcd" * 20)
                checks += 1

    for k in (2, 8, 16):
        macros = tuple(
            ("+." if j % 2 else "-.") * 20
            + (">+<" if j % 3 == 0 else ">.<") * 5
            for j in range(k)
        )
        for calls in (
            (k - 1,) * 255,
            (k - 1,) * 128 + (0,) * 128,
            tuple(i % k for i in range(160)),
        ):
            cost = verify(macros, calls, 2)
            print(
                f"K={k} calls={len(calls)} raw={cost.baseline_chars:,} "
                f"complete_BF={cost.selected_chars:,} "
                f"selected={cost.selected_family}, runs={cost.run_records}"
            )
            checks += 1

    # Dictionary IDs 0 and 2 have identical definitions; merge and
    # reassign ID=0 to their most frequent canonical spelling.
    macros = ("+++", "-", "+++", ".", ",")
    calls = (2, 2, 2, 2, 2, 0, 3, 4, 4, 4, 1, 2, 1)
    compacted, _ = normalize_dictionary(macros, calls, 1)
    assert len(compacted) == 4 and compacted[0] == "+++"
    verify(macros, calls, 1, "XYZ")
    checks += 1
    print(f"threaded grammar portfolio full-state cases passed: {checks}")


if __name__ == "__main__":
    main()
