from __future__ import annotations
"""Exact-source-cost DP for a bounded periodic RUN decomposition.

Enumerate literal calls and consecutive identical repeats of a short call
block, with block length <=max_period and count <=255. For fixed counter
depth 1 the source-length DP is exact, and the resulting executable BF is
compared with the depth-0 no-RUN program (which has a smaller record).
This is not an optimal arbitrary or recursively shared grammar extractor.
"""
from collections.abc import Sequence
from threaded_hierarchical_grammar import (
    Call, Seq, Run, _emitter, build_program
)
from threaded_grammar_portfolio import signed_initializer, numeric_program
from threaded_window_macro_vm import literal_program, check_window_macro


def infer_runs(macros: Sequence[str], calls: Sequence[int], width: int,
               *, max_period: int = 24) -> Seq:
    if max_period < 1 or not 1 <= len(macros) <= 128:
        raise ValueError("invalid period/dictionary")
    for macro in macros:
        check_window_macro(macro, width)
    if any(not isinstance(i, int) or i < 0 or i >= len(macros)
           for i in calls):
        raise ValueError("invalid macro ID")
    n = len(calls)
    leaf = [len(_emitter(i, width, len(macros), 1)) for i in calls]
    prefix = [0]
    for length in leaf:
        prefix.append(prefix[-1] + length)
    best = [10**30] * (n + 1)
    choices = [None] * (n + 1)
    best[n] = 0
    off = width + 3
    for i in range(n - 1, -1, -1):
        best[i] = leaf[i] + best[i + 1]
        choices[i] = (i + 1, Call(calls[i]))
        for period in range(1, min(max_period, (n - i) // 2) + 1):
            block = calls[i:i + period]
            if block != calls[i + period:i + 2 * period]:
                continue
            body_cost = prefix[i + period] - prefix[i]
            for count in range(2, min(255, (n - i) // period) + 1):
                end = i + period * count
                if calls[end - period:end] != block:
                    break
                # Four cursor-counter traversals and three fixed loop
                # symbols, plus exactly encoded repeat count and body.
                wrapper = 4 * off + 3 + len(signed_initializer(count))
                candidate = wrapper + body_cost + best[end]
                if candidate < best[i]:
                    best[i] = candidate
                    choices[i] = (
                        end,
                        Run(Seq(tuple(Call(x) for x in block)), count)
                    )
    out = []
    i = 0
    while i < n:
        end, node = choices[i]
        out.append(node)
        i = end
    grammar = Seq(tuple(out))
    literal_tree = Seq(tuple(Call(i) for i in calls))
    # Important fixed-cost correction: no RUN means depth 0 (no extra
    # counter per record). Compare *complete emitted BF* at the end.
    if len(build_program(macros, literal_tree, width)) <= len(
            build_program(macros, grammar, width)):
        return literal_tree
    return grammar


def choose_inferred(macros: Sequence[str], calls: Sequence[int], width: int,
                    *, max_period: int = 24):
    grammar = infer_runs(macros, calls, width, max_period=max_period)
    literal = literal_program(macros, calls)
    flat = numeric_program(macros, calls, width) if calls else ""
    hierarchical = build_program(macros, grammar, width)
    candidates = {
        "literal": literal,
        "flat_numeric": flat,
        "auto_run_grammar": hierarchical,
    }
    family = min(candidates, key=lambda n: (len(candidates[n]), n))
    return family, candidates[family], {
        name: len(src) for name, src in candidates.items()
    }, grammar
