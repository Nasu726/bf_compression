from __future__ import annotations

"""Exhaustively verify the modular iteration-count formula used by the profiler."""

import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_exact_loop_summary import inv_mod_odd


def predicted_iterations(c: int, x: int) -> int | None:
    c &= 255
    x &= 255
    if c == 0 or x == 0:
        return None
    g = math.gcd(c, 256)
    if x % g:
        return None
    modulus = 256 // g
    return ((-x // g) * inv_mod_odd(c // g, modulus)) % modulus


def observed_iterations(c: int, x: int) -> int | None:
    value = x & 255
    for k in range(1, 257):
        value = (value + c) & 255
        if value == 0:
            return k
    return None


def main() -> None:
    # Exhaust every nonzero control update and nonzero entry value.
    for c in range(1, 256):
        for x in range(1, 256):
            pred = predicted_iterations(c, x)
            obs = observed_iterations(c, x)
            assert pred == obs, (c, x, pred, obs)
            if pred is not None:
                # Check several target coefficients: repeated loop updates equal
                # one summarized modular addition.
                for a in (1, 2, 3, 17, 127, 128, 255):
                    repeated = 0
                    for _ in range(pred):
                        repeated = (repeated + a) & 255
                    assert repeated == (pred * a) & 255

    print("exact affine loop summary congruence: OK")


if __name__ == "__main__":
    main()
