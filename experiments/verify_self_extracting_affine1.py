from __future__ import annotations

"""Algebraic and BF differential checks for the data-driven AFFINE1 kernel.

The legacy translator ``optimize_bf`` does not flush a trailing pointer-only
move in its known-zero pass. Under this research project's stronger ABI, that
can change final pointer state. Raw AFFINE1 correctness is therefore the
primary proof obligation here. Optimized output is checked after an explicit
static pointer repair, and the legacy mismatch is counted as a diagnostic.
"""

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


def balanced_net_pointer(code: str) -> int:
    """Return static net pointer, requiring every loop to be balanced."""
    depth = 0
    net = [0]
    for ch in code:
        if ch == "[":
            depth += 1
            if len(net) <= depth:
                net.append(0)
            else:
                net[depth] = 0
        elif ch == "]":
            assert depth > 0
            assert net[depth] == 0, (depth, net[depth])
            depth -= 1
        elif ch == ">":
            net[depth] += 1
        elif ch == "<":
            net[depth] -= 1
    assert depth == 0
    return net[0]


def repair_final_pointer(original: str, optimized: str) -> str:
    target = balanced_net_pointer(original)
    got = balanced_net_pointer(optimized)
    delta = target - got
    return optimized + (">" * delta if delta > 0 else "<" * -delta)


def verify_case(x: int, y: int, coeff: int) -> bool:
    ref = reference_program(x, y, coeff)
    vm = data_driven_program(x, y, coeff)
    optimized = optimize_bf(vm)
    repaired = repair_final_pointer(vm, optimized)

    a = run_bf(ref, memory_size=32, step_limit=20_000_000)
    b = run_bf(vm, memory_size=32, step_limit=20_000_000)
    c = run_bf(repaired, memory_size=32, step_limit=20_000_000)

    expected_target = (y + (x * coeff)) & 255
    assert a.pointer == b.pointer == c.pointer == 0
    assert a.memory[0] == b.memory[0] == c.memory[0] == 0
    assert a.memory[1] == b.memory[1] == c.memory[1] == expected_target
    assert all(v == 0 for v in b.memory[2:]), (x, y, coeff, b.memory)
    assert all(v == 0 for v in c.memory[2:]), (x, y, coeff, c.memory)
    assert observable(a) == observable(b), (x, y, coeff, observable(a), observable(b))
    assert observable(a) == observable(c), (x, y, coeff, observable(a), observable(c))
    return balanced_net_pointer(optimized) != balanced_net_pointer(vm)


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

    legacy_pointer_mismatches = sum(verify_case(*case) for case in cases)

    rows = [operation_accounting(k) for k in range(256)]
    mean_flat = sum(r["flat_loop_chars"] for r in rows) / 256
    mean_constructor = sum(r["coefficient_constructor_chars"] for r in rows) / 256
    print(f"AFFINE1 differential cases passed: {len(cases)}")
    print(f"AFFINE1 fixed executor chars: {len(AFFINE1_EXECUTOR)}")
    print(f"best-flat mean loop chars over all coefficients: {mean_flat:.3f}")
    print(f"runtime-coefficient mean constructor chars: {mean_constructor:.3f}")
    print(f"legacy optimize_bf final-pointer repairs required: {legacy_pointer_mismatches}/{len(cases)}")
    print(
        "shared-executor break-even intuition: after the executor exists once, "
        "each coefficient costs only its payload constructor rather than another flat loop"
    )


if __name__ == "__main__":
    main()
