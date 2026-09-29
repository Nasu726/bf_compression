from __future__ import annotations

"""Differential execution checks for the experimental dense radix-16 core."""

from bf_runtime import run_bf
from bfcore import BFEmitter
from bfopt import optimize_bf
from hex16_scalar_core import MASK64, Hex16I64Core, Hex16I64Ref


def decode(memory: list[int], ref: Hex16I64Ref) -> int:
    value = 0
    for i in range(16):
        digit = memory[ref.digit(i)]
        assert 0 <= digit < 16, (i, digit)
        value |= digit << (4 * i)
    return value


def run_case(a_value: int, b_value: int) -> None:
    bf = BFEmitter()
    a = Hex16I64Ref(0)
    b = Hex16I64Ref(20)
    add = Hex16I64Ref(40)
    sub = Hex16I64Ref(60)
    tmp = Hex16I64Ref(80)
    result = 100
    scratch = 104
    core = Hex16I64Core(bf, scratch)

    core.set_u64(a, a_value)
    core.set_u64(b, b_value)
    core.add64(add, a, b)
    core.sub64(sub, a, b)
    core.uge64(result, a, b, tmp)

    code = optimize_bf(bf.code())
    execution = run_bf(code, memory_size=256, step_limit=80_000_000)
    memory = execution.memory

    ua = a_value & MASK64
    ub = b_value & MASK64
    assert decode(memory, a) == ua
    assert decode(memory, b) == ub
    assert decode(memory, add) == (ua + ub) & MASK64
    assert decode(memory, sub) == (ua - ub) & MASK64
    assert memory[result] == int(ua >= ub)
    assert all(memory[scratch + i] == 0 for i in range(core.SCRATCH_CELLS))


def main() -> None:
    cases = [
        (0, 0),
        (0, 1),                    # borrow through all sixteen nibbles
        (MASK64, 1),               # carry through all sixteen nibbles
        (15, 1),                   # carry across one nibble boundary
        (16, 15),
        (0xFEDCBA9876543210, 0x0123456789ABCDEF),
        (1 << 63, (1 << 63) - 1),
        (0x1111111111111111, 0xEEEEEEEEEEEEEEEE),
    ]
    for a, b in cases:
        run_case(a, b)
    print(f"hex16 differential cases passed: {len(cases)}")


if __name__ == "__main__":
    main()
