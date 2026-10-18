from __future__ import annotations

"""Attribute generic compiler emission to top-level backend calls.

This is a source-opportunity profiler, not a semantic transform.  It compiles
representative generic programs with PythonToBFLayout, wraps the already-created
backend instance, and records the BF fragments emitted by each *outermost*
backend method call.  Nested helper calls are charged to their outer operation
so totals are not double-counted.

Attribution is measured on raw emitted BF because the final peephole optimizer
can cancel/coalesce commands across call boundaries.  The report therefore also
includes raw and final optimized whole-program sizes.  A large raw operation is
a candidate for representation-level replacement; its byte count is not a
promise of the same saving after whole-program optimization.
"""

import ast
import json
from collections import defaultdict
from dataclasses import dataclass, asdict
from textwrap import dedent
from typing import Any, Callable

from bfopt import optimize_bf
from compiler_layout import PythonToBFLayout


CASES = {
    "char_runtime_store": '''
chars = list(input())
i = int(input())
chars[i] = "X"
print("".join(chars))
''',
    "direct_join_input": '''
print("".join(list(input())))
''',
    "string_to_int": '''
s = input()
n = int(s)
print(n)
''',
    "int_to_string": '''
n = int(input())
s = str(n)
print(s)
''',
    "direct_int_input": '''
n = int(input())
print(n)
''',
    "scalar_arithmetic": '''
a = 123456789
b = 987654321
c = a + b
d = c - a
if d >= b:
    e = d + 7
else:
    e = d - 7
print(e)
''',
}


@dataclass
class Counter:
    calls: int = 0
    bytes: int = 0
    movement: int = 0
    arithmetic: int = 0
    control: int = 0
    io: int = 0

    def add(self, code: str) -> None:
        self.calls += 1
        self.bytes += len(code)
        self.movement += code.count(">") + code.count("<")
        self.arithmetic += code.count("+") + code.count("-")
        self.control += code.count("[") + code.count("]")
        self.io += code.count(".") + code.count(",")


def instrument_backend(compiler: PythonToBFLayout):
    backend = compiler.backend
    counters: dict[str, Counter] = defaultdict(Counter)
    state = {"depth": 0}

    # Instance patching means internal self.foo() calls also pass through these
    # wrappers.  depth==0 charges the complete nested emission only once.
    for name in dir(backend):
        if name.startswith("__"):
            continue
        try:
            original = getattr(backend, name)
        except Exception:
            continue
        if not callable(original):
            continue

        def make_wrapper(method_name: str, method: Callable[..., Any]):
            def wrapped(*args: Any, **kwargs: Any):
                outer = state["depth"] == 0
                start = len(compiler.bf.parts) if outer else 0
                state["depth"] += 1
                try:
                    return method(*args, **kwargs)
                finally:
                    state["depth"] -= 1
                    if outer:
                        emitted = "".join(compiler.bf.parts[start:])
                        counters[method_name].add(emitted)
            return wrapped

        try:
            setattr(backend, name, make_wrapper(name, original))
        except Exception:
            # Read-only descriptors are irrelevant to runtime emission.
            pass

    return counters


def compile_case(name: str, source: str) -> dict[str, object]:
    source = dedent(source)
    tree = ast.parse(source, filename=f"<{name}>")
    compiler = PythonToBFLayout(tree)
    counters = instrument_backend(compiler)
    raw = compiler.compile_module(tree)
    optimized = optimize_bf(raw)

    attributed = sum(c.bytes for c in counters.values())
    rows = {
        method: asdict(counter)
        for method, counter in sorted(
            counters.items(), key=lambda item: (-item[1].bytes, item[0])
        )
        if counter.bytes or counter.calls
    }
    return {
        "name": name,
        "raw_bytes": len(raw),
        "optimized_bytes": len(optimized),
        "raw_movement_bytes": raw.count(">") + raw.count("<"),
        "attributed_backend_bytes": attributed,
        "attributed_fraction_of_raw": attributed / len(raw) if raw else 0.0,
        "residual_raw_bytes": len(raw) - attributed,
        "backend_methods": rows,
    }


def main() -> None:
    results = [compile_case(name, source) for name, source in CASES.items()]

    aggregate: dict[str, Counter] = defaultdict(Counter)
    for result in results:
        for method, row in result["backend_methods"].items():
            c = aggregate[method]
            c.calls += row["calls"]
            c.bytes += row["bytes"]
            c.movement += row["movement"]
            c.arithmetic += row["arithmetic"]
            c.control += row["control"]
            c.io += row["io"]

    payload = {
        "artifacts": results,
        "aggregate": {
            "raw_bytes": sum(r["raw_bytes"] for r in results),
            "optimized_bytes": sum(r["optimized_bytes"] for r in results),
            "attributed_backend_bytes": sum(
                r["attributed_backend_bytes"] for r in results
            ),
            "methods": {
                method: asdict(counter)
                for method, counter in sorted(
                    aggregate.items(), key=lambda item: (-item[1].bytes, item[0])
                )
            },
        },
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
