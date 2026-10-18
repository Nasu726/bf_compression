from __future__ import annotations

"""Runnable standard-BF macro dictionary over a bounded data-tape window.

All-zero 8-bit tape, initial pointer 0. Every dictionary macro starts and
ends at the logical window anchor, stays within window_width cells, and has
only pointer-balanced nested loops. All eight BF commands, including input
and output, are allowed. Moving loops are conservatively rejected.

Each reversed call record is [W data cells | K one-hot flags | live]. A single
shared executor stores each macro body once, runs it on its current logical
window, and destructively transfers ALL W data bytes to the previous record.
Every temporary record is zero on exit; final window occupies physical
cells [0,W), pointer 0. Complete payload construction, dispatch, state
materialization and cleanup are counted in the emitted standard BF source.

This is a constructive one-level macro grammar VM, not an interpreter for
arbitrary BF: the dictionary and call stream are currently supplied by the
caller and there is no relational-parameter or rule-nesting decoder yet.
"""

from collections.abc import Sequence
from dataclasses import dataclass

BF = frozenset("><+-.,[]")


def check_window_macro(body: str, width: int) -> None:
    if width < 1:
        raise ValueError("window width must be >=1")
    if any(ch not in BF for ch in body):
        raise ValueError("macro contains invalid BF symbol")
    ptr = 0
    stack: list[int] = []
    for ch in body:
        if ch == ">":
            ptr += 1
        elif ch == "<":
            ptr -= 1
        elif ch == "[":
            stack.append(ptr)
        elif ch == "]":
            if not stack or stack.pop() != ptr:
                raise ValueError("moving or malformed nested loop")
        if not 0 <= ptr < width:
            raise ValueError("macro leaves declared window")
    if ptr != 0 or stack:
        raise ValueError("macro does not end at anchor with balanced brackets")


def literal_program(macros: Sequence[str], calls: Sequence[int]) -> str:
    if any(not 0 <= i < len(macros) for i in calls):
        raise ValueError("unknown macro symbol")
    return "".join(macros[i] for i in calls)


def threaded_executor(macros: Sequence[str], width: int) -> str:
    k = len(macros)
    if k < 1:
        raise ValueError("at least one macro required")
    for body in macros:
        check_window_macro(body, width)
    record_width = width + k + 1
    code = ["[", "-"]  # start at live flag; consume it
    for j in range(k - 1, -1, -1):
        distance = width + j
        code += ["<[-", "<" * distance, macros[j], ">" * distance, "]"]
    # At first flag; transfer data cells width-1 .. 0 to previous record.
    code += ["<"]
    for j in range(width - 1, -1, -1):
        code += ["[-", "<" * record_width, "+", ">" * record_width, "]"]
        if j > 0:
            code += ["<"]
    # At current state0; previous record's live flag is one cell left.
    code += ["<]"]
    return "".join(code)


def payload_source(macros: Sequence[str], calls: Sequence[int], width: int) -> str:
    if not calls:
        return ""
    k = len(macros)
    if not k or any(not isinstance(i, int) or not 0 <= i < k for i in calls):
        raise ValueError("invalid macro call stream")
    record_width = width + k + 1
    blocks = [">" * record_width]
    for index in reversed(calls):
        blocks.append(">" * width)
        for j in range(k):
            if j:
                blocks.append(">")
            if index == j:
                blocks.append("+")
        blocks.append(">+>")  # live flag and next record's state0
    return "".join(blocks)


def build_threaded(macros: Sequence[str], calls: Sequence[int], width: int) -> str:
    for body in macros:
        check_window_macro(body, width)
    if not calls:
        return ""
    record_width = width + len(macros) + 1
    return (
        payload_source(macros, calls, width)
        + "<"
        + threaded_executor(macros, width)
        + "<" * (record_width - 1)
    )


@dataclass(frozen=True)
class Cost:
    literal_chars: int
    threaded_chars: int
    selected_chars: int
    selected_family: str
    payload_chars: int
    fixed_chars: int
    window_width: int
    dictionary_size: int
    calls: int


def choose_shorter(macros: Sequence[str], calls: Sequence[int], width: int):
    literal = literal_program(macros, calls)
    payload = payload_source(macros, calls, width)
    vm = build_threaded(macros, calls, width)
    family = "threaded_window" if len(vm) < len(literal) else "literal"
    return (vm if family == "threaded_window" else literal), Cost(
        len(literal), len(vm), min(len(literal), len(vm)), family,
        len(payload), len(vm) - len(payload), width, len(macros), len(calls)
    )
