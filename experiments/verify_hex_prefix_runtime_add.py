from __future__ import annotations

"""Differential BF checks for the moving-lane stored-prefix add kernel."""

from random import Random

from bf_runtime import run_bf
from bfcore import BFEmitter
from bfopt import optimize_bf
from bfhexradixfast import add_data_to_total_kernel
from bfhexseq import ANS, BACK, DATA, HEX_DIGITS, LEFT, MARKER, TOTAL, _RelativeBuilder
from hex_prefix_runtime_add import destructive_add_data_to_total_runtime

MASK64 = (1 << 64) - 1


def set_hex(bf: BFEmitter, base: int, value: int) -> None:
    value &= MASK64
    for i in range(HEX_DIGITS):
        bf.set_const(base + i, (value >> (4 * i)) & 0xF)


def read_hex(memory: list[int], base: int) -> int:
    return sum((memory[base + i] & 0xF) << (4 * i) for i in range(HEX_DIGITS))


def build_runtime_case(data: int, total: int) -> tuple[str, int, int, list[int]]:
    bf = BFEmitter()
    # Sentinel values ensure unrelated record state is untouched.
    bf.set_const(MARKER, 7)
    bf.set_const(BACK, 3)
    set_hex(bf, ANS, 0x123456789ABCDEF0)
    set_hex(bf, DATA, data)
    set_hex(bf, TOTAL, total)
    for i in range(HEX_DIGITS):
        bf.clear(LEFT + i)

    r = _RelativeBuilder()
    destructive_add_data_to_total_runtime(r)
    bf.move(0)
    bf.emit(r.code())
    code = optimize_bf(bf.code())
    result = run_bf(code, memory_size=160, step_limit=80_000_000)
    return code, result.steps, result.memory, result.output


def main() -> None:
    cases = [
        (0, 0),
        (1, 0),
        (0, 1),
        (15, 1),
        (0xF, 0x1),
        (0xFFFF, 1),
        (MASK64, 1),
        (0xFEDCBA9876543210, 0x0123456789ABCDEF),
        (0x1111111111111111, 0xEEEEEEEEEEEEEEEE),
    ]
    rng = Random(0xBFC0DE)
    cases.extend((rng.getrandbits(64), rng.getrandbits(64)) for _ in range(16))

    max_steps = 0
    for data, total in cases:
        code, steps, memory, output = build_runtime_case(data, total)
        max_steps = max(max_steps, steps)
        assert output == b""
        assert read_hex(memory, TOTAL) == (data + total) & MASK64
        assert read_hex(memory, DATA) == 0
        assert all(memory[LEFT + i] == 0 for i in range(HEX_DIGITS))
        assert memory[MARKER] == 7
        assert memory[BACK] == 3
        assert read_hex(memory, ANS) == 0x123456789ABCDEF0

    # Source opportunity: compare the operation bodies without setup constants.
    r = _RelativeBuilder()
    destructive_add_data_to_total_runtime(r)
    runtime_body = r.code()
    old_body = add_data_to_total_kernel()
    print(f"runtime-lane cases passed: {len(cases)}")
    print(f"old add kernel bytes: {len(old_body)}")
    print(f"runtime-lane destructive kernel bytes: {len(runtime_body)}")
    print(f"source ratio: {len(runtime_body) / len(old_body):.6f}")
    print(f"max runtime steps in verification: {max_steps}")


if __name__ == "__main__":
    main()
