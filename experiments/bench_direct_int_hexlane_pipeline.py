from __future__ import annotations

"""End-to-end scalar-I/O experiment for the HexLane ABI.

This deliberately keeps the production packed decimal parser unchanged and
replaces only the expensive representation boundary + scalar printer:

    decimal input -> PackedI64 (8 bytes) -> HexLane (16 nibbles) -> decimal output

The Packed -> HexLane conversion is destructive because the input token is dead
immediately after conversion in ``n = int(input()); print(n)``. Each packed
byte is divided by two four times at runtime: the four observed parity bits form
the low nibble, and the residual quotient is the high nibble. This avoids the
64-Boolean-bit expansion used by the current Quad path.

Parser and printer workspaces are deliberately disjoint. The compact printer's
temporary division chain assumes untouched zero-initialized cells; reusing the
parser workspace without a scrub violates that precondition and can make the
reverse walk run on stale metadata.

The production packed decimal parser is intentionally runtime-heavy. Long
19/20-digit boundary inputs can be much slower than the representation boundary,
so verification is split into short textual end-to-end cases and direct packed
boundary values.
"""

import json

from bf_runtime import run_bf
from bfcore import BFEmitter
from bfopt import optimize_bf
from bfpacked64 import PackedI64Ref
from bfstringlists import BinaryStringListIO
from compiler_layout import compile_source
from hexlane_decimal_print import print_hexlane_s64_compact
from hexlane_scalar_core import DIGITS, HexLaneI64Ref

SOURCE = "n = int(input())\nprint(n)\n"
MASK64 = (1 << 64) - 1

TOKEN_BASE = 0
HEX_BASE = 16
HAS_TOKEN = 52
END_LINE = 53
LINE_OPEN = 54
GATE = 55
SCRATCH_BASE = 64
WORKSPACE_BASE = 80
PRINT_WORKSPACE_BASE = 256


def _packed_to_hexlane_destructive(
    bf: BFEmitter,
    src: PackedI64Ref,
    dst: HexLaneI64Ref,
) -> None:
    """Consume eight packed bytes into sixteen little-endian nibbles."""
    shared_gate = dst.marker(DIGITS)
    bf.clear(shared_gate)
    bf.clear(dst.value(DIGITS))

    for byte_index in range(8):
        byte = src.byte(byte_index)
        low_digit = 2 * byte_index
        high_digit = low_digit + 1
        quotient = dst.marker(low_digit)
        parity = dst.marker(high_digit)
        low = dst.value(low_digit)
        high = dst.value(high_digit)

        for cell in (quotient, parity, low, high):
            bf.clear(cell)

        for within in range(4):
            bf.clear(quotient)
            bf.clear(parity)
            bf.begin_while(byte)
            bf.add_const(byte, -1)
            bf.set_const(shared_gate, 1)
            bf.begin_while(parity)
            bf.add_const(parity, -1)
            bf.clear(shared_gate)
            bf.add_const(quotient, 1)
            bf.end_while(parity)
            bf.begin_while(shared_gate)
            bf.add_const(shared_gate, -1)
            bf.add_const(parity, 1)
            bf.end_while(shared_gate)
            bf.end_while(byte)
            bf.begin_while(parity)
            bf.add_const(parity, -1)
            bf.add_const(low, 1 << within)
            bf.end_while(parity)
            bf.begin_while(quotient)
            bf.add_const(quotient, -1)
            bf.add_const(byte, 1)
            bf.end_while(quotient)

        bf.begin_while(byte)
        bf.add_const(byte, -1)
        bf.add_const(high, 1)
        bf.end_while(byte)
        bf.clear(quotient)
        bf.clear(parity)
        bf.clear(shared_gate)


def build_hexlane_direct_int() -> str:
    bf = BFEmitter()
    token = PackedI64Ref(TOKEN_BASE)
    value = HexLaneI64Ref(HEX_BASE)
    backend = BinaryStringListIO(bf, scratch_base=SCRATCH_BASE)

    backend.packed64.clear(token)
    bf.set_const(LINE_OPEN, 1)
    backend.read_packed_s64_line_token(token, HAS_TOKEN, END_LINE, WORKSPACE_BASE)

    backend.copy_cell(END_LINE, GATE, backend.s0)
    bf.begin_while(GATE)
    bf.add_const(GATE, -1)
    bf.clear(LINE_OPEN)
    bf.end_while(GATE)
    backend.drain_to_line_end(LINE_OPEN, WORKSPACE_BASE)

    _packed_to_hexlane_destructive(bf, token, value)
    print_hexlane_s64_compact(bf, value, PRINT_WORKSPACE_BASE)

    bf.set_const(token.byte(0), 10)
    bf.move(token.byte(0))
    bf.emit(".")
    return optimize_bf(bf.code())


def build_boundary_case(value: int) -> str:
    bf = BFEmitter()
    token = PackedI64Ref(TOKEN_BASE)
    word = HexLaneI64Ref(HEX_BASE)
    backend = BinaryStringListIO(bf, scratch_base=SCRATCH_BASE)
    backend.packed64.set_u64(token, value & MASK64)
    _packed_to_hexlane_destructive(bf, token, word)
    print_hexlane_s64_compact(bf, word, PRINT_WORKSPACE_BASE)
    return optimize_bf(bf.code())


def command_stats(code: str) -> dict[str, int | float]:
    movement = code.count("<") + code.count(">")
    return {
        "bytes": len(code),
        "movement": movement,
        "arithmetic": code.count("+") + code.count("-"),
        "control": code.count("[") + code.count("]"),
        "io": code.count(",") + code.count("."),
        "movement_fraction": movement / len(code) if code else 0.0,
    }


def verify_short_end_to_end(code: str) -> dict[str, int]:
    cases = {
        "0\n": "0\n",
        "1\n": "1\n",
        "-1\n": "-1\n",
        "9\n": "9\n",
        "10\n": "10\n",
        "42\n": "42\n",
        "   42   \n": "42\n",
        "12345\n": "12345\n",
        "-12345\n": "-12345\n",
    }
    max_steps = 0
    for raw_input, expected in cases.items():
        result = run_bf(code, input_data=raw_input, memory_size=900, step_limit=30_000_000)
        assert result.output == expected, (raw_input, result.output, expected)
        max_steps = max(max_steps, result.steps)
    return {"cases": len(cases), "max_steps": max_steps}


def verify_boundary_values() -> dict[str, int]:
    values = [
        0, 1, 15, 16, 255, 256, 123456789, -123456789,
        (1 << 31) - 1, 1 << 31, (1 << 63) - 1, -(1 << 63), -1,
    ]
    max_steps = 0
    max_bytes = 0
    for value in values:
        code = build_boundary_case(value)
        result = run_bf(code, memory_size=900, step_limit=20_000_000)
        expected = str(value)
        assert result.output == expected, (value, result.output, expected)
        max_steps = max(max_steps, result.steps)
        max_bytes = max(max_bytes, len(code))
    return {"cases": len(values), "max_steps": max_steps, "max_optimized_bytes": max_bytes}


def main() -> None:
    baseline = compile_source(SOURCE)
    hexlane = build_hexlane_direct_int()
    short_verification = verify_short_end_to_end(hexlane)
    boundary_verification = verify_boundary_values()

    payload = {
        "source": SOURCE,
        "baseline": command_stats(baseline),
        "hexlane_io_pipeline": command_stats(hexlane),
        "ratio": len(hexlane) / len(baseline),
        "saved_bytes": len(baseline) - len(hexlane),
        "saved_percent": 100.0 * (len(baseline) - len(hexlane)) / len(baseline),
        "verification": {
            "short_end_to_end": short_verification,
            "packed_boundary_pipeline": boundary_verification,
        },
        "layout": {
            "packed_input_cells": 8,
            "hexlane_persistent_cells": 34,
            "parser_workspace_base": WORKSPACE_BASE,
            "print_workspace_base": PRINT_WORKSPACE_BASE,
            "decimal_temp_record_stride": 25,
        },
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
