from __future__ import annotations

"""Full-state checks for the mixed-radix 8/8/4 BF payload channel."""

from random import Random

from bf_runtime import run_bf
from bfopt import optimize_bf
from self_extracting_balanced_octal_channel import (
    DECODER,
    build_program,
    decoded_cell_index,
    source_accounting,
)


def verify_blob(blob: bytes) -> tuple[int, int]:
    program = build_program(blob)
    optimized = optimize_bf(program)
    memory_size = max(64, 4 * (len(blob) + 2) + 16)

    for source in (program, optimized):
        result = run_bf(source, memory_size=memory_size, step_limit=50_000_000)
        assert result.output == ""
        assert result.input_consumed == 0
        assert result.pointer == 0
        expected = {decoded_cell_index(i): value for i, value in enumerate(blob) if value}
        actual = {i: value for i, value in enumerate(result.memory) if value}
        assert actual == expected, (blob, expected, actual)
    return len(program), len(optimized)


def main() -> None:
    cases = [
        b"",
        b"\x00",
        b"\xff",
        bytes(range(16)),
        bytes(range(256)),
        b"hello, compressed BF",
    ]
    rng = Random(0x8A4)
    for length in (1, 2, 3, 8, 31, 64, 257):
        cases.append(bytes(rng.randrange(256) for _ in range(length)))

    totals = [verify_blob(blob) for blob in cases]
    sample = bytes(range(256))
    acc = source_accounting(sample)
    print(f"balanced-octal channel cases passed: {len(cases)}")
    print(f"fixed decoder chars: {acc['fixed_decoder_chars']}")
    print(
        "uniform-byte sample: "
        f"payload={acc['payload_constructor_chars']:,} "
        f"full={acc['total_chars']:,} chars_per_byte={acc['chars_per_byte']:.4f}"
    )
    print(
        f"aggregate generated source: raw={sum(a for a, _ in totals):,} "
        f"optimized={sum(b for _, b in totals):,}"
    )
    print(f"decoder body chars: {len(DECODER)}")


if __name__ == "__main__":
    main()
