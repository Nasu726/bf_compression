from __future__ import annotations

"""BF-native static payload channels with proved source-cost models.

A standalone Brainfuck program cannot read its own source. Static compressed
payload therefore has to be *constructed* on the tape by executable BF before a
VM/decoder can consume it.

Two fully realizable channels are measured.

Direct-byte channel
-------------------
One serialized payload byte is one fresh tape cell. Value ``v`` is written by
the shorter of ``v`` pluses or ``256-v`` minuses, then ``>`` advances. Thus

    c(v) = 1 + min(v, 256-v).

This needs no payload decoder at all: the semantic VM reads the serialized bytes
directly. It can be especially good for structured formats dominated by small
opcodes/ULEB values.

Generic-bit channel
-------------------
For arbitrary incompressible bits, unequal-cost coding over the same direct-cell
alphabet has capacity C determined by

    sum_v 2**(-C*c(v)) = 1.

To keep the decoder tiny, we use only the 16 cheapest cell values and an actual
binary prefix code. Its tree is not heuristic: CI exhaustively enumerates every
full binary prefix-tree leaf-depth multiset with 16 leaves and verifies that the
selected tree maximizes expected payload bits per BF source character.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable


def cell_cost(value: int) -> int:
    value &= 255
    return 1 + min(value, 256 - value)


def signed_cell_value(value: int) -> int:
    value &= 255
    return value if value <= 128 else value - 256


def direct_initializer_fragment(value: int) -> str:
    """Shortest literal +/- initialization of one fresh zero cell, then >."""
    value &= 255
    if value <= 128:
        return "+" * value + ">"
    return "-" * (256 - value) + ">"


def direct_byte_loader_chars(blob: bytes) -> int:
    """Exact source length for writing serialized bytes directly to fresh cells."""
    return sum(cell_cost(value) for value in blob)


def direct_byte_loader_source(blob: bytes) -> str:
    return "".join(direct_initializer_fragment(value) for value in blob)


def channel_capacity(tol: float = 1e-14) -> float:
    """Solve sum 2^(-C*c(v)) = 1 by bisection."""
    lo, hi = 0.0, 4.0
    while hi - lo > tol:
        mid = (lo + hi) / 2
        mass = sum(2.0 ** (-mid * cell_cost(v)) for v in range(256))
        if mass > 1.0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


@lru_cache(maxsize=None)
def full_tree_depth_multisets(leaves: int) -> frozenset[tuple[int, ...]]:
    """All unordered leaf-depth multisets of full binary trees."""
    if leaves == 1:
        return frozenset({(0,)})
    out: set[tuple[int, ...]] = set()
    for left in range(1, leaves):
        right = leaves - left
        if left > right:
            continue
        for a in full_tree_depth_multisets(left):
            for b in full_tree_depth_multisets(right):
                out.add(tuple(sorted([x + 1 for x in a] + [x + 1 for x in b])))
    return frozenset(out)


def cheapest_values(count: int) -> list[int]:
    return sorted(range(256), key=lambda v: (cell_cost(v), abs(signed_cell_value(v)), signed_cell_value(v)))[:count]


def expected_rate(depths: Iterable[int], values: Iterable[int]) -> float:
    ds = sorted(depths)
    vs = sorted(values, key=lambda v: cell_cost(v))
    if len(ds) != len(vs):
        raise ValueError("depth/value count mismatch")
    numerator = sum((2.0 ** -d) * d for d in ds)
    denominator = sum((2.0 ** -d) * cell_cost(v) for d, v in zip(ds, vs))
    return numerator / denominator


def optimal_depths(leaves: int) -> tuple[tuple[int, ...], float]:
    values = cheapest_values(leaves)
    best_depths: tuple[int, ...] | None = None
    best_rate = -1.0
    for depths in full_tree_depth_multisets(leaves):
        rate = expected_rate(depths, values)
        if rate > best_rate:
            best_rate = rate
            best_depths = depths
    assert best_depths is not None
    return best_depths, best_rate


def canonical_codes(depths: Iterable[int]) -> list[tuple[int, int]]:
    lengths = sorted(depths)
    if not lengths:
        return []
    out: list[tuple[int, int]] = []
    code = 0
    prev = lengths[0]
    out.append((0, prev))
    for length in lengths[1:]:
        code = (code + 1) << (length - prev)
        out.append((code, length))
        prev = length
    return out


@dataclass(frozen=True)
class PrefixEntry:
    value: int
    code: int
    length: int


OPT16_DEPTHS = (1, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 7, 8, 9, 10, 10)


def prefix16_entries() -> list[PrefixEntry]:
    values = cheapest_values(16)
    codes = canonical_codes(OPT16_DEPTHS)
    return [PrefixEntry(value=v, code=code, length=length) for v, (code, length) in zip(values, codes)]


def _bit_string(blob: bytes) -> str:
    return "".join(f"{byte:08b}" for byte in blob)


def encode_bits_to_cells(bits: str) -> tuple[list[int], int]:
    entries = prefix16_entries()
    by_word = {(f"{e.code:0{e.length}b}"): e.value for e in entries}
    prefixes = {word[:i] for word in by_word for i in range(1, len(word) + 1)}

    cells: list[int] = []
    cur = ""
    i = 0
    padding = 0
    while i < len(bits) or cur:
        if i < len(bits):
            cur += bits[i]
            i += 1
        else:
            cur += "0"
            padding += 1
        value = by_word.get(cur)
        if value is not None:
            cells.append(value)
            cur = ""
        elif cur not in prefixes:
            raise AssertionError(f"prefix table lost synchronization at {cur!r}")
    return cells, padding


def decode_cells_to_bits(cells: Iterable[int]) -> str:
    table = {e.value: f"{e.code:0{e.length}b}" for e in prefix16_entries()}
    return "".join(table[v & 255] for v in cells)


def loader_source_for_bytes(blob: bytes) -> tuple[str, int]:
    cells, padding = encode_bits_to_cells(_bit_string(blob))
    return "".join(direct_initializer_fragment(v) for v in cells), padding


def loader_chars_for_bytes(blob: bytes) -> tuple[int, float, int]:
    source, padding = loader_source_for_bytes(blob)
    return len(source), len(source) - len(blob) * 8 / channel_capacity(), padding


def summarize() -> dict[str, object]:
    cap = channel_capacity()
    best_depths, best_rate = optimal_depths(16)
    entries = prefix16_entries()
    return {
        "full_256_symbol_capacity_bits_per_bf_char": cap,
        "optimal_16_symbol_rate_bits_per_bf_char": best_rate,
        "optimal_16_symbol_rate_fraction_of_capacity": best_rate / cap,
        "optimal_16_depths": list(best_depths),
        "prefix16": [
            {
                "signed_cell_value": signed_cell_value(e.value),
                "cell_value": e.value,
                "source_cost": cell_cost(e.value),
                "code": f"{e.code:0{e.length}b}",
                "bits": e.length,
            }
            for e in entries
        ],
    }


if __name__ == "__main__":
    import json
    print(json.dumps(summarize(), indent=2, sort_keys=True))
