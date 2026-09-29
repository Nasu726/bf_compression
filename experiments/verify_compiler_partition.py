from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dead_affine_target_opt import (
    optimize_region_zero_dead_affine,
    optimize_region_zero_dead_affine_fixedpoint,
)
from region_zero_opt import optimize_region_zero
from bf_runtime import run_bf


def observable(result):
    # Step count is intentionally excluded: shortening may change execution
    # cost. Preserve output, input consumption, final pointer and full tape.
    return result.output, result.input_consumed, result.pointer, result.memory


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("program", type=Path)
    ap.add_argument(
        "--optimizer",
        choices=(
            "region-zero",
            "region-zero-dead-affine",
            "region-zero-dead-affine-fixedpoint",
        ),
        default="region-zero",
    )
    args = ap.parse_args()

    original = args.program.read_text(encoding="ascii")
    if args.optimizer == "region-zero":
        optimized = optimize_region_zero(original)
        suffix = ".region-zero.bf"
    elif args.optimizer == "region-zero-dead-affine":
        optimized = optimize_region_zero_dead_affine(original)
        suffix = ".region-zero-dead-affine.bf"
    else:
        optimized = optimize_region_zero_dead_affine_fixedpoint(original)
        suffix = ".region-zero-dead-affine-fixedpoint.bf"
    out_path = args.program.with_name(args.program.stem + suffix)
    out_path.write_text(optimized, encoding="ascii")

    cases = [
        [1, 2, 3, 4],
        [5, -2, 10, 1234, -77],
        [100],
        list(range(12)),
    ]
    for values in cases:
        data = f"{len(values)}\n" + " ".join(map(str, values)) + "\n"
        a = run_bf(original, data, memory_size=30_000, step_limit=1_000_000_000)
        b = run_bf(optimized, data, memory_size=30_000, step_limit=1_000_000_000)
        assert observable(a) == observable(b), (
            values,
            args.optimizer,
            a.output,
            b.output,
            a.input_consumed,
            b.input_consumed,
            a.pointer,
            b.pointer,
        )
        print(
            f"case_n={len(values)} output={a.output.strip()!r} "
            f"steps_original={a.steps} steps_optimized={b.steps}"
        )

    print(
        f"compiler partition differential [{args.optimizer}]: OK; "
        f"{len(original)} -> {len(optimized)} bytes "
        f"({len(original) - len(optimized)} saved)"
    )


if __name__ == "__main__":
    main()
