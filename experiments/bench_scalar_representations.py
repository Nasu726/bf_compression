from __future__ import annotations

"""Compare BF source cost of candidate int64 physical representations.

A zero-initialized standalone primitive is a bad benchmark: the compiler's
``optimize_bf`` can prove an uninitialized source word is zero and erase an
otherwise real copy/arithmetic body.  Every operation benchmark therefore has
an *unknown-state guard*: `,` is emitted into every persistent operand/output
cell whose old value the primitive may inspect or overwrite.  The final comma
is a side-effect barrier, so subtracting the optimized guard-only prefix gives
a useful marginal source cost without relying on zero-tape facts.

This remains an opportunity microbenchmark, not compiler integration.  Final
representation choices must be measured on complete generated programs.
"""

import json
from typing import Callable, Iterable

from bfcore import BFEmitter
from bfopt import optimize_bf
from bfpacked64 import PackedI64Core, PackedI64Ref
from bfquad import Quad64Core, Quad64Ref, WORD_CELLS as QUAD_CELLS
from bfbase4 import Base4I64Core, Base4I64Ref, WORD_CELLS as BASE4_CELLS
from hex16_scalar_core import Hex16I64Core, Hex16I64Ref, WORD_CELLS as HEX16_CELLS


def _unknown(bf: BFEmitter, cells: Iterable[int]) -> None:
    for cell in cells:
        bf.move(cell)
        bf.emit(",")


def measured(
    build: Callable[[BFEmitter], None],
    guard: Callable[[BFEmitter], None],
) -> dict[str, int]:
    # Raw body is still useful because representation emitters are themselves
    # the source-size machinery under study.
    body = BFEmitter()
    build(body)
    raw_body = body.code()

    guard_only = BFEmitter()
    guard(guard_only)
    guard_optimized = optimize_bf(guard_only.code())

    full = BFEmitter()
    guard(full)
    build(full)
    full_raw = full.code()
    full_optimized = optimize_bf(full_raw)

    return {
        "raw_operation_bytes": len(raw_body),
        "guard_only_optimized_bytes": len(guard_optimized),
        "guarded_total_raw_bytes": len(full_raw),
        "guarded_total_optimized_bytes": len(full_optimized),
        "guarded_incremental_bytes": len(full_optimized) - len(guard_optimized),
    }


def quad_refs():
    gap = QUAD_CELLS + 1
    return (
        Quad64Ref(0),
        Quad64Ref(gap),
        Quad64Ref(2 * gap),
        Quad64Ref(3 * gap),
        4 * gap,
    )


def quad_cells(ref: Quad64Ref) -> list[int]:
    return [ref.bit(i) for i in range(64)]


def base4_refs():
    gap = BASE4_CELLS + 1
    return (
        Base4I64Ref(0),
        Base4I64Ref(gap),
        Base4I64Ref(2 * gap),
        Base4I64Ref(3 * gap),
        4 * gap,
    )


def base4_cells(ref: Base4I64Ref) -> list[int]:
    return [ref.value(i) for i in range(32)]


def hex16_refs():
    gap = HEX16_CELLS + 1
    a = Hex16I64Ref(0)
    b = Hex16I64Ref(gap)
    dst = Hex16I64Ref(2 * gap)
    tmp = Hex16I64Ref(3 * gap)
    result = 4 * gap
    scratch = result + 2
    return a, b, dst, tmp, result, scratch


def hex16_cells(ref: Hex16I64Ref) -> list[int]:
    return [ref.digit(i) for i in range(16)]


def packed_cells(ref: PackedI64Ref) -> list[int]:
    return [ref.byte(i) for i in range(8)]


def bench_quad() -> dict[str, object]:
    a, b, dst, tmp, result = quad_refs()
    core = lambda bf: Quad64Core(bf)
    return {
        "word_cells": QUAD_CELLS,
        "copy": measured(
            lambda bf: core(bf).copy64(dst, a),
            lambda bf: _unknown(bf, quad_cells(a) + quad_cells(dst)),
        ),
        "add": measured(
            lambda bf: core(bf).add64(dst, a, b),
            lambda bf: _unknown(
                bf, quad_cells(a) + quad_cells(b) + quad_cells(dst)
            ),
        ),
        "sub": measured(
            lambda bf: core(bf).sub64(dst, a, b),
            lambda bf: _unknown(
                bf, quad_cells(a) + quad_cells(b) + quad_cells(dst)
            ),
        ),
        "uge": measured(
            lambda bf: core(bf).uge64(result, a, b, tmp),
            lambda bf: _unknown(
                bf,
                quad_cells(a)
                + quad_cells(b)
                + quad_cells(tmp)
                + [result],
            ),
        ),
        "set_const": measured(
            lambda bf: core(bf).set_u64(dst, 0xFEDCBA9876543210),
            lambda bf: _unknown(bf, quad_cells(dst)),
        ),
    }


def bench_base4() -> dict[str, object]:
    a, b, dst, tmp, result = base4_refs()
    core = lambda bf: Base4I64Core(bf)
    return {
        "word_cells": BASE4_CELLS,
        "copy": measured(
            lambda bf: core(bf).copy64(dst, a),
            lambda bf: _unknown(bf, base4_cells(a) + base4_cells(dst)),
        ),
        "add": measured(
            lambda bf: core(bf).add64(dst, a, b),
            lambda bf: _unknown(
                bf, base4_cells(a) + base4_cells(b) + base4_cells(dst)
            ),
        ),
        "sub": measured(
            lambda bf: core(bf).sub64(dst, a, b),
            lambda bf: _unknown(
                bf, base4_cells(a) + base4_cells(b) + base4_cells(dst)
            ),
        ),
        "uge": measured(
            lambda bf: core(bf).uge64(result, a, b, tmp),
            lambda bf: _unknown(
                bf,
                base4_cells(a)
                + base4_cells(b)
                + base4_cells(tmp)
                + [result],
            ),
        ),
        "set_const": measured(
            lambda bf: core(bf).set_u64(dst, 0xFEDCBA9876543210),
            lambda bf: _unknown(bf, base4_cells(dst)),
        ),
    }


def bench_hex16() -> dict[str, object]:
    a, b, dst, tmp, result, scratch = hex16_refs()
    core = lambda bf: Hex16I64Core(bf, scratch)
    return {
        "word_cells": HEX16_CELLS,
        "scratch_cells": Hex16I64Core.SCRATCH_CELLS,
        "copy": measured(
            lambda bf: core(bf).copy64(dst, a),
            lambda bf: _unknown(bf, hex16_cells(a) + hex16_cells(dst)),
        ),
        "add": measured(
            lambda bf: core(bf).add64(dst, a, b),
            lambda bf: _unknown(
                bf, hex16_cells(a) + hex16_cells(b) + hex16_cells(dst)
            ),
        ),
        "sub": measured(
            lambda bf: core(bf).sub64(dst, a, b),
            lambda bf: _unknown(
                bf, hex16_cells(a) + hex16_cells(b) + hex16_cells(dst)
            ),
        ),
        "uge": measured(
            lambda bf: core(bf).uge64(result, a, b, tmp),
            lambda bf: _unknown(
                bf,
                hex16_cells(a)
                + hex16_cells(b)
                + hex16_cells(tmp)
                + [result],
            ),
        ),
        "set_const": measured(
            lambda bf: core(bf).set_u64(dst, 0xFEDCBA9876543210),
            lambda bf: _unknown(bf, hex16_cells(dst)),
        ),
    }


def packed_preserving_add_via_quad(bf: BFEmitter) -> None:
    pa = PackedI64Ref(0)
    pb = PackedI64Ref(8)
    pd = PackedI64Ref(16)
    q0 = Quad64Ref(32)
    q1 = Quad64Ref(32 + QUAD_CELLS)
    qd = Quad64Ref(32 + 2 * QUAD_CELLS)
    packed = PackedI64Core(bf, scratch_base=32 + 3 * QUAD_CELLS + 2)
    quad = Quad64Core(bf)
    packed.to_int64(q0, pa)
    packed.to_int64(q1, pb)
    quad.add64(qd, q0, q1)
    packed.from_int64(pd, qd)


def bench_packed_at_rest() -> dict[str, object]:
    pa, pb, pd = PackedI64Ref(0), PackedI64Ref(8), PackedI64Ref(16)
    return {
        "word_cells": 8,
        "copy": measured(
            lambda bf: PackedI64Core(bf, scratch_base=32).copy(pd, pa),
            lambda bf: _unknown(bf, packed_cells(pa) + packed_cells(pd)),
        ),
        "set_const": measured(
            lambda bf: PackedI64Core(bf, scratch_base=32).set_u64(
                pd, 0xFEDCBA9876543210
            ),
            lambda bf: _unknown(bf, packed_cells(pd)),
        ),
        "add_via_shared_quad_preserving_inputs": measured(
            packed_preserving_add_via_quad,
            lambda bf: _unknown(
                bf, packed_cells(pa) + packed_cells(pb) + packed_cells(pd)
            ),
        ),
        "note": (
            "The add case uses existing generic preserving pack/unpack code. "
            "It is an upper-bound integration prototype, not an optimized "
            "packed-scalar arithmetic backend."
        ),
    }


def comparison(rows: dict[str, object], candidate: str) -> dict[str, object]:
    result: dict[str, object] = {}
    for op in ("copy", "add", "sub", "uge", "set_const"):
        if op not in rows[candidate]:
            continue
        q = rows["quad64"][op]["guarded_incremental_bytes"]
        c = rows[candidate][op]["guarded_incremental_bytes"]
        result[op] = {
            "quad_incremental_bytes": q,
            f"{candidate}_incremental_bytes": c,
            "delta_bytes": c - q,
            "ratio": c / q if q else None,
        }
    return result


def main() -> None:
    rows = {
        "quad64": bench_quad(),
        "base4": bench_base4(),
        "hex16": bench_hex16(),
        "packed_at_rest": bench_packed_at_rest(),
    }
    rows["base4_vs_quad"] = comparison(rows, "base4")
    rows["hex16_vs_quad"] = comparison(rows, "hex16")
    print(json.dumps(rows, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
