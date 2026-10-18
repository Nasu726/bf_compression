from __future__ import annotations
"""Standalone standard-BF hierarchical RUN constructor + shared terminal VM.

AST: Call(id), Seq(children), Run(child, count 1..255), Ref(rule_name).
RUN is executed by BF itself: it does NOT unroll the call records in source.
The terminal macro dictionary is shared (each macro body occurs once).
Ref definitions are expanded at compile time: DAG code sharing is NOT yet
implemented. Every generated record carries all active moving counters to
its successor. All scratch is zero after execution; the W-cell data window
is materialized at [0,W), pointer zero. Initial tape is zero, cells wrap
modulo 256, EOF is the interpreter's zero-byte convention.
"""
from dataclasses import dataclass
from collections.abc import Mapping, Sequence
from threaded_window_macro_vm import check_window_macro, literal_program
from threaded_grammar_portfolio import signed_initializer, numeric_program

@dataclass(frozen=True)
class Call:
    symbol: int

@dataclass(frozen=True)
class Seq:
    children: tuple["Node", ...]

@dataclass(frozen=True)
class Run:
    child: "Node"
    count: int

@dataclass(frozen=True)
class Ref:
    name: str

Node = Call | Seq | Run | Ref


def _expand_refs(node: Node, rules: Mapping[str, Node],
                 active: frozenset[str] = frozenset()) -> Node:
    if isinstance(node, Ref):
        if node.name not in rules or node.name in active:
            raise ValueError("undefined/cyclic grammar rule: " + node.name)
        return _expand_refs(rules[node.name], rules, active | {node.name})
    if isinstance(node, Seq):
        return Seq(tuple(_expand_refs(ch, rules, active) for ch in node.children))
    if isinstance(node, Run):
        if not isinstance(node.count, int) or not 1 <= node.count <= 255:
            raise ValueError("RUN count must be in 1..255")
        return Run(_expand_refs(node.child, rules, active), node.count)
    if isinstance(node, Call):
        if not isinstance(node.symbol, int) or node.symbol < 0:
            raise ValueError("invalid terminal macro ID")
        return node
    raise TypeError(node)


def expand_calls(node: Node, rules: Mapping[str, Node] | None = None,
                 max_calls: int = 150000) -> tuple[int, ...]:
    tree = _expand_refs(node, rules or {})
    result = []
    def visit(t):
        if isinstance(t, Call):
            result.append(t.symbol)
            if len(result) > max_calls:
                raise ValueError("call expansion exceeds reference-verifier limit")
        elif isinstance(t, Seq):
            for child in t.children:
                visit(child)
        else:
            for _ in range(t.count):
                visit(t.child)
    visit(tree)
    return tuple(result)


def _depth(tree: Node) -> int:
    if isinstance(tree, Call):
        return 0
    if isinstance(tree, Seq):
        return max((_depth(ch) for ch in tree.children), default=0)
    return 1 + _depth(tree.child)


def _emitter(symbol: int, width: int, k: int, depth: int) -> str:
    stride = width + 4 + depth
    # At data0 of the next record. Set Q and live flag. Transport each
    # active counter to the following record and zero the old counter.
    out = [">" * width, signed_initializer(symbol),
           ">" * (stride - 1 - width), "+", "<" * (stride - 1)]
    for level in range(depth):
        off = width + 3 + level
        out += [">" * off, "[-", ">" * stride, "+",
                "<" * stride, "]", "<" * off]
    out.append(">" * stride)
    return "".join(out)


def _emit_tree(tree: Node, width: int, k: int, depth: int) -> str:
    def visit(t, layer):
        if isinstance(t, Call):
            if t.symbol >= k:
                raise ValueError("macro ID outside dictionary")
            return _emitter(t.symbol, width, k, depth)
        if isinstance(t, Seq):
            # Construct reversed records, executed from right to left.
            return "".join(visit(ch, layer) for ch in reversed(t.children))
        off = width + 3 + layer
        return (">" * off + signed_initializer(t.count)
                + "[" + "<" * off + visit(t.child, layer + 1)
                + ">" * off + "-]" + "<" * off)
    return visit(tree, 0)


def _executor(macros: Sequence[str], width: int, depth: int) -> str:
    stride = width + 4 + depth
    body = ["[", "-", "<" * (depth + 3)]  # live -> Q
    for macro in macros:
        body += [">+<", "[->[-]>+<<]", ">>[-<<+>>]<<",
                 ">[-<-", "<" * width, macro, ">" * width,
                 ">]<", "-"]
    body += ["[-]<"]
    for j in range(width - 1, -1, -1):
        body += ["[-", "<" * stride, "+", ">" * stride, "]"]
        if j:
            body.append("<")
    body += ["<", "]"]
    return "".join(body)


def build_program(macros: Sequence[str], root: Node, width: int,
                  rules: Mapping[str, Node] | None = None) -> str:
    if not 1 <= len(macros) <= 128:
        raise ValueError("1..128 terminal macros required")
    for macro in macros:
        check_window_macro(macro, width)
    tree = _expand_refs(root, rules or {})
    if isinstance(tree, Seq) and not tree.children:
        return ""
    depth = _depth(tree)
    stride = width + 4 + depth
    constructor = ">" * stride + _emit_tree(tree, width, len(macros), depth)
    return constructor + "<" + _executor(macros, width, depth) + "<" * (stride - 1)


def choose_shortest(macros: Sequence[str], root: Node, width: int,
                    rules: Mapping[str, Node] | None = None):
    calls = expand_calls(root, rules)
    literal = literal_program(macros, calls)
    flat = numeric_program(macros, calls, width) if calls else ""
    hierarchical = build_program(macros, root, width, rules)
    choices = {"literal": literal, "flat_numeric": flat,
               "hierarchical": hierarchical}
    winner = min(choices, key=lambda name: (len(choices[name]), name))
    return winner, choices[winner], {name: len(src) for name, src in choices.items()}
