from __future__ import annotations

"""Relative-base known-zero optimization experiment.

This is deliberately a research prototype, not a production compressor.
It preserves a small but useful fact across pointer-moving loop barriers:
if a Brainfuck loop terminates, the cell under the pointer at loop exit is zero.
After such a barrier absolute cell identity is discarded, but the exit cell
becomes relative offset 0 of a fresh epoch and is therefore known zero.

ABI assumptions match the research project: zero-initialized tape and 8-bit
wrapping cells. Input is treated conservatively as producing an unknown value;
no overwrite/dead-store rule depends on EOF behavior.
"""

from dataclasses import dataclass
from typing import Any

BF = frozenset("><+-.,[]")
UNKNOWN = None


@dataclass(frozen=True)
class Loop:
    body: tuple[object, ...]


def strip_bf(text: str) -> str:
    return "".join(ch for ch in text if ch in BF)


def precanonicalize(code: str) -> str:
    out: list[str] = []
    move = 0
    add = 0

    def flush_move() -> None:
        nonlocal move
        if move > 0:
            out.append(">" * move)
        elif move < 0:
            out.append("<" * -move)
        move = 0

    def flush_add() -> None:
        nonlocal add
        z = add & 255
        if z <= 128:
            if z:
                out.append("+" * z)
        elif z:
            out.append("-" * (256 - z))
        add = 0

    for ch in strip_bf(code):
        if ch == ">":
            flush_add(); move += 1
        elif ch == "<":
            flush_add(); move -= 1
        elif ch == "+":
            flush_move(); add += 1
        elif ch == "-":
            flush_move(); add -= 1
        else:
            flush_move(); flush_add(); out.append(ch)
    flush_move(); flush_add()
    return "".join(out)


def parse(code: str) -> tuple[object, ...]:
    code = strip_bf(code)

    def rec(pos: int, nested: bool) -> tuple[list[object], int]:
        out: list[object] = []
        while pos < len(code):
            ch = code[pos]
            pos += 1
            if ch == "]":
                if not nested:
                    raise ValueError("unmatched ]")
                return out, pos
            if ch == "[":
                body, pos = rec(pos, True)
                out.append(Loop(tuple(body)))
            else:
                out.append(ch)
        if nested:
            raise ValueError("unmatched [")
        return out, pos

    nodes, _ = rec(0, False)
    return tuple(nodes)


def stringify(nodes: tuple[object, ...] | list[object]) -> str:
    out: list[str] = []
    for node in nodes:
        if isinstance(node, Loop):
            out.append("[")
            out.append(stringify(node.body))
            out.append("]")
        else:
            out.append(str(node))
    return "".join(out)


def canonicalize(nodes: tuple[object, ...] | list[object]) -> tuple[object, ...]:
    out: list[object] = []
    move = 0
    add = 0

    def flush_move() -> None:
        nonlocal move
        if move > 0:
            out.extend(">" for _ in range(move))
        elif move < 0:
            out.extend("<" for _ in range(-move))
        move = 0

    def flush_add() -> None:
        nonlocal add
        z = add & 255
        if z <= 128:
            out.extend("+" for _ in range(z))
        else:
            out.extend("-" for _ in range(256 - z))
        add = 0

    for node in nodes:
        if node == ">":
            flush_add(); move += 1
        elif node == "<":
            flush_add(); move -= 1
        elif node == "+":
            flush_move(); add += 1
        elif node == "-":
            flush_move(); add -= 1
        else:
            flush_move(); flush_add()
            if isinstance(node, Loop):
                body = canonicalize(node.body)
                if body in (("+",), ("-",)):
                    body = ("-",)
                out.append(Loop(body))
            else:
                out.append(node)
    flush_move(); flush_add()
    return tuple(out)


def body_static_delta(nodes: tuple[object, ...]) -> int | None:
    """Return one-iteration pointer delta iff every nested loop is balanced."""
    ptr = 0
    for node in nodes:
        if node == ">":
            ptr += 1
        elif node == "<":
            ptr -= 1
        elif isinstance(node, Loop):
            child_delta = body_static_delta(node.body)
            if child_delta is None or child_delta != 0:
                return None
    return ptr


def balanced_effects(nodes: tuple[object, ...], start: int) -> tuple[int, set[int]]:
    """Summarize a recursively balanced loop body."""
    ptr = start
    touched: set[int] = set()
    for node in nodes:
        if node == ">":
            ptr += 1
        elif node == "<":
            ptr -= 1
        elif node in ("+", "-", ","):
            touched.add(ptr)
        elif isinstance(node, Loop):
            d = body_static_delta(node.body)
            if d != 0:
                raise ValueError("balanced_effects called on dynamic body")
            _end, child = balanced_effects(node.body, ptr)
            touched.update(child)
    return ptr, touched


def _new_stats() -> dict[str, Any]:
    return {
        "removed_known_zero_loops": 0,
        "removed_known_zero_loop_bytes": 0,
        "moving_barriers_emitted": 0,
        "balanced_loops_emitted": 0,
        "removed_by_origin": {},
        "removed_bytes_by_origin": {},
        "removed_by_loop_kind": {},
        "removed_bytes_by_loop_kind": {},
        "original_loop_kinds": {},
        "loop_kind_transitions": {},
    }


def _bump(mapping: dict[str, int], key: str, amount: int = 1) -> None:
    mapping[key] = mapping.get(key, 0) + amount


def _loop_kind(body: tuple[object, ...]) -> str:
    delta = body_static_delta(body)
    if delta is None:
        return "dynamic"
    if delta == 0:
        return "balanced"
    return "moving"


def _optimize_sequence(
    nodes: tuple[object, ...],
    *,
    default_value: int | None,
    default_origin: str | None,
    initial_values: dict[int, int | None] | None = None,
    initial_origins: dict[int, str | None] | None = None,
    stats: dict[str, Any],
) -> tuple[object, ...]:
    values: dict[int, int | None] = dict(initial_values or {})
    origins: dict[int, str | None] = dict(initial_origins or {})
    logical_ptr = 0
    emitted_ptr = 0
    out: list[object] = []

    def value_at(cell: int) -> int | None:
        return values[cell] if cell in values else default_value

    def origin_at(cell: int) -> str | None:
        return origins[cell] if cell in origins else default_origin

    def flush_move() -> None:
        nonlocal emitted_ptr
        d = logical_ptr - emitted_ptr
        if d > 0:
            out.extend(">" for _ in range(d))
        elif d < 0:
            out.extend("<" for _ in range(-d))
        emitted_ptr = logical_ptr

    for node in nodes:
        if node == ">":
            logical_ptr += 1
            continue
        if node == "<":
            logical_ptr -= 1
            continue
        if node in ("+", "-"):
            flush_move()
            cur = value_at(logical_ptr)
            if cur is not UNKNOWN:
                values[logical_ptr] = (cur + (1 if node == "+" else -1)) & 255
                origins[logical_ptr] = "arithmetic"
            else:
                values[logical_ptr] = UNKNOWN
                origins.pop(logical_ptr, None)
            out.append(node)
            continue
        if node == ",":
            flush_move()
            values[logical_ptr] = UNKNOWN
            origins.pop(logical_ptr, None)
            out.append(node)
            continue
        if node == ".":
            flush_move()
            out.append(node)
            continue
        if not isinstance(node, Loop):
            raise AssertionError(node)

        original_body = canonicalize(node.body)
        original_kind = _loop_kind(original_body)
        _bump(stats["original_loop_kinds"], original_kind)

        cur = value_at(logical_ptr)
        if cur == 0:
            origin = origin_at(logical_ptr) or "known_zero"
            loop_bytes = 2 + len(stringify(original_body))
            stats["removed_known_zero_loops"] += 1
            stats["removed_known_zero_loop_bytes"] += loop_bytes
            _bump(stats["removed_by_origin"], origin)
            _bump(stats["removed_bytes_by_origin"], origin, loop_bytes)
            _bump(stats["removed_by_loop_kind"], original_kind)
            _bump(stats["removed_bytes_by_loop_kind"], original_kind, loop_bytes)
            _bump(stats["loop_kind_transitions"], f"{original_kind}->removed")
            continue

        # Body-local simplification is safe with an unknown iteration-entry
        # state: facts established earlier in the same body hold on every
        # executed iteration.
        body = _optimize_sequence(
            original_body,
            default_value=UNKNOWN,
            default_origin=None,
            initial_values=None,
            initial_origins=None,
            stats=stats,
        )
        body = canonicalize(body)
        clear_loop = body == ("-",)

        flush_move()
        if clear_loop:
            _bump(stats["loop_kind_transitions"], f"{original_kind}->clear")
            out.append(Loop(("-",)))
            values[logical_ptr] = 0
            origins[logical_ptr] = "clear"
            continue

        new_kind = _loop_kind(body)
        _bump(stats["loop_kind_transitions"], f"{original_kind}->{new_kind}")
        delta = body_static_delta(body)
        if delta == 0:
            _end, touched = balanced_effects(body, logical_ptr)
            out.append(Loop(body))
            stats["balanced_loops_emitted"] += 1
            for cell in touched:
                values[cell] = UNKNOWN
                origins.pop(cell, None)
            values[logical_ptr] = 0
            origins[logical_ptr] = "balanced_exit"
            continue

        # Moving/dynamic barrier. If the loop reaches its exit, `]` has just
        # observed zero at the current pointer. Forget absolute identity and
        # start a fresh relative epoch there, retaining only cell 0 = 0.
        out.append(Loop(body))
        stats["moving_barriers_emitted"] += 1
        logical_ptr = 0
        emitted_ptr = 0
        values = {0: 0}
        origins = {0: "moving_exit"}
        default_value = UNKNOWN
        default_origin = None

    flush_move()
    return tuple(out)


def optimize_region_zero_with_stats(code: str) -> tuple[str, dict[str, Any]]:
    original = strip_bf(code)
    nodes = canonicalize(parse(precanonicalize(original)))
    stats = _new_stats()
    optimized = _optimize_sequence(
        nodes,
        default_value=0,
        default_origin="initial_zero",
        stats=stats,
    )
    optimized = canonicalize(optimized)
    result = stringify(optimized)
    baseline = stringify(nodes)
    stats["canonical_bytes"] = len(baseline)
    stats["result_bytes"] = len(result)
    stats["saved_vs_canonical"] = len(baseline) - len(result)
    stats["accepted"] = len(result) <= len(baseline)
    if not stats["accepted"]:
        stats["result_bytes"] = len(baseline)
        stats["saved_vs_canonical"] = 0
        return baseline, stats
    return result, stats


def optimize_region_zero(code: str) -> str:
    return optimize_region_zero_with_stats(code)[0]


__all__ = [
    "optimize_region_zero",
    "optimize_region_zero_with_stats",
    "strip_bf",
]
