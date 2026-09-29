from __future__ import annotations

"""Full-state checks and source accounting for balanced-nibble payload channel."""

from random import Random

from bf_runtime import run_bf
from bfopt import optimize_bf
from self_extracting_balanced_nibble_channel import (
    DECODER,
    build_program,
    decoded_cell_index,
    source_accounting,
)


def verify_blob(blob: bytes) -> tuple[int, int]:
    program = build_program(blob)
    optimized = optimize_bf(program)
    memory_size = max(64, 3 * (len(blob) + 2) + 16)

    for source in (program, optimized):
        result = run_bf(source, memory_size=memory_size, step_limit=50_000_000)
        assert result.output == ""
        assert result.input_consumed == 0
        assert result.pointer == 0

        expected_nonzero = {decoded_cell_index(i): value for i, value in enumerate(blob) if value}
        actual_nonzero = {i: value for i, value in enumerate(result.memory) if value}
        assert actual_nonzero == expected_nonzero, (blob, expected_nonzero, actual_nonzero)

    return len(program), len(optimized)


def main() -> None:
    cases = [
        b"",
        b"\x00",
        b"\xff",
        b"\x08\x78\x80\x88",
        bytes(range(16)),
        bytes(range(256)),
        b"hello, compressed BF",
    ]
    rng = Random(0xB17E)
    for length in (1, 2, 3, 8, 31, 64, 257):
        cases.append(bytes(rng.randrange(256) for _ in range(length)))

    totals = [verify_blob(blob) for blob in cases]
    sample = bytes(range(256))
    acc = source_accounting(sample)

    print(f"balanced-nibble channel cases passed: {len(cases)}")
    print(f"fixed decoder chars: {acc['fixed_decoder_chars']}")
    print(
        "uniform-byte sample: "
        f"payload={acc['payload_constructor_chars']:,} "
        f"full={acc['total_chars']:,} "
        f"chars_per_byte={acc['chars_per_byte']:.4f}"
    )
    print(
        f"aggregate generated source: raw={sum(a for a, _ in totals):,} "
        f"optimized={sum(b for _, b in totals):,}"
    )
    print(f"decoder body chars: {len(DECODER)}")


if __name__ == "__main__":
    main()
