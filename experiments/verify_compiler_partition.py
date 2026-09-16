from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from region_zero_opt import optimize_region_zero
from bf_runtime import run_bf


def observable(result):
    # Step count is intentionally excluded: shortening may change execution
    # cost. Preserve output, input consumption, final pointer and full tape.
    return result.output, result.input_consumed, result.pointer, result.memory


def main() -> None:
    path = Path(sys.argv[1])
    original = path.read_text(encoding="ascii")
    optimized = optimize_region_zero(original)
    out_path = path.with_name(path.stem + ".region-zero.bf")
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
            a.output,
            b.output,
            a.input_consumed,
            b.input_consumed,
            a.pointer,
            b.pointer,
        )
        print(
            f"case_n={len(values)} output={a.output.strip()!r} "
            f"steps_original={a.steps} steps_region_zero={b.steps}"
        )

    print(
        f"compiler partition differential: OK; "
        f"{len(original)} -> {len(optimized)} bytes "
        f"({len(original) - len(optimized)} saved)"
    )


if __name__ == "__main__":
    main()
