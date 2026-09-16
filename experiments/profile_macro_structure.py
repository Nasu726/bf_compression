from __future__ import annotations

"""Profile macro-scale compression opportunity in compiler-generated BF.

This experiment is intentionally optimistic.  It asks whether exact or
semantically normalized *tandem repetition* is abundant enough to justify an
executable-rerolling research track capable of order-of-magnitude source-size
reduction.

Important: the reported reroll savings are NOT immediately valid rewrites.
They ignore scratch-counter placement, counter setup/update cost, and wrapper
routing.  They therefore act as a structural upper bound / triage signal:
if even this optimistic bound is small, executable rerolling alone cannot
explain a 10x target.

The scanner is near-linear for a fixed period budget: O(n * P), where n is the
number of normalized atoms and P is the number of tested atom periods.  It does
not enumerate arbitrary substring pairs.
"""

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any, Hashable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_dead_affine_targets import flat_balanced_coeff
from region_zero_opt import (
    Loop,
    body_static_delta,
    canonicalize,
    parse,
    precanonicalize,
    stringify,
    strip_bf,
)


PERIODS = tuple(range(1, 129)) + (192, 256, 384, 512)


@dataclass(frozen=True)
class Atom:
    key: Hashable
    source_bytes: int
    pointer_delta: int


def _odd_affine_semantic_key(body: tuple[object, ...]) -> Hashable | None:
    coeff = flat_balanced_coeff(body)
    if coeff is None:
        return None
    control = coeff.get(0, 0)
    if control % 2 == 0:
        return None
    inv = pow(control, -1, 256)
    transfer = tuple(
        sorted(
            (off, (-value * inv) & 255)
            for off, value in coeff.items()
            if off != 0 and value
        )
    )
    return ("AFFINE_ODD", transfer)


def _loop_key(body: tuple[object, ...], *, semantic: bool) -> Hashable:
    body = canonicalize(body)
    if semantic:
        affine = _odd_affine_semantic_key(body)
        if affine is not None:
            return affine
    return ("LOOP_LITERAL", stringify(body))


def _flush_run(
    atoms: list[Atom],
    kind: str | None,
    amount: int,
    source_bytes: int,
) -> tuple[str | None, int, int]:
    if kind is None:
        return None, 0, 0
    if kind == "MOVE":
        if amount:
            atoms.append(Atom(("MOVE", amount), source_bytes, amount))
    elif kind == "ADD":
        z = amount & 255
        if z:
            signed = z if z <= 128 else z - 256
            atoms.append(Atom(("ADD", signed), source_bytes, 0))
    else:
        raise AssertionError(kind)
    return None, 0, 0


def atomize_sequence(
    nodes: tuple[object, ...],
    *,
    semantic: bool,
    regions: list[list[Atom]],
) -> None:
    """Split one lexical scope at moving/dynamic loops and atomize static regions."""
    atoms: list[Atom] = []
    run_kind: str | None = None
    run_amount = 0
    run_bytes = 0

    def flush() -> None:
        nonlocal run_kind, run_amount, run_bytes
        run_kind, run_amount, run_bytes = _flush_run(
            atoms, run_kind, run_amount, run_bytes
        )

    def finish_region() -> None:
        flush()
        if atoms:
            regions.append(list(atoms))
            atoms.clear()

    for node in nodes:
        if node in (">", "<"):
            if run_kind != "MOVE":
                flush()
                run_kind = "MOVE"
            run_amount += 1 if node == ">" else -1
            run_bytes += 1
            continue
        if node in ("+", "-"):
            if run_kind != "ADD":
                flush()
                run_kind = "ADD"
            run_amount += 1 if node == "+" else -1
            run_bytes += 1
            continue

        flush()
        if node in (".", ","):
            atoms.append(Atom(("IO", node), 1, 0))
            continue
        if not isinstance(node, Loop):
            raise AssertionError(node)

        body = canonicalize(node.body)
        delta = body_static_delta(body)
        if delta == 0:
            atoms.append(
                Atom(
                    _loop_key(body, semantic=semantic),
                    2 + len(stringify(body)),
                    0,
                )
            )
        else:
            # Absolute identity is no longer static across this loop.  Keep it
            # out of a reroll candidate but recurse into its lexical body.
            finish_region()
            atomize_sequence(body, semantic=semantic, regions=regions)

    finish_region()

    # Balanced loop bodies are analyzable lexical scopes in their own right.
    for node in nodes:
        if isinstance(node, Loop):
            body = canonicalize(node.body)
            if body_static_delta(body) == 0:
                atomize_sequence(body, semantic=semantic, regions=regions)


def _intern_ids(atoms: list[Atom]) -> list[int]:
    table: dict[Hashable, int] = {}
    ids: list[int] = []
    for atom in atoms:
        ident = table.get(atom.key)
        if ident is None:
            ident = len(table) + 1
            table[atom.key] = ident
        ids.append(ident)
    return ids


def profile_region(atoms: list[Atom]) -> dict[str, Any]:
    n = len(atoms)
    if n < 2:
        return {
            "atoms": n,
            "source_bytes": sum(a.source_bytes for a in atoms),
            "candidate_starts": 0,
            "greedy_repeat_bytes": 0,
            "greedy_ideal_saved_bytes": 0,
            "max_repeat_count": 1,
            "max_period_atoms": 0,
            "max_single_candidate_saved_bytes": 0,
        }

    ids = _intern_ids(atoms)
    byte_prefix = [0] * (n + 1)
    ptr_prefix = [0] * (n + 1)
    for i, atom in enumerate(atoms):
        byte_prefix[i + 1] = byte_prefix[i] + atom.source_bytes
        ptr_prefix[i + 1] = ptr_prefix[i] + atom.pointer_delta

    best_saved = [0] * n
    best_end = [0] * n
    best_k = [1] * n
    best_p = [0] * n
    max_p = min(n // 2, PERIODS[-1])

    # lcp[i] = number of equal atoms from i and i+p onward.  For fixed p this
    # is computed by one reverse scan, making the whole search O(n * |PERIODS|).
    lcp = [0] * (n + 1)
    for p in PERIODS:
        if p > max_p:
            break
        # Only indices with i+p < n are meaningful.
        for i in range(n - p - 1, -1, -1):
            if ids[i] == ids[i + p]:
                lcp[i] = lcp[i + 1] + 1
            else:
                lcp[i] = 0
            if lcp[i] < p:
                continue
            # A rerolled body must return to its entry pointer.  Nested loops in
            # a region are themselves recursively balanced by construction.
            if ptr_prefix[i + p] != ptr_prefix[i]:
                continue
            k = 1 + lcp[i] // p
            end = i + k * p
            if end > n:
                k = (n - i) // p
                end = i + k * p
            if k < 2:
                continue
            # Optimistic: keep the first body copy and remove all later copies.
            # Counter/scratch/wrapper cost is deliberately ignored.
            saved = byte_prefix[end] - byte_prefix[i + p]
            if saved > best_saved[i]:
                best_saved[i] = saved
                best_end[i] = end
                best_k[i] = k
                best_p[i] = p

    candidate_starts = sum(1 for x in best_saved if x > 0)
    greedy_saved = 0
    greedy_repeat_bytes = 0
    max_k = 1
    max_period = 0
    max_single = 0
    i = 0
    while i < n:
        if best_saved[i] <= 0:
            i += 1
            continue
        end = best_end[i]
        greedy_saved += best_saved[i]
        greedy_repeat_bytes += byte_prefix[end] - byte_prefix[i]
        max_k = max(max_k, best_k[i])
        max_period = max(max_period, best_p[i])
        max_single = max(max_single, best_saved[i])
        i = end

    return {
        "atoms": n,
        "source_bytes": byte_prefix[n],
        "candidate_starts": candidate_starts,
        "greedy_repeat_bytes": greedy_repeat_bytes,
        "greedy_ideal_saved_bytes": greedy_saved,
        "max_repeat_count": max_k,
        "max_period_atoms": max_period,
        "max_single_candidate_saved_bytes": max_single,
    }


def _run_lengths(code: str, chars: set[str]) -> list[int]:
    out: list[int] = []
    run = 0
    for ch in code:
        if ch in chars:
            run += 1
        else:
            if run:
                out.append(run)
                run = 0
    if run:
        out.append(run)
    return out


def _threshold_bytes(lengths: list[int]) -> dict[str, int]:
    return {
        str(t): sum(x for x in lengths if x >= t)
        for t in (4, 8, 16, 32, 64, 128)
    }


def _duplicate_loop_profile(nodes: tuple[object, ...], *, semantic: bool) -> dict[str, Any]:
    groups: dict[Hashable, list[int]] = defaultdict(list)

    def rec(seq: tuple[object, ...]) -> None:
        for node in seq:
            if not isinstance(node, Loop):
                continue
            body = canonicalize(node.body)
            groups[_loop_key(body, semantic=semantic)].append(2 + len(stringify(body)))
            rec(body)

    rec(nodes)
    repeated_classes = 0
    repeated_instances = 0
    duplicate_bytes_after_first = 0
    for lengths in groups.values():
        if len(lengths) < 2:
            continue
        repeated_classes += 1
        repeated_instances += len(lengths)
        # Unrealistic dictionary/macro upper bound: keep the first instance.
        duplicate_bytes_after_first += sum(lengths[1:])
    return {
        "unique_loop_classes": len(groups),
        "repeated_loop_classes": repeated_classes,
        "instances_in_repeated_classes": repeated_instances,
        "dictionary_upper_bound_duplicate_bytes": duplicate_bytes_after_first,
    }


def profile_code(text: str) -> dict[str, Any]:
    raw = strip_bf(text)
    canon = precanonicalize(raw)
    nodes = canonicalize(parse(canon))
    canonical_source = stringify(nodes)

    counts = Counter(raw)
    move_runs = _run_lengths(raw, {">", "<"})
    add_runs = _run_lengths(raw, {"+", "-"})

    result: dict[str, Any] = {
        "bf_bytes": len(raw),
        "precanonical_bytes": len(canon),
        "canonical_ast_bytes": len(canonical_source),
        "command_counts": {ch: counts.get(ch, 0) for ch in "><+-.,[]"},
        "movement_bytes": counts.get(">", 0) + counts.get("<", 0),
        "arithmetic_bytes": counts.get("+", 0) + counts.get("-", 0),
        "control_bytes": counts.get("[", 0) + counts.get("]", 0),
        "io_bytes": counts.get(".", 0) + counts.get(",", 0),
        "movement_run_count": len(move_runs),
        "movement_run_max": max(move_runs, default=0),
        "movement_bytes_in_long_runs": _threshold_bytes(move_runs),
        "arithmetic_run_count": len(add_runs),
        "arithmetic_run_max": max(add_runs, default=0),
        "arithmetic_bytes_in_long_runs": _threshold_bytes(add_runs),
        "literal_loop_duplicates": _duplicate_loop_profile(nodes, semantic=False),
        "semantic_loop_duplicates": _duplicate_loop_profile(nodes, semantic=True),
    }

    for mode, semantic in (("literal", False), ("semantic", True)):
        regions: list[list[Atom]] = []
        atomize_sequence(nodes, semantic=semantic, regions=regions)
        rows = [profile_region(region) for region in regions]
        total_region_bytes = sum(r["source_bytes"] for r in rows)
        total_saved = sum(r["greedy_ideal_saved_bytes"] for r in rows)
        result[f"{mode}_reroll"] = {
            "regions": len(rows),
            "atoms": sum(r["atoms"] for r in rows),
            "region_source_bytes": total_region_bytes,
            "candidate_starts": sum(r["candidate_starts"] for r in rows),
            "greedy_repeat_bytes": sum(r["greedy_repeat_bytes"] for r in rows),
            "greedy_ideal_saved_bytes": total_saved,
            "greedy_ideal_saved_fraction_of_program": (
                total_saved / len(raw) if raw else 0.0
            ),
            "optimistic_result_bytes_if_free_reroll": len(raw) - total_saved,
            "max_repeat_count": max((r["max_repeat_count"] for r in rows), default=1),
            "max_period_atoms": max((r["max_period_atoms"] for r in rows), default=0),
            "max_single_candidate_saved_bytes": max(
                (r["max_single_candidate_saved_bytes"] for r in rows), default=0
            ),
        }

    return result


def profile(path: Path) -> dict[str, Any]:
    return {"name": str(path), **profile_code(path.read_text(encoding="ascii", errors="ignore"))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rows = [profile(Path(name)) for name in args.files]
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        for row in rows:
            lit = row["literal_reroll"]
            sem = row["semantic_reroll"]
            print(
                f"{row['name']}: bytes={row['bf_bytes']:,} "
                f"move={row['movement_bytes'] / row['bf_bytes']:.1%} "
                f"literal_ideal={lit['greedy_ideal_saved_bytes']:,} "
                f"semantic_ideal={sem['greedy_ideal_saved_bytes']:,} "
                f"semantic_result={sem['optimistic_result_bytes_if_free_reroll']:,}"
            )


if __name__ == "__main__":
    main()
