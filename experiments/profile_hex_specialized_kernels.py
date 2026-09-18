from __future__ import annotations

"""Measure source budget of the specialized stride-66 hexadecimal path.

The partition specialization does not primarily use Quad64 scalars, so generic
backend attribution alone cannot prioritize the 10x work.  This profiler records
raw command composition for its cached hexadecimal kernels and the cumulative
whole-program checkpoints exposed by the compiler itself.
"""

import json

from bfcontestpartition import partition_program_size_breakdown
from bfhexcounted_prefix import _counted_record_body
from bfhexpartition_prefix import partition_body
from bfhexradixfast import add_data_to_total_kernel


def describe(code: str) -> dict[str, int | float]:
    movement = code.count(">") + code.count("<")
    return {
        "bytes": len(code),
        "movement": movement,
        "movement_fraction": movement / len(code) if code else 0.0,
        "arithmetic": code.count("+") + code.count("-"),
        "control": code.count("[") + code.count("]"),
        "io": code.count(",") + code.count("."),
    }


def main() -> None:
    # initial_ans=10_000_000 has hexadecimal extent 6 in the current bounded
    # partition lowering and is the standard benchmark configuration.
    kernels = {
        "add_data_to_total": describe(add_data_to_total_kernel()),
        "counted_prefix_record_body": describe(_counted_record_body()),
        "partition_prefix_body_extent6": describe(partition_body(6)),
    }
    checkpoints = partition_program_size_breakdown(initial_ans=10_000_000)
    print(
        json.dumps(
            {
                "record_stride": 66,
                "kernels": kernels,
                "partition_cumulative_raw_and_optimized": checkpoints,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
