from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from region_zero_opt import optimize_region_zero
from bf_runtime import run_bf


def observable(result):
    return result.output, result.input_consumed, result.pointer, result.memory


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("program", type=Path)
    ap.add_argument("--input-file", type=Path, required=True)
    ap.add_argument("--expected-file", type=Path)
    ap.add_argument("--memory-size", type=int, default=300_000)
    ap.add_argument("--step-limit", type=int, default=1_000_000_000)
    args = ap.parse_args()

    original = args.program.read_text(encoding="ascii")
    optimized = optimize_region_zero(original)
    data = args.input_file.read_text(encoding="ascii")

    a = run_bf(
        original,
        data,
        memory_size=args.memory_size,
        step_limit=args.step_limit,
    )
    b = run_bf(
        optimized,
        data,
        memory_size=args.memory_size,
        step_limit=args.step_limit,
    )
    assert observable(a) == observable(b), (
        args.program,
        a.output,
        b.output,
        a.input_consumed,
        b.input_consumed,
        a.pointer,
        b.pointer,
    )
    if args.expected_file is not None:
        expected = args.expected_file.read_text(encoding="ascii")
        assert a.output == expected, (a.output, expected)

    out_path = args.program.with_name(args.program.stem + ".region-zero.bf")
    out_path.write_text(optimized, encoding="ascii")
    print(
        f"{args.program.name}: differential OK; "
        f"{len(original)} -> {len(optimized)} bytes; "
        f"steps {a.steps} -> {b.steps}"
    )


if __name__ == "__main__":
    main()
