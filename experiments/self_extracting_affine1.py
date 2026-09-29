from __future__ import annotations

"""Data-driven exact affine transfer kernel for standard Brainfuck.

The kernel implements the semantic instruction

    AFFINE1(k): (x, y) -> (0, y + k*x mod 256)

on logical cells 0 and 1.  The coefficient ``k`` is data in cell 2 rather than
being unrolled into the BF source.  Cell 3 is zero scratch.  The kernel consumes
all metadata and exits at cell 0, so its observable final tape is exactly the
two-cell affine map followed by zeros.

This is the first runtime implementation of the semantic ``AFFINE`` family used
by the grammar profiler.  A single occurrence is not expected to beat the best
flat BF spelling; the compression opportunity comes from sharing this fixed
kernel across many differently-parameterized AFFINE instructions.
"""


def shortest_byte_delta(value: int) -> str:
    value &= 255
    if value <= 128:
        return "+" * value
    return "-" * (256 - value)


def signed_cost(value: int) -> int:
    value &= 255
    return min(value, 256 - value)


def best_flat_affine_loop(coeff: int) -> str:
    """Shortest one-target odd-control flat loop for the same exact map.

    A flat loop with control delta ``c`` and target delta ``a`` maps
    ``y -> y - x*a*c^{-1}`` for odd c.  Therefore ``a = -coeff*c`` gives the
    requested ``y + coeff*x`` map.  We search all 128 odd controls using the
    shortest +/- spelling for both deltas.
    """
    coeff &= 255
    if coeff == 0:
        return "[-]"
    best: str | None = None
    for c in range(1, 256, 2):
        a = (-coeff * c) & 255
        control_src = shortest_byte_delta(c)
        target_src = shortest_byte_delta(a)
        candidate = "[" + control_src + ">" + target_src + "<]"
        if best is None or len(candidate) < len(best):
            best = candidate
    assert best is not None
    return best


# Entry: cell 0 (x).  Tape prefix is [x, y, k, 0].
#
# For every unit of x, copy k into y while restoring k through cell 3.  Runtime
# is intentionally expensive; literal source length is the objective.  Once x
# reaches zero, coefficient metadata is cleared and the pointer returns to 0.
AFFINE1_EXECUTOR = "[->>[-<+>>+<]>[-<+>]<<<]>>[-]<<"


def reference_program(x: int, y: int, coeff: int) -> str:
    """Self-contained reference using the best flat odd-control affine loop."""
    return (
        shortest_byte_delta(x)
        + ">"
        + shortest_byte_delta(y)
        + "<"
        + best_flat_affine_loop(coeff)
    )


def data_driven_program(x: int, y: int, coeff: int) -> str:
    """Self-contained program whose affine coefficient is runtime payload data."""
    return (
        shortest_byte_delta(x)
        + ">"
        + shortest_byte_delta(y)
        + ">"
        + shortest_byte_delta(coeff)
        + "<<"
        + AFFINE1_EXECUTOR
    )


def operation_accounting(coeff: int) -> dict[str, int]:
    """Compare the affine-operation portion, excluding common x/y setup."""
    return {
        "coefficient": coeff & 255,
        "flat_loop_chars": len(best_flat_affine_loop(coeff)),
        "coefficient_constructor_chars": 2 + signed_cost(coeff),  # > k <<
        "shared_executor_chars": len(AFFINE1_EXECUTOR),
        "standalone_data_driven_operation_chars": 2 + signed_cost(coeff) + len(AFFINE1_EXECUTOR),
    }
