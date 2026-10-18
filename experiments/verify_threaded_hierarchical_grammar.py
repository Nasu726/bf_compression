from __future__ import annotations
"""Full-state differential test for nested RUN + terminal dictionary."""
from random import Random
from itertools import product
from bf_runtime import run_bf
from threaded_hierarchical_grammar import (
    Call, Seq, Run, Ref, build_program, expand_calls, choose_shortest
)
from threaded_window_macro_vm import literal_program


def observe(x):
    return x.output, x.input_consumed, x.pointer, x.memory


def check(macros, root, width, rules=None, data="ABCxyz"):
    calls = expand_calls(root, rules)
    source = literal_program(macros, calls)
    expanded_vm = build_program(macros, root, width, rules)
    _, chosen, sizes = choose_shortest(macros, root, width, rules)
    assert len(chosen) <= len(source)
    assert sizes["hierarchical"] == len(expanded_vm)
    mem = max(128, (len(calls) + 3) * (width + 12) + 96)
    runtime = dict(memory_size=mem, input_data=data, step_limit=18000000)
    ref = run_bf(source, **runtime)
    for label, bf in (("hierarchical", expanded_vm), ("portfolio", chosen)):
        got = run_bf(bf, **runtime)
        assert observe(got) == observe(ref), (label, root, sizes)
        assert got.pointer == 0
        assert all(c == 0 for c in got.memory[width:])
    return len(source), len(expanded_vm), len(chosen)


def dictionaries():
    return (
        (1, ("+.", ",.", "[-]+.")),
        (2, (">+<.", "+>[-]<.", ">,.<")),
        (3, (">+>++<<.", "++[->+>+<<]>.<", ",>.,>+.<<")),
    )


def main():
    rng = Random(1929)
    cases = []
    for width, macros in dictionaries():
        for n in range(5):
            for seq in product(range(3), repeat=n):
                cases.append((macros, Seq(tuple(Call(j) for j in seq)),
                              width, None, "abc"))
        for _ in range(35):
            leaves = Seq(tuple(Call(rng.randrange(3))
                               for __ in range(rng.randrange(1, 6))))
            ast = Run(leaves, rng.randrange(1, 10))
            if rng.randrange(2):
                ast = Seq((Call(rng.randrange(3)), ast, Call(rng.randrange(3))))
            if rng.randrange(2):
                ast = Run(ast, rng.randrange(1, 8))
            cases.append((macros, ast, width, None, "abcdefghi"))
        rules = {
            "A": Seq((Call(0), Call(1))),
            "B": Run(Ref("A"), 4),
            "C": Seq((Ref("B"), Call(2), Ref("B"))),
        }
        cases.append((macros, Run(Ref("C"), 6),
                      width, rules, "abcdefghi"))
    results = [check(*args) for args in cases]
    print("hierarchical BF full-state cases passed:", len(results))
    print("reference:", sum(a for a, _, _ in results),
          "hierarchical:", sum(b for _, b, _ in results),
          "portfolio:", sum(c for _, _, c in results))
    for width, macros in dictionaries():
        base = Seq((Call(0), Call(1), Call(2)))
        for counts in ((16, 16), (255, 255)):
            node = base
            for count in counts:
                node = Run(node, count)
            bf = build_program(macros, node, width)
            literal = sum(len(m) for m in macros) * counts[0] * counts[1]
            print(f"W={width} counts={counts} calls={3*counts[0]*counts[1]} "
                  f"literal={literal} hierarchical={len(bf)}")
    node = Run(Run(Call(0), 64), 64)
    # Real execution of a >4,000-call nested grammar, not size estimate.
    check(("+.",), node, 1, None, "")
    print("4096-call nested grammar execution: full state matched")
    try:
        build_program(("+.",), Ref("A"), 1,
                      {"A": Run(Ref("A"), 2)})
    except ValueError:
        pass
    else:
        raise AssertionError("cyclic rule accepted")
    print("cyclic rule rejected")


if __name__ == "__main__":
    main()
