from __future__ import annotations

"""Source-size-only profile for the direct-int HexLane pipeline.

Kept separate from execution verification because the inherited packed decimal
parser is intentionally runtime-heavy.  This module performs no BF execution.
"""

import json

from bench_direct_int_hexlane_pipeline import (
    SOURCE,
    build_hexlane_direct_int,
    command_stats,
)
from compiler_layout import compile_source


def main() -> None:
    baseline = compile_source(SOURCE)
    candidate = build_hexlane_direct_int()
    payload = {
        "source": SOURCE,
        "baseline": command_stats(baseline),
        "hexlane_io_pipeline": command_stats(candidate),
        "ratio": len(candidate) / len(baseline),
        "saved_bytes": len(baseline) - len(candidate),
        "saved_percent": 100.0 * (len(baseline) - len(candidate)) / len(baseline),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
