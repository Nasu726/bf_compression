from __future__ import annotations

"""Differential execution for the compact HexLane signed decimal printer."""

from bf_runtime import run_bf
from bfcore import BFEmitter
from bfopt import optimize_bf
from hexlane_scalar_core import HexLaneI64Core, HexLaneI64Ref
from hexlane_decimal_print import print_hexlane_s64_compact

MASK64 = (1 << 64) - 1


def signed64(value: int) -> int:
    value &= MASK64
    return value - (1 << 64) if value & (1 << 63) else value


def run_case(value: int) -> tuple[int, int]:
    bf = BFEmitter()
    ref = HexLaneI64Ref(0)
    core = HexLaneI64Core(bf)
    core.set_u64(ref, value)
    print_hexlane_s64_compact(bf, ref, workspace_base=40)
    code = optimize_bf(bf.code())
    result = run_bf(code, memory_size=700, step_limit=300_000_000)
    expected = str(signed64(value)).encode()
    assert result.output == expected, (value, result.output, expected)

    decoded = sum((result.memory[ref.value(i)] & 0xF) << (4 * i) for i in range(16))
    assert decoded == (value & MASK64)
    assert all(result.memory[ref.marker(i)] == 0 for i in range(17))
    return len(code), result.steps


def main() -> None:
    values = [
        0,
        1,
        9,
        10,
        15,
        16,
        99,
        100,
        123456789,
        (1 << 31) - 1,
        1 << 63,
        (1 << 63) - 1,
        MASK64,
        -123456789,
    ]
    max_code = max_steps = 0
    for value in values:
        code, steps = run_case(value)
        max_code = max(max_code, code)
        max_steps = max(max_steps, steps)
    print(f"hexlane decimal cases passed: {len(values)}")
    print(f"max optimized full snippet bytes: {max_code}")
    print(f"max runtime steps: {max_steps}")


if __name__ == "__main__":
    main()
