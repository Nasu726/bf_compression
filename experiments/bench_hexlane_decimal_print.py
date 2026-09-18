from __future__ import annotations

"""Compare emitted source size of Quad and compact HexLane decimal printers.

Raw operation bytes are the primary comparison because standalone zero-tape
optimization can legally erase value-dependent work.  We also report a real
constant-initialized optimized snippet for each representation as a secondary
sanity metric; full compiler integration remains the decisive measurement.
"""

import json

from bfcore import BFEmitter
from bfopt import optimize_bf
from bfquad import Quad64Ref, Quad64Core
from bfquadbackend import QuadBinaryStringListIO
from hexlane_scalar_core import HexLaneI64Core, HexLaneI64Ref
from hexlane_decimal_print import RECORD_STRIDE, print_hexlane_s64_compact

VALUE = 0xFEDCBA9876543210


def quad_print_raw() -> str:
    bf = BFEmitter()
    backend = QuadBinaryStringListIO(bf, scratch_base=110)
    backend.set_quad_workspace(120)
    backend.print_s64(Quad64Ref(0), workspace_base=330)
    return bf.code()


def hexlane_print_raw() -> str:
    bf = BFEmitter()
    print_hexlane_s64_compact(bf, HexLaneI64Ref(0), workspace_base=40)
    return bf.code()


def quad_constant_snippet() -> str:
    bf = BFEmitter()
    backend = QuadBinaryStringListIO(bf, scratch_base=110)
    backend.set_quad_workspace(120)
    src = Quad64Ref(0)
    Quad64Core(bf).set_u64(src, VALUE)
    backend.print_s64(src, workspace_base=330)
    return optimize_bf(bf.code())


def hexlane_constant_snippet() -> str:
    bf = BFEmitter()
    src = HexLaneI64Ref(0)
    HexLaneI64Core(bf).set_u64(src, VALUE)
    print_hexlane_s64_compact(bf, src, workspace_base=40)
    return optimize_bf(bf.code())


def describe(code: str) -> dict[str, int | float]:
    movement = code.count(">") + code.count("<")
    return {
        "bytes": len(code),
        "movement": movement,
        "movement_fraction": movement / len(code) if code else 0.0,
        "arithmetic": code.count("+") + code.count("-"),
        "control": code.count("[") + code.count("]"),
        "io": code.count(".") + code.count(","),
    }


def main() -> None:
    quad_raw = quad_print_raw()
    hex_raw = hexlane_print_raw()
    quad_const = quad_constant_snippet()
    hex_const = hexlane_constant_snippet()
    print(json.dumps({
        "quad_print_raw": describe(quad_raw),
        "hexlane_print_raw": describe(hex_raw),
        "raw_ratio": len(hex_raw) / len(quad_raw),
        "quad_constant_optimized": describe(quad_const),
        "hexlane_constant_optimized": describe(hex_const),
        "constant_optimized_ratio": len(hex_const) / len(quad_const),
        "hexlane_temp_record_stride": RECORD_STRIDE,
        "hexlane_temp_chain_cells": RECORD_STRIDE * 21,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
