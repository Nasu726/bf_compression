from __future__ import annotations

"""Minimum-cost decomposition into direct literals and counted BF macro runs.

This is a *runnable standard-BF* alternative to a compressed bytecode VM.
It compiles repetition of an arbitrary one-cell A/O/C semantic operation
block B into a counter-controlled macro:

    > COUNT [ < B > - ] <

The execution enters and exits at the logical data cell 0. Cell 1 is
a proven-zero private scratch counter. Each iteration executes the exact
same B on cell 0, irrespective of the value B produces; B may print,
clear, or add. The loop destroys its count and returns to data cell 0,
so the complete final tape and pointer match the literal expansion.
Counts 1..255 are initialized with the shortest 8-bit signed spelling.

The optimizer runs a suffix shortest-path DP. Allowed edges are:
- literal execution of one A/O/C operation;
- a macro RUN(B,k) for a contiguous identical repeated block of 1..P
  operations, repeated 2..255 times.

All edges carry their *actual complete BF source costs*, including the
counter, brackets, routing and cleanup; the DP finds the exact optimum
within this bounded literal/RUN decomposition grammar. It does not claim
global shortest BF. It does not handle MOVE, INPUT, or unknown scratch
memory and must not be applied to an arbitrary program region without
proving its counter cell is private and initially zero.

A very long run is naturally split into multiple counted segments by the
DP. A 255-count needs a single '-' instruction, not 255 pluses.
"""

from typing import Iterable

from self_extracting_linear_vm import Op, reference_program, shortest_delta_source

ALLOWED = frozenset("AOC")


def counted_macro(body: str, repeats: int) -> str:
    if not (1 <= repeats <= 255):
        raise ValueError(repeats)
    if any(ch not in "+-.[]" for ch in body):
        raise ValueError("counted body must be balanced at data cell 0")
    # The only permitted bracket sequence in the restricted body is [-].
    if body.replace("[-]", "").find("[") >= 0 or body.replace("[-]", "").find("]") >= 0:
        raise ValueError("unsupported loop in counted body")
    return ">" + shortest_delta_source(repeats) + "[<" + body + ">-]<"


def shortest_run_decomposition(ops: Iterable[Op], max_period: int = 16):
    seq = list(ops)
    if max_period < 1:
        raise ValueError(max_period)
    for op in seq:
        if op.kind not in ALLOWED:
            raise ValueError(op)
    n = len(seq)
    best = [10**30] * (n + 1)
    choices: list[tuple[int, str, str, int] | None] = [None] * n
    best[n] = 0

    literals = [reference_program((op,)) for op in seq]

    for i in range(n - 1, -1, -1):
        best[i] = len(literals[i]) + best[i + 1]
        choices[i] = (i + 1, literals[i], "literal", 1)

        for period in range(1, min(max_period, (n - i) // 2) + 1):
            body_ops = seq[i:i + period]
            if body_ops != seq[i + period:i + 2 * period]:
                continue
            body = "".join(literals[i:i + period])
            max_repeats = min(255, (n - i) // period)
            for repeats in range(2, max_repeats + 1):
                end = i + repeats * period
                if seq[end - period:end] != body_ops:
                    break
                replacement = counted_macro(body, repeats)
                cost = len(replacement) + best[end]
                if cost < best[i]:
                    best[i] = cost
                    choices[i] = (end, replacement, "run", repeats)

    pieces: list[str] = []
    records: list[dict[str, int | str]] = []
    i = 0
    while i < n:
        choice = choices[i]
        assert choice is not None
        end, part, kind, count = choice
        pieces.append(part)
        if kind == "run":
            records.append({
                "start_operation": i,
                "end_operation": end,
                "period": (end - i) // count,
                "repeats": count,
                "source_chars": len(part),
                "literal_chars": sum(map(len, literals[i:end])),
            })
        i = end
    code = "".join(pieces)
    assert len(code) == best[0]
    assert len(code) <= sum(map(len, literals))
    return code, records


def build_program(ops: Iterable[Op], max_period: int = 16) -> str:
    return shortest_run_decomposition(ops, max_period)[0]


def source_accounting(ops: Iterable[Op], max_period: int = 16):
    seq = list(ops)
    source, runs = shortest_run_decomposition(seq, max_period)
    return {
        "operations": len(seq),
        "reference_chars": len(reference_program(seq)),
        "runnable_run_chars": len(source),
        "run_records": len(runs),
        "run_covered_operations": sum(int(x["end_operation"]) - int(x["start_operation"]) for x in runs),
        "runnable_macro_source_chars": sum(int(x["source_chars"]) for x in runs),
        "removed_literal_source_chars": sum(int(x["literal_chars"]) for x in runs),
    }
