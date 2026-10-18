from __future__ import annotations

"""Differential checks for marker+nibble radix-16 scalar arithmetic."""

from bf_runtime import run_bf
from bfcore import BFEmitter
from bfopt import optimize_bf
from hexlane_scalar_core import MASK64, HexLaneI64Core, HexLaneI64Ref


def decode(memory: list[int], ref: HexLaneI64Ref) -> int:
    value = 0
    for i in range(16):
        digit = memory[ref.value(i)]
        assert 0 <= digit < 16, (i, digit)
        value |= digit << (4 * i)
    return value


def markers_zero(memory: list[int], ref: HexLaneI64Ref) -> bool:
    return all(memory[ref.marker(i)] == 0 for i in range(17))


def run_case(a_value: int, b_value: int) -> None:
    bf = BFEmitter()
    gap = 40
    a = HexLaneI64Ref(0)
    b = HexLaneI64Ref(gap)
    add = HexLaneI64Ref(2 * gap)
    sub = HexLaneI64Ref(3 * gap)
    tmp = HexLaneI64Ref(4 * gap)
    ge = 5 * gap
    core = HexLaneI64Core(bf)

    core.set_u64(a, a_value)
    core.set_u64(b, b_value)
    core.add64(add, a, b)
    core.sub64(sub, a, b)
    core.uge64(ge, a, b, tmp)

    code = optimize_bf(bf.code())
    result = run_bf(code, memory_size=320, step_limit=80_000_000)
    memory = result.memory
    ua = a_value & MASK64
    ub = b_value & MASK64

    assert decode(memory, a) == ua
    assert decode(memory, b) == ub
    assert decode(memory, add) == (ua + ub) & MASK64
    assert decode(memory, sub) == (ua - ub) & MASK64
    assert memory[ge] == int(ua >= ub)
    for ref in (a, b, add, sub, tmp):
        assert markers_zero(memory, ref), ref


def main() -> None:
    cases = [
        (0, 0),
        (0, 1),
        (MASK64, 1),
        (15, 1),
        (16, 15),
        (0xFEDCBA9876543210, 0x0123456789ABCDEF),
        (1 << 63, (1 << 63) - 1),
        (0x1111111111111111, 0xEEEEEEEEEEEEEEEE),
    ]
    for a, b in cases:
        run_case(a, b)
    print(f"hexlane differential cases passed: {len(cases)}")


if __name__ == "__main__":
    main()
