from __future__ import annotations
"""Independent short-grammar exhaustive optima and BF runtime regression."""
from itertools import product
from functools import lru_cache
from random import Random
from bf_runtime import run_bf
from mine_hierarchical_call_runs import infer_runs, choose_inferred
from threaded_hierarchical_grammar import Call, Seq, Run, build_program, expand_calls
from threaded_window_macro_vm import literal_program


def observe(x):
    return x.output, x.input_consumed, x.pointer, x.memory


def brute_cost(macros, calls, width, max_period):
    @lru_cache(None)
    def all_options(i):
        if i == len(calls):
            return ((),)
        candidates = []
        for tail in all_options(i + 1):
            candidates.append((Call(calls[i]),) + tail)
        for period in range(1, min(max_period, (len(calls)-i)//2) + 1):
            block = tuple(calls[i:i + period])
            for count in range(2, min(255, (len(calls)-i)//period) + 1):
                end = i + period * count
                if tuple(calls[i:end]) != block * count:
                    break
                for tail in all_options(end):
                    candidates.append((
                        Run(Seq(tuple(Call(j) for j in block)), count),
                    ) + tail)
        return tuple(candidates)
    return min(len(build_program(macros, Seq(parts), width))
               for parts in all_options(0))


def check(macros, calls, width, input_data="ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    name, selected, lengths, grammar = choose_inferred(
        macros, calls, width, max_period=8
    )
    assert expand_calls(grammar) == tuple(calls)
    assert len(selected) == lengths[name] <= len(literal_program(macros, calls))
    source = literal_program(macros, calls)
    encoded = build_program(macros, grammar, width)
    cfg = dict(input_data=input_data,
               memory_size=max(128, (len(calls)+6)*(width+6)+128),
               step_limit=16000000)
    ref = run_bf(source, **cfg)
    for label, program in (("hierarchical", encoded), ("portfolio", selected)):
        got = run_bf(program, **cfg)
        assert observe(ref) == observe(got), (label, calls, lengths)
    return lengths


def main():
    rng = Random(20261018)
    dictionaries = (
        (1, ("+.", ",.", "[-]+.")),
        (2, (">+<.", ",>.<", "+>[-]<.")),
        (3, (">+>++<<.", "++[->+>+<<]>.<", ",>.,>+.<<")),
    )
    exhaustive = 0
    for width, macros in dictionaries[:2]:
        for n in range(7):
            for calls in product(range(2), repeat=n):
                grammar = infer_runs(macros, calls, width, max_period=3)
                assert len(build_program(macros, grammar, width)) == brute_cost(
                    macros, calls, width, 3
                )
                exhaustive += 1
    print("bounded grammar exhaustive source-cost optima:", exhaustive)
    checked = 0
    for width, macros in dictionaries:
        for n in range(5):
            for calls in product(range(3), repeat=n):
                check(macros, calls, width, "HELLO")
                checked += 1
        for _ in range(24):
            pattern = tuple(rng.randrange(3) for __ in range(
                rng.randrange(1, 8)
            ))
            calls = ((rng.randrange(3),) * rng.randrange(1, 4)
                     + pattern * rng.randrange(2, 19) + (2, 1, 0))
            check(macros, calls, width, "abcde" * 5)
            checked += 1
    print("automatic grammar full-memory differential cases:", checked)
    for width, macros in dictionaries:
        for n in (16, 64, 256, 1024):
            calls = (0, 1, 2) * (n // 3)
            name, program, lengths, grammar = choose_inferred(
                macros, calls, width, max_period=8
            )
            assert expand_calls(grammar) == calls
            print(f"W={width} calls={len(calls)} {lengths} chosen={name}")


if __name__ == "__main__":
    main()
