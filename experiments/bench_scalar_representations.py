from __future__ import annotations

"""Compare literal BF source cost of existing int64 physical representations.

This is an opportunity benchmark, not a compiler integration.  It emits a few
representative primitives from Python_to_BF_Translator at a pinned revision:

- Quad64: current 99-cell scalar representation;
- Base4: experimental 66-cell radix-4 lane representation;
- Packed-at-rest: 8-byte persistent values converted through a shared Quad
  workspace using the existing preserving PackedI64Core conversions.

All snippets are passed through the compiler's existing ``optimize_bf`` before
length measurement.  The benchmark intentionally reports both raw and optimized
source lengths because a representation can trade physical width for a longer
runtime lane body.
"""

import json
from typing import Callable

from bfcore import BFEmitter
from bfopt import optimize_bf
from bfpacked64 import PackedI64Core, PackedI64Ref
from bfquad import Quad64Core, Quad64Ref, WORD_CELLS as QUAD_CELLS
from bfbase4 import Base4I64Core, Base4I64Ref, WORD_CELLS as BASE4_CELLS


def measured(build: Callable[[BFEmitter], None]) -> dict[str, int]:
    bf = BFEmitter()
    build(bf)
    raw = bf.code()
    optimized = optimize_bf(raw)
    return {"raw_bytes": len(raw), "optimized_bytes": len(optimized)}


def quad_refs():
    gap = QUAD_CELLS + 1
    return (
        Quad64Ref(0),
        Quad64Ref(gap),
        Quad64Ref(2 * gap),
        Quad64Ref(3 * gap),
        4 * gap,
    )


def base4_refs():
    gap = BASE4_CELLS + 1
    return (
        Base4I64Ref(0),
        Base4I64Ref(gap),
        Base4I64Ref(2 * gap),
        Base4I64Ref(3 * gap),
        4 * gap,
    )


def bench_quad() -> dict[str, object]:
    a, b, dst, tmp, result = quad_refs()
    return {
        "word_cells": QUAD_CELLS,
        "copy": measured(lambda bf: Quad64Core(bf).copy64(dst, a)),
        "add": measured(lambda bf: Quad64Core(bf).add64(dst, a, b)),
        "sub": measured(lambda bf: Quad64Core(bf).sub64(dst, a, b)),
        "uge": measured(lambda bf: Quad64Core(bf).uge64(result, a, b, tmp)),
        "set_const": measured(
            lambda bf: Quad64Core(bf).set_u64(dst, 0xFEDCBA9876543210)
        ),
    }


def bench_base4() -> dict[str, object]:
    a, b, dst, tmp, result = base4_refs()
    return {
        "word_cells": BASE4_CELLS,
        "copy": measured(lambda bf: Base4I64Core(bf).copy64(dst, a)),
        "add": measured(lambda bf: Base4I64Core(bf).add64(dst, a, b)),
        "sub": measured(lambda bf: Base4I64Core(bf).sub64(dst, a, b)),
        "uge": measured(lambda bf: Base4I64Core(bf).uge64(result, a, b, tmp)),
        "set_const": measured(
            lambda bf: Base4I64Core(bf).set_u64(dst, 0xFEDCBA9876543210)
        ),
    }


def packed_preserving_add_via_quad(bf: BFEmitter) -> None:
    # Dense persistent values.
    pa = PackedI64Ref(0)
    pb = PackedI64Ref(8)
    pd = PackedI64Ref(16)

    # Shared arithmetic workspace, deliberately placed immediately after a
    # small guard.  A real allocator may improve this placement further.
    q0 = Quad64Ref(32)
    q1 = Quad64Ref(32 + QUAD_CELLS)
    qd = Quad64Ref(32 + 2 * QUAD_CELLS)
    packed = PackedI64Core(bf, scratch_base=32 + 3 * QUAD_CELLS + 2)
    quad = Quad64Core(bf)

    packed.to_int64(q0, pa)
    packed.to_int64(q1, pb)
    quad.add64(qd, q0, q1)
    packed.from_int64(pd, qd)


def packed_preserving_copy(bf: BFEmitter) -> None:
    core = PackedI64Core(bf, scratch_base=32)
    core.copy(PackedI64Ref(8), PackedI64Ref(0))


def packed_set_const(bf: BFEmitter) -> None:
    core = PackedI64Core(bf, scratch_base=32)
    core.set_u64(PackedI64Ref(0), 0xFEDCBA9876543210)


def bench_packed_at_rest() -> dict[str, object]:
    return {
        "word_cells": 8,
        "copy": measured(packed_preserving_copy),
        "set_const": measured(packed_set_const),
        "add_via_shared_quad_preserving_inputs": measured(
            packed_preserving_add_via_quad
        ),
        "note": (
            "The add case uses existing generic preserving pack/unpack code. "
            "It is an upper-bound integration prototype, not an optimized "
            "packed-scalar arithmetic backend."
        ),
    }


def main() -> None:
    rows = {
        "quad64": bench_quad(),
        "base4": bench_base4(),
        "packed_at_rest": bench_packed_at_rest(),
    }
    for op in ("copy", "add", "sub", "uge", "set_const"):
        if op in rows["quad64"] and op in rows["base4"]:
            q = rows["quad64"][op]["optimized_bytes"]
            b = rows["base4"][op]["optimized_bytes"]
            rows.setdefault("base4_vs_quad", {})[op] = {
                "quad_bytes": q,
                "base4_bytes": b,
                "delta_bytes": b - q,
                "ratio": b / q if q else None,
            }
    print(json.dumps(rows, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
