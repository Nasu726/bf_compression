from __future__ import annotations

"""Profile macro-scale compression opportunity in compiler-generated BF.

This experiment asks whether exact or semantically normalized tandem repetition
is abundant enough to justify executable rerolling as a route toward roughly
10x source-size reduction.

The reroll result is deliberately optimistic: scratch-counter placement,
counter synthesis/update, and wrapper routing are treated as free.  It is
therefore a structural triage bound, not an immediately valid rewrite.

Nested opportunities are composed without double counting.  A loop body is
profiled recursively first; only its remaining ideal cost is exposed as one
atom to the enclosing static region.  If the enclosing region then rerolls
several copies, it removes the already-compressed cost of the discarded copies.
Thus no original byte is credited twice.

For a fixed period budget the tandem scan is O(n * P), where n is normalized
atom count and P is the number of tested atom periods.  It does not enumerate
arbitrary substring pairs.
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
    effective_bytes: int
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


def _new_stats() -> dict[str, Any]:
    return {
        "regions": 0,
        "atoms": 0,
        "candidate_starts": 0,
        "greedy_repeat_effective_bytes": 0,
        "outer_reroll_saved_bytes": 0,
        "max_repeat_count": 1,
        "max_period_atoms": 0,
        "max_single_candidate_saved_bytes": 0,
    }


def _merge_stats(dst: dict[str, Any], src: dict[str, Any]) -> None:
    for key in (
        "regions",
        "atoms",
        "candidate_starts",
        "greedy_repeat_effective_bytes",
        "outer_reroll_saved_bytes",
    ):
        dst[key] += src[key]
    for key in (
        "max_repeat_count",
        "max_period_atoms",
        "max_single_candidate_saved_bytes",
    ):
        dst[key] = max(dst[key], src[key])


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


def _profile_region(atoms: list[Atom]) -> tuple[int, dict[str, Any]]:
    stats = _new_stats()
    stats["regions"] = 1
    stats["atoms"] = len(atoms)
    total = sum(a.effective_bytes for a in atoms)
    n = len(atoms)
    if n < 2:
        return total, stats

    ids = _intern_ids(atoms)
    byte_prefix = [0] * (n + 1)
    ptr_prefix = [0] * (n + 1)
    for i, atom in enumerate(atoms):
        byte_prefix[i + 1] = byte_prefix[i] + atom.effective_bytes
        ptr_prefix[i + 1] = ptr_prefix[i] + atom.pointer_delta

    best_saved = [0] * n
    best_end = [0] * n
    best_k = [1] * n
    best_p = [0] * n
    max_p = min(n // 2, PERIODS[-1])

    for p in PERIODS:
        if p > max_p:
            break
        # Reset per period so the reverse LCP boundary cannot inherit a stale
        # value from the previous offset.
        lcp = [0] * (n + 1)
        for i in range(n - p - 1, -1, -1):
            if ids[i] == ids[i + p]:
                lcp[i] = lcp[i + 1] + 1
            else:
                lcp[i] = 0
            if lcp[i] < p:
                continue
            if ptr_prefix[i + p] != ptr_prefix[i]:
                continue
            k = 1 + lcp[i] // p
            end = i + k * p
            if end > n:
                k = (n - i) // p
                end = i + k * p
            if k < 2:
                continue
            saved = byte_prefix[end] - byte_prefix[i + p]
            if saved > best_saved[i]:
                best_saved[i] = saved
                best_end[i] = end
                best_k[i] = k
                best_p[i] = p

    stats["candidate_starts"] = sum(1 for x in best_saved if x > 0)
    i = 0
    while i < n:
        if best_saved[i] <= 0:
            i += 1
            continue
        end = best_end[i]
        saved = best_saved[i]
        stats["outer_reroll_saved_bytes"] += saved
        stats["greedy_repeat_effective_bytes"] += byte_prefix[end] - byte_prefix[i]
        stats["max_repeat_count"] = max(stats["max_repeat_count"], best_k[i])
        stats["max_period_atoms"] = max(stats["max_period_atoms"], best_p[i])
        stats["max_single_candidate_saved_bytes"] = max(
            stats["max_single_candidate_saved_bytes"], saved
        )
        i = end

    return total - stats["outer_reroll_saved_bytes"], stats


def _append_run(
    atoms: list[Atom],
    kind: str | None,
    amount: int,
    source_bytes: int,
) -> None:
    if kind is None:
        return
    if kind == "MOVE":
        if amount:
            atoms.append(Atom(("MOVE", amount), source_bytes, amount))
        return
    if kind == "ADD":
        z = amount & 255
        if z:
            signed = z if z <= 128 else z - 256
            atoms.append(Atom(("ADD", signed), source_bytes, 0))
        return
    raise AssertionError(kind)


def _profile_sequence(
    nodes: tuple[object, ...],
    *,
    semantic: bool,
) -> tuple[int, dict[str, Any]]:
    total_cost = 0
    stats = _new_stats()
    atoms: list[Atom] = []
    run_kind: str | None = None
    run_amount = 0
    run_bytes = 0

    def flush_run() -> None:
        nonlocal run_kind, run_amount, run_bytes
        _append_run(atoms, run_kind, run_amount, run_bytes)
        run_kind = None
        run_amount = 0
        run_bytes = 0

    def finish_region() -> None:
        nonlocal total_cost
        flush_run()
        if not atoms:
            return
        remaining, region_stats = _profile_region(atoms)
        total_cost += remaining
        _merge_stats(stats, region_stats)
        atoms.clear()

    for node in nodes:
        if node in (">", "<"):
            if run_kind != "MOVE":
                flush_run()
                run_kind = "MOVE"
            run_amount += 1 if node == ">" else -1
            run_bytes += 1
            continue
        if node in ("+", "-"):
            if run_kind != "ADD":
                flush_run()
                run_kind = "ADD"
            run_amount += 1 if node == "+" else -1
            run_bytes += 1
            continue

        flush_run()
        if node in (".", ","):
            atoms.append(Atom(("IO", node), 1, 0))
            continue
        if not isinstance(node, Loop):
            raise AssertionError(node)

        body = canonicalize(node.body)
        child_cost, child_stats = _profile_sequence(body, semantic=semantic)
        _merge_stats(stats, child_stats)
        delta = body_static_delta(body)
        if delta == 0:
            atoms.append(
                Atom(
                    _loop_key(body, semantic=semantic),
                    2 + child_cost,
                    0,
                )
            )
        else:
            finish_region()
            total_cost += 2 + child_cost

    finish_region()
    return total_cost, stats


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
    return {str(t): sum(x for x in lengths if x >= t) for t in (4, 8, 16, 32, 64, 128)}


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
    canonical_bytes = len(canonical_source)

    counts = Counter(raw)
    move_runs = _run_lengths(raw, {">", "<"})
    add_runs = _run_lengths(raw, {"+", "-"})

    result: dict[str, Any] = {
        "bf_bytes": len(raw),
        "precanonical_bytes": len(canon),
        "canonical_ast_bytes": canonical_bytes,
        "canonicalization_saved_bytes": len(raw) - canonical_bytes,
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
        optimistic_cost, stats = _profile_sequence(nodes, semantic=semantic)
        if optimistic_cost > canonical_bytes:
            raise AssertionError((mode, optimistic_cost, canonical_bytes))
        reroll_saved = canonical_bytes - optimistic_cost
        result[f"{mode}_reroll"] = {
            **stats,
            "reroll_incremental_saved_bytes": reroll_saved,
            "reroll_incremental_saved_fraction_of_program": (
                reroll_saved / len(raw) if raw else 0.0
            ),
            "optimistic_result_bytes_if_free_reroll": optimistic_cost,
            "total_saved_including_canonicalization": len(raw) - optimistic_cost,
        }

    return result


def profile(path: Path) -> dict[str, Any]:
    return {
        "name": str(path),
        **profile_code(path.read_text(encoding="ascii", errors="ignore")),
    }


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
                f"literal_ideal={lit['reroll_incremental_saved_bytes']:,} "
                f"semantic_ideal={sem['reroll_incremental_saved_bytes']:,} "
                f"semantic_result={sem['optimistic_result_bytes_if_free_reroll']:,}"
            )


if __name__ == "__main__":
    main()
