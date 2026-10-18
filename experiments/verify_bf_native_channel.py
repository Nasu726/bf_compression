from __future__ import annotations

from profile_bf_native_channel import (
    OPT16_DEPTHS,
    channel_capacity,
    decode_cells_to_bits,
    encode_bits_to_cells,
    expected_rate,
    full_tree_depth_multisets,
    loader_source_for_bytes,
    optimal_depths,
    prefix16_entries,
)


def main() -> None:
    cap = channel_capacity()
    assert 1.2715 < cap < 1.2716, cap

    depths, rate = optimal_depths(16)
    assert depths == OPT16_DEPTHS, (depths, OPT16_DEPTHS)
    assert abs(sum(2.0 ** -d for d in depths) - 1.0) < 1e-15
    assert 1.2479 < rate < 1.2480, rate
    assert rate / cap > 0.981

    # The exhaustive space is small enough that this check is meaningful in CI,
    # rather than trusting a precomputed tree shape.
    assert len(full_tree_depth_multisets(16)) == 1639
    for candidate in full_tree_depth_multisets(16):
        assert expected_rate(candidate, [e.value for e in prefix16_entries()]) <= rate + 1e-15

    entries = prefix16_entries()
    words = [f"{e.code:0{e.length}b}" for e in entries]
    for i, a in enumerate(words):
        for j, b in enumerate(words):
            if i != j:
                assert not b.startswith(a), (a, b)

    payloads = [
        b"",
        b"\x00",
        b"\xff",
        bytes(range(256)),
        b"Brainfuck global compression" * 17,
    ]
    for blob in payloads:
        bits = "".join(f"{x:08b}" for x in blob)
        cells, padding = encode_bits_to_cells(bits)
        recovered = decode_cells_to_bits(cells)
        assert recovered[: len(bits)] == bits
        assert recovered[len(bits):] == "0" * padding
        source, p2 = loader_source_for_bytes(blob)
        assert p2 == padding
        assert set(source) <= set("+->")
        # Each emitted cell advances exactly once, so this also checks the
        # literal source-cost accounting used by the theoretical model.
        assert source.count(">") == len(cells)

    print(
        "BF-native payload channel verification: ok; "
        f"capacity={cap:.9f} bit/char; prefix16={rate:.9f} bit/char"
    )


if __name__ == "__main__":
    main()
