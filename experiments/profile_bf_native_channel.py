from __future__ import annotations

"""BF-native static payload channel with a proved source-cost model.

A standalone Brainfuck program cannot read its own source.  Static compressed
payload therefore has to be *constructed* on the tape by executable BF before a
VM/decoder can consume it.

This module studies a deliberately simple, fully realizable channel:

* the tape starts at zero;
* one payload symbol is one fresh byte cell;
* value v is written by the shorter of v '+' commands or (256-v) '-' commands;
* '>' advances to the next fresh zero cell.

Thus a symbol v costs

    c(v) = 1 + min(v, 256-v)

BF source characters (apart from an O(1) final-cell convention).

For arbitrary incompressible payload bits, unequal-cost coding gives channel
capacity C determined by

    sum_v 2**(-C*c(v)) = 1.

We also expose a tiny 16-symbol *binary prefix code* whose decoder table is
small enough to be realistic in BF.  The tree is not heuristic: the verifier
exhaustively enumerates every full binary prefix-tree leaf-depth multiset with
16 leaves and checks that the selected tree maximizes expected payload bits per
literal BF source character for the 16 cheapest cell values.

This is still only the payload-construction layer.  A complete compressed BF
program additionally pays for its semantic VM/decoder.
"""

from dataclasses import dataclass
import math
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
    # For a complete prefix tree fed unbiased bits, a leaf at depth d occurs
    # with probability 2^-d.  Rearrangement says cheapest cell costs should be
    # assigned to the shallowest (most probable) leaves.
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
    """Return [(code, bit_length)] in nondecreasing length order."""
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


# Exhaustively optimal for exactly 16 direct-cell symbols.  Keeping this fixed
# makes the eventual BF decoder tiny and makes measurements reproducible.
OPT16_DEPTHS = (1, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 7, 8, 9, 10, 10)


def prefix16_entries() -> list[PrefixEntry]:
    values = cheapest_values(16)
    codes = canonical_codes(OPT16_DEPTHS)
    return [PrefixEntry(value=v, code=code, length=length) for v, (code, length) in zip(values, codes)]


def _bit_string(blob: bytes) -> str:
    return "".join(f"{byte:08b}" for byte in blob)


def encode_bits_to_cells(bits: str) -> tuple[list[int], int]:
    """Parse unbiased payload bits with the fixed 16-leaf prefix code.

    Returns (cell_values, padding_bits).  Zero padding is appended only to close
    the final prefix-code word.  A real stream must separately communicate the
    original bit length or have an intrinsic end marker.
    """
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


def loader_chars_for_bytes(blob: bytes) -> tuple[int, int, int]:
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
