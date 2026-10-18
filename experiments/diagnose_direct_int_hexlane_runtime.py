from __future__ import annotations

"""Isolate runtime cost/correctness in the direct-int HexLane experiment."""

import json

from bf_runtime import BFExecutionError, run_bf
from bfcore import BFEmitter
from bfopt import optimize_bf
from bfpacked64 import PackedI64Ref
from bfstringlists import BinaryStringListIO
from bench_direct_int_hexlane_pipeline import (
    END_LINE,
    HAS_TOKEN,
    HEX_BASE,
    LINE_OPEN,
    MASK64,
    SCRATCH_BASE,
    TOKEN_BASE,
    WORKSPACE_BASE,
    _packed_to_hexlane_destructive,
)
from hexlane_decimal_print import print_hexlane_s64_compact
from hexlane_scalar_core import HexLaneI64Ref


def stats(code: str) -> dict[str, int | float]:
    move = code.count('<') + code.count('>')
    return {
        'bytes': len(code),
        'movement': move,
        'movement_fraction': move / len(code) if code else 0.0,
    }


def run_limited(code: str, *, input_data: str = '', limit: int = 20_000_000):
    try:
        result = run_bf(code, input_data=input_data, memory_size=900, step_limit=limit)
        return result, {'status': 'ok', 'steps': result.steps}
    except BFExecutionError as exc:
        return None, {'status': 'step_limit', 'limit': limit, 'error': str(exc)}


def parser_code() -> str:
    bf = BFEmitter()
    token = PackedI64Ref(TOKEN_BASE)
    backend = BinaryStringListIO(bf, scratch_base=SCRATCH_BASE)
    backend.packed64.clear(token)
    bf.set_const(LINE_OPEN, 1)
    backend.read_packed_s64_line_token(token, HAS_TOKEN, END_LINE, WORKSPACE_BASE)
    return optimize_bf(bf.code())


def converter_code(value: int) -> str:
    bf = BFEmitter()
    token = PackedI64Ref(TOKEN_BASE)
    word = HexLaneI64Ref(HEX_BASE)
    backend = BinaryStringListIO(bf, scratch_base=SCRATCH_BASE)
    backend.packed64.set_u64(token, value & MASK64)
    _packed_to_hexlane_destructive(bf, token, word)
    return optimize_bf(bf.code())


def composition_code(value: int) -> str:
    bf = BFEmitter()
    token = PackedI64Ref(TOKEN_BASE)
    word = HexLaneI64Ref(HEX_BASE)
    backend = BinaryStringListIO(bf, scratch_base=SCRATCH_BASE)
    backend.packed64.set_u64(token, value & MASK64)
    _packed_to_hexlane_destructive(bf, token, word)
    print_hexlane_s64_compact(bf, word, WORKSPACE_BASE)
    return optimize_bf(bf.code())


def decode_hex(memory: list[int]) -> int:
    ref = HexLaneI64Ref(HEX_BASE)
    return sum((memory[ref.value(i)] & 0xF) << (4 * i) for i in range(16))


def main() -> None:
    payload: dict[str, object] = {}

    pcode = parser_code()
    parser_cases = {}
    for raw, expected in [('0\n', 0), ('1\n', 1), ('10\n', 10), ('-1\n', MASK64)]:
        result, meta = run_limited(pcode, input_data=raw, limit=20_000_000)
        if result is not None:
            packed = sum((result.memory[TOKEN_BASE + i] & 0xFF) << (8 * i) for i in range(8))
            meta['packed'] = packed
            meta['correct'] = packed == expected
        parser_cases[repr(raw)] = meta
    payload['parser_only'] = {'source': stats(pcode), 'cases': parser_cases}

    conversion_cases = {}
    for value in [0, 1, 15, 16, 255, 256, 123456789, MASK64, 1 << 63]:
        code = converter_code(value)
        result, meta = run_limited(code, limit=5_000_000)
        if result is not None:
            decoded = decode_hex(result.memory)
            meta['decoded'] = decoded
            meta['correct'] = decoded == (value & MASK64)
        meta['source'] = stats(code)
        conversion_cases[str(value)] = meta
    payload['packed_to_hexlane'] = conversion_cases

    composition_cases = {}
    for value in [0, 1, -1, 123456789, -123456789, (1 << 63) - 1, -(1 << 63)]:
        code = composition_code(value)
        result, meta = run_limited(code, limit=10_000_000)
        if result is not None:
            meta['output'] = result.output
            meta['correct'] = result.output == str(value)
        meta['source'] = stats(code)
        composition_cases[str(value)] = meta
    payload['packed_to_hexlane_to_print'] = composition_cases

    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
