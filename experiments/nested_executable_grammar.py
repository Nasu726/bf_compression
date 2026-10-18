from __future__ import annotations

"""Execute recursively nested run-length grammar directly as standard BF.

A terminal body has an explicitly established *one-cell frame contract*:
it starts and ends at physical cell 0 and only touches cell 0. It may emit
output but not consume input; allowed symbols are +,-,.,[-].

Grammar:
    Term(body)          execute body once
    Run(inner, count)   execute inner exactly count times, 1<=count<=255

Compilation of Run at nesting depth d uses a private zero scratch cell d+1:

    >^(d+1) INIT(count) [ <^(d+1) COMPILE(inner,d+1) >^(d+1) - ] <^(d+1)

All nested references to deeper counters are initially zero and restored
to zero on exit. Outer counters remain untouched inside child execution,
which stays at cell 0 or uses only counters further right. Consequently
the expansion is context-independent for *every* initial value of data
cell 0; outputs, final value, pointer and all scratch cells match the
unrolled direct body. Counts at each level are at most 255, but k nested
levels execute a body product(counts) times without repeating its BF
source. A count 255 costs only one '-' to initialize.

This is a concrete executable RLSLP-like construction for a restricted
one-cell, no-input frame. It is not a general BF subroutine mechanism.
"""

from dataclasses import dataclass
from functools import reduce
from operator import mul

from self_extracting_linear_vm import shortest_delta_source

_ALLOWED = set("+-.[]")


@dataclass(frozen=True)
class Term:
    body: str


@dataclass(frozen=True)
class Run:
    child: "Node"
    count: int


Node = Term | Run


def validate_terminal(body: str) -> None:
    # Every instruction, including nested loops, remains on data cell 0.
    # Thus terminal executions never access private counter cells. Input is
    # intentionally excluded until the EOF/runtime convention is specified.
    if any(ch not in _ALLOWED for ch in body):
        raise ValueError("one-cell terminal contains pointer/input command")
    nesting = 0
    for char in body:
        if char == "[":
            nesting += 1
        elif char == "]":
            nesting -= 1
            if nesting < 0:
                raise ValueError("unmatched terminal closing bracket")
    if nesting:
        raise ValueError("unmatched terminal opening bracket")


def compile_node(node: Node, active_depth: int = 0) -> str:
    if isinstance(node, Term):
        validate_terminal(node.body)
        return node.body

    if not 1 <= node.count <= 255:
        raise ValueError(node.count)
    depth = active_depth + 1
    child = compile_node(node.child, depth)
    left = "<" * depth
    right = ">" * depth
    return (
        right + shortest_delta_source(node.count) +
        "[" + left + child + right + "-]" + left
    )


def nested_run(body: str, outer_to_inner_counts: tuple[int, ...]) -> str:
    validate_terminal(body)
    node: Node = Term(body)
    for count in reversed(outer_to_inner_counts):
        node = Run(node, count)
    return compile_node(node)


def repetitions(counts: tuple[int, ...]) -> int:
    if not counts:
        return 1
    return reduce(mul, counts, 1)


def best_two_level(body: str, count: int) -> tuple[str, tuple[int, ...]]:
    """Exact min cost among flat-or-two-tier factorizations of this count."""
    if not 1 <= count <= 255**2:
        raise ValueError(count)
    validate_terminal(body)
    variants: list[tuple[str, tuple[int, ...]]] = []
    if count <= 255:
        variants.append((nested_run(body, (count,)), (count,)))
    for inner in range(2, min(count, 255) + 1):
        if count % inner:
            continue
        outer = count // inner
        if 2 <= outer <= 255:
            variants.append((nested_run(body, (outer, inner)), (outer, inner)))
    assert variants
    return min(variants, key=lambda pair: (len(pair[0]), len(pair[1])))


def source_accounting(body: str, counts: tuple[int, ...]) -> dict[str, int]:
    compressed = nested_run(body, counts)
    instances = repetitions(counts)
    return {
        "body_chars": len(body),
        "iterations": instances,
        "counter_depth": len(counts),
        "unrolled_chars": len(body) * instances,
        "runnable_nested_chars": len(compressed),
    }
