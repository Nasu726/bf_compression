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
    # Reuse the text canonicalizer recursively; this keeps the prototype small
    # and avoids relying on compiler metadata.
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
    """Return one-iteration pointer delta iff every nested loop is balanced.

    A loop whose body has nonzero delta is a moving-loop barrier as an operation:
    its iteration count is data-dependent, so its total pointer displacement is
    not statically known.
    """
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


def _optimize_sequence(
    nodes: tuple[object, ...],
    *,
    default_value: int | None,
    initial_values: dict[int, int | None] | None = None,
) -> tuple[object, ...]:
    values: dict[int, int | None] = dict(initial_values or {})
    logical_ptr = 0
    emitted_ptr = 0
    out: list[object] = []

    def value_at(cell: int) -> int | None:
        return values[cell] if cell in values else default_value

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
            else:
                values[logical_ptr] = UNKNOWN
            out.append(node)
            continue
        if node == ",":
            # EOF semantics are intentionally not assumed. The post-input value
            # is unknown, and no preceding write is deleted merely because a
            # comma follows.
            flush_move()
            values[logical_ptr] = UNKNOWN
            out.append(node)
            continue
        if node == ".":
            flush_move()
            out.append(node)
            continue
        if not isinstance(node, Loop):
            raise AssertionError(node)

        # Body-local simplification is safe with an unknown iteration-entry
        # state: facts established earlier in the same body hold on every
        # executed iteration.
        body = _optimize_sequence(
            canonicalize(node.body),
            default_value=UNKNOWN,
            initial_values=None,
        )
        body = canonicalize(body)
        clear_loop = body == ("-",)
        cur = value_at(logical_ptr)

        # If the loop-control cell is already known zero, the loop is skipped,
        # including moving loops; no pointer movement occurs.
        if cur == 0:
            continue

        flush_move()
        if clear_loop:
            out.append(Loop(("-",)))
            values[logical_ptr] = 0
            continue

        delta = body_static_delta(body)
        if delta == 0:
            # A balanced loop returns to the same address. Any cell written by
            # the body is unknown afterwards; reaching the instruction after ]
            # proves the control cell is zero.
            _end, touched = balanced_effects(body, logical_ptr)
            out.append(Loop(body))
            for cell in touched:
                values[cell] = UNKNOWN
            values[logical_ptr] = 0
            continue

        # Moving/dynamic barrier. If the loop reaches its exit, `]` has just
        # observed zero at the *current* pointer. Forget absolute identity and
        # start a fresh relative epoch at that exit cell, retaining only cell 0
        # = 0. This also covers the skipped-loop case semantically, but cur != 0
        # here so an executed path may move.
        out.append(Loop(body))
        logical_ptr = 0
        emitted_ptr = 0
        values = {0: 0}
        default_value = UNKNOWN

    flush_move()
    return tuple(out)


def optimize_region_zero(code: str) -> str:
    original = strip_bf(code)
    nodes = canonicalize(parse(precanonicalize(original)))
    optimized = _optimize_sequence(nodes, default_value=0)
    optimized = canonicalize(optimized)
    result = stringify(optimized)
    # Research invariant: never make emitted standard BF longer than the local
    # canonical baseline. Returning canonical rather than original is fine: the
    # project already accepts canonical +- / >< folding as Level 0.
    baseline = stringify(nodes)
    return result if len(result) <= len(baseline) else baseline


__all__ = ["optimize_region_zero", "strip_bf"]
