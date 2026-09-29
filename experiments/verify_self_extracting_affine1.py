from __future__ import annotations

"""Algebraic and BF differential checks for the data-driven AFFINE1 kernel."""

from random import Random

from bf_runtime import run_bf
from bfopt import optimize_bf
from self_extracting_affine1 import (
    AFFINE1_EXECUTOR,
    best_flat_affine_loop,
    data_driven_program,
    operation_accounting,
    reference_program,
)


def observable(result):
    return result.output, result.input_consumed, result.pointer, result.memory


def verify_case(x: int, y: int, coeff: int) -> None:
    ref = reference_program(x, y, coeff)
    vm = data_driven_program(x, y, coeff)
    opt = optimize_bf(vm)
    a = run_bf(ref, memory_size=32, step_limit=20_000_000)
    b = run_bf(vm, memory_size=32, step_limit=20_000_000)
    c = run_bf(opt, memory_size=32, step_limit=20_000_000)

    expected_target = (y + (x * coeff)) & 255
    assert a.pointer == b.pointer == c.pointer == 0
    assert a.memory[0] == b.memory[0] == c.memory[0] == 0
    assert a.memory[1] == b.memory[1] == c.memory[1] == expected_target
    assert all(v == 0 for v in b.memory[2:]), (x, y, coeff, b.memory)
    assert all(v == 0 for v in c.memory[2:]), (x, y, coeff, c.memory)
    assert observable(a) == observable(b), (x, y, coeff, observable(a), observable(b))
    assert observable(a) == observable(c), (x, y, coeff, observable(a), observable(c))


def verify_flat_formula() -> None:
    # Exhaustively verify the algebra used to choose the best flat reference.
    # We need not execute BF 65k*256 times: for odd control c, termination and
    # transfer count are exact modulo-256 group arithmetic.
    for coeff in range(256):
        src = best_flat_affine_loop(coeff)
        assert src.startswith("[") and src.endswith("]")
        if coeff == 0:
            assert src == "[-]"
            continue
        best_cost = len(src)
        for c in range(1, 256, 2):
            a = (-coeff * c) & 255
            # Source structural cost = brackets + two moves + shortest deltas.
            expected_cost = 4 + min(c, 256-c) + min(a, 256-a)
            assert best_cost <= expected_cost
            inv = pow(c, -1, 256)
            assert (-a * inv) & 255 == coeff


def main() -> None:
    verify_flat_formula()

    cases = []
    edges = [0, 1, 2, 15, 16, 31, 63, 64, 127, 128, 129, 254, 255]
    for x in (0, 1, 2, 127, 255):
        for coeff in edges:
            cases.append((x, 37, coeff))
    for y in (0, 1, 127, 128, 255):
        for coeff in (1, 3, 17, 127, 128, 255):
            cases.append((19, y, coeff))

    rng = Random(0xAFF1)
    for _ in range(80):
        cases.append((rng.randrange(256), rng.randrange(256), rng.randrange(256)))

    for case in cases:
        verify_case(*case)

    rows = [operation_accounting(k) for k in range(256)]
    mean_flat = sum(r["flat_loop_chars"] for r in rows) / 256
    mean_constructor = sum(r["coefficient_constructor_chars"] for r in rows) / 256
    print(f"AFFINE1 differential cases passed: {len(cases)}")
    print(f"AFFINE1 fixed executor chars: {len(AFFINE1_EXECUTOR)}")
    print(f"best-flat mean loop chars over all coefficients: {mean_flat:.3f}")
    print(f"runtime-coefficient mean constructor chars: {mean_constructor:.3f}")
    print(
        "shared-executor break-even intuition: after the executor exists once, "
        "each coefficient costs only its payload constructor rather than another flat loop"
    )


if __name__ == "__main__":
    main()
