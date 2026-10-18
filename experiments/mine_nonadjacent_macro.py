from __future__ import annotations

"""Bounded discovery of non-adjacent executable BF macro sharing.

A lexical top-level BF loop is one indivisible atom. The input program
must admit a complete static global tape footprint (no moving loops).
For each tested atom-span period, a rolling hash identifies occurrences
of exactly the same macro body at the same pointer anchor. Candidate
collisions are checked by exact atom slices.

For each candidate group, select disjoint occurrences and try short
windows of two to six calls. The intervening gaps can differ arbitrarily.
A phase dispatcher stores the repeated body only once. The final choice
is the **shortest fully executable BF source** among the candidate
windows and the original untouched program.

The dictionary search is bounded and heuristic; its output is sound
because construct_phase_reuse performs the semantic precondition proof,
but it does not promise to find the globally shortest phase grammar.
Large compiler artifacts should use scalable suffix indexes / scope
decomposition rather than this exploratory whole-program miner.
"""

from collections import defaultdict
from dataclasses import dataclass

from global_scratch_reroll import analyze_global_static, top_level_atoms
from nonadjacent_phase_macro import construct_phase_reuse


@dataclass(frozen=True)
class MiningResult:
    source: str
    baseline_chars: int
    result_chars: int
    selected: bool
    macro_chars: int
    calls: int
    gap_chars: tuple[int, ...]
    considered_groups: int
    reason: str


def candidate_periods(max_period: int) -> tuple[int, ...]:
    return tuple(
        sorted(
            set(range(1, min(max_period, 32) + 1))
            | {p for p in (40, 48, 64, 80, 96, 128, 160, 192, 220, 256)
               if p <= max_period}
        )
    )


def mine_nonadjacent(
    source: str,
    *,
    max_atoms: int = 4_000,
    max_period: int = 256,
    max_calls: int = 6,
    max_groups: int = 96,
    min_macro_chars: int = 36,
) -> MiningResult:
    footprint = analyze_global_static(source)
    if footprint is None:
        return MiningResult(source, len(source), len(source), False, 0, 0, (), 0, "dynamic-footprint")

    atoms, positions = top_level_atoms(source, footprint)
    n = len(atoms)
    if n > max_atoms:
        return MiningResult(source, len(source), len(source), False, 0, 0, (), 0, "atom-budget")
    if n < 2:
        return MiningResult(source, len(source), len(source), False, 0, 0, (), 0, "too-short")

    byte_starts = [0]
    for atom in atoms:
        byte_starts.append(byte_starts[-1] + len(atom))
    assert byte_starts[-1] == len(source)

    mask = (1 << 64) - 1
    base = 11400714819323198485
    values = [(hash(atom) & mask) + 1 for atom in atoms]
    prefix = [0]
    powers = [1]
    for value in values:
        prefix.append((prefix[-1] * base + value) & mask)
        powers.append((powers[-1] * base) & mask)

    # In-code deterministic local hash; Python's per-process randomized
    # string hashes are not serialized and do not affect correctness.
    groups: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for p in candidate_periods(max_period):
        for i in range(n - p + 1):
            if positions[i+p] != positions[i]:
                continue
            length = byte_starts[i+p] - byte_starts[i]
            if length < min_macro_chars:
                continue
            h = (prefix[i+p] - prefix[i] * powers[p]) & mask
            groups[(positions[i], p, h)].append(i)

    ranks: list[tuple[int, tuple[int, int, int], list[int]]] = []
    for key, starts in groups.items():
        if len(starts) < 2:
            continue
        p = key[1]
        first = starts[0]
        # Overlap is conservatively removed before scoring.
        chosen = []
        end = -1
        for start in starts:
            if start >= end and atoms[start:start+p] == atoms[first:first+p]:
                chosen.append(start)
                end = start + p
        if len(chosen) < 2:
            continue
        macro_len = byte_starts[chosen[0]+p] - byte_starts[chosen[0]]
        optimistic = (min(max_calls, len(chosen)) - 1) * macro_len
        if optimistic < 36:
            continue
        ranks.append((optimistic, key, chosen))
    ranks.sort(reverse=True)

    best_source = source
    best_key = None
    considered = 0
    for _, key, starts in ranks[:max_groups]:
        considered += 1
        p = key[1]
        for i in range(len(starts) - 1):
            for k in range(2, min(max_calls, len(starts)-i)+1):
                selected = starts[i:i+k]
                macro_start = selected[0]
                macro = source[byte_starts[macro_start]:byte_starts[macro_start+p]]
                gaps = tuple(
                    source[byte_starts[selected[j]+p]:byte_starts[selected[j+1]]]
                    for j in range(k-1)
                )
                # One genuinely nonadjacent pair must occur.
                if not any(gaps):
                    continue
                prefix_text = source[:byte_starts[macro_start]]
                suffix_text = source[byte_starts[selected[-1]+p]:]
                result = construct_phase_reuse(prefix_text, macro, gaps, suffix_text)
                if len(result.source) < len(best_source):
                    best_source = result.source
                    best_key = (len(macro), k, tuple(map(len, gaps)))

    selected = best_key is not None
    return MiningResult(
        best_source, len(source), len(best_source),
        selected,
        best_key[0] if selected else 0,
        best_key[1] if selected else 0,
        best_key[2] if selected else (),
        considered,
        "ok",
    )
