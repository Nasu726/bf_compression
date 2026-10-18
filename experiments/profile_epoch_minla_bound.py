from __future__ import annotations

"""Bound the best possible pointer routing under free per-epoch relayout.

For a relative-coordinate epoch, every maximal textual pointer run is an edge
between two logical cells.  If logical cell v is assigned physical position
p(v), the regenerated run costs |p(u)-p(v)| BF bytes.  Parallel runs become
edge weights.  Therefore free cell relayout is exactly weighted Minimum Linear
Arrangement (MinLA):

    minimize sum_{uv} w_uv |p(u)-p(v)|.

This profiler computes:

* the existing routing cost;
* the impossible all-edges-adjacent lower bound sum w;
* a stronger rigorous star lower bound;
* the exact MinLA optimum with O(n 2^n) subset DP for small epochs.

Epochs separated by moving/dynamic loop barriers are allowed independent
coordinate systems here.  That is a RELAXATION of real BF layout constraints,
especially for periodic/dynamic structures.  Consequently the aggregate result
is a lower bound / headroom oracle, not an immediately semantics-preserving
post-pass transformation.
"""

import argparse
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from region_zero_opt import Loop, body_static_delta, canonicalize, parse, precanonicalize, strip_bf, stringify

EXACT_MAX_VERTICES = 17


@dataclass
class EpochGraph:
    context: str
    vertices: set[int]
    edges: Counter[tuple[int, int]]
    current_cost: int


def loop_kind(body: tuple[object, ...]) -> str:
    delta = body_static_delta(body)
    if delta is None:
        return "dynamic"
    if delta == 0:
        return "balanced"
    return "moving"


def child_context(parent: str, kind: str) -> str:
    if parent == "dynamic" or kind == "dynamic":
        return "dynamic"
    if parent == "periodic" or kind == "moving":
        return "periodic"
    return "static"


def build_epoch_graph(nodes: tuple[object, ...], context: str) -> EpochGraph:
    vertices: set[int] = {0}
    edges: Counter[tuple[int, int]] = Counter()
    current_cost = 0

    def add_edge(a: int, b: int) -> None:
        nonlocal current_cost
        if a == b:
            return
        key = (a, b) if a < b else (b, a)
        edges[key] += 1
        current_cost += abs(a - b)
        vertices.add(a)
        vertices.add(b)

    def walk(seq: tuple[object, ...], start: int) -> int:
        logical = start
        emitted = start

        def flush() -> None:
            nonlocal emitted
            if logical != emitted:
                add_edge(emitted, logical)
                emitted = logical

        for node in seq:
            if node == ">":
                logical += 1
                continue
            if node == "<":
                logical -= 1
                continue
            flush()
            vertices.add(logical)
            if isinstance(node, Loop):
                body = canonicalize(node.body)
                if body_static_delta(body) != 0:
                    raise AssertionError("barrier loop leaked into an epoch")
                end = walk(body, logical)
                if end != logical:
                    raise AssertionError((logical, end))
        flush()
        return logical

    walk(nodes, 0)
    return EpochGraph(context=context, vertices=vertices, edges=edges, current_cost=current_cost)


def extract_epochs(nodes: tuple[object, ...], context: str = "static") -> list[EpochGraph]:
    out: list[EpochGraph] = []
    current: list[object] = []

    def flush() -> None:
        nonlocal current
        if current:
            graph = build_epoch_graph(tuple(current), context)
            if graph.edges:
                out.append(graph)
            current = []

    for node in nodes:
        if isinstance(node, Loop):
            body = canonicalize(node.body)
            kind = loop_kind(body)
            if kind != "balanced":
                flush()
                out.extend(extract_epochs(body, child_context(context, kind)))
                continue
        current.append(node)
    flush()
    return out


def star_lower_bound(graph: EpochGraph) -> int:
    """Rigorous MinLA lower bound from independent incident-edge packing.

    Around any vertex, at most two distinct neighbours can be at each distance
    1, 2, ... .  To minimize its incident contribution independently, place the
    largest edge weights in those closest slots.  Summing vertex contributions
    counts every layout edge twice, hence ceil(sum local / 2) is a lower bound.
    """
    incident: dict[int, list[int]] = {v: [] for v in graph.vertices}
    for (a, b), w in graph.edges.items():
        incident[a].append(w)
        incident[b].append(w)
    twice_lb = 0
    for weights in incident.values():
        weights.sort(reverse=True)
        for i, w in enumerate(weights):
            distance = i // 2 + 1
            twice_lb += w * distance
    return (twice_lb + 1) // 2


def exact_minla(graph: EpochGraph) -> int | None:
    verts = sorted(graph.vertices)
    n = len(verts)
    if n > EXACT_MAX_VERTICES:
        return None
    if n <= 1:
        return 0
    index = {v: i for i, v in enumerate(verts)}
    adj = [[0] * n for _ in range(n)]
    degree = [0] * n
    for (a, b), w in graph.edges.items():
        i, j = index[a], index[b]
        adj[i][j] += w
        adj[j][i] += w
        degree[i] += w
        degree[j] += w

    full = 1 << n
    cut = [0] * full
    # cut[S] = total edge weight with exactly one endpoint in S.
    for mask in range(1, full):
        bit = mask & -mask
        v = bit.bit_length() - 1
        prev = mask ^ bit
        to_prev = 0
        x = prev
        while x:
            b = x & -x
            u = b.bit_length() - 1
            to_prev += adj[v][u]
            x ^= b
        cut[mask] = cut[prev] + degree[v] - 2 * to_prev

    inf = 10**30
    dp = [inf] * full
    dp[0] = 0
    # Adding v last to prefix S contributes the previous prefix cut.  For the
    # full set this sums cuts of permutation prefixes S_1 ... S_{n-1}, which is
    # exactly sum_e w_e * edge_distance.
    for mask in range(1, full):
        x = mask
        best = inf
        while x:
            bit = x & -x
            prev = mask ^ bit
            cand = dp[prev] + cut[prev]
            if cand < best:
                best = cand
            x ^= bit
        dp[mask] = best
    return dp[-1]


def profile_text(text: str) -> dict[str, Any]:
    raw = strip_bf(text)
    nodes = canonicalize(parse(precanonicalize(raw)))
    canonical = stringify(nodes)
    epochs = extract_epochs(nodes)

    rows = []
    current = 0
    adjacency_lb = 0
    rigorous_lb = 0
    exact_epochs = 0
    for graph in epochs:
        current += graph.current_cost
        edge_mass = sum(graph.edges.values())
        adjacency_lb += edge_mass
        star = star_lower_bound(graph)
        exact = exact_minla(graph)
        bound = exact if exact is not None else star
        rigorous_lb += bound
        if exact is not None:
            exact_epochs += 1
        rows.append({
            "context": graph.context,
            "vertices": len(graph.vertices),
            "edge_pairs": len(graph.edges),
            "movement_runs": edge_mass,
            "current_movement_bytes": graph.current_cost,
            "all_adjacent_lower_bound": edge_mass,
            "star_lower_bound": star,
            "exact_minla": exact,
            "used_lower_bound": bound,
        })

    total_movement = canonical.count(">") + canonical.count("<")
    # Every movement run belongs to one extracted epoch; its literal length is
    # the current graph-layout cost.
    if current != total_movement:
        raise AssertionError((current, total_movement))

    nonmovement = len(canonical) - total_movement
    by_context: dict[str, dict[str, int]] = {}
    for context in ("static", "periodic", "dynamic"):
        subset = [r for r in rows if r["context"] == context]
        by_context[context] = {
            "epochs": len(subset),
            "current_movement_bytes": sum(r["current_movement_bytes"] for r in subset),
            "movement_runs": sum(r["movement_runs"] for r in subset),
            "rigorous_relaxed_lower_bound": sum(r["used_lower_bound"] for r in subset),
        }

    return {
        "bf_bytes": len(raw),
        "canonical_bytes": len(canonical),
        "nonmovement_bytes": nonmovement,
        "movement_bytes": total_movement,
        "epochs": len(rows),
        "exact_epochs": exact_epochs,
        "all_adjacent_movement_lower_bound": adjacency_lb,
        "rigorous_relaxed_movement_lower_bound": rigorous_lb,
        "all_adjacent_result_lower_bound": nonmovement + adjacency_lb,
        "rigorous_relaxed_result_lower_bound": nonmovement + rigorous_lb,
        "contexts": by_context,
        "largest_epochs": sorted(rows, key=lambda r: (r["vertices"], r["current_movement_bytes"]), reverse=True)[:20],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rows = []
    for name in args.files:
        path = Path(name)
        rows.append({"name": str(path), **profile_text(path.read_text(encoding="ascii", errors="ignore"))})
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        for row in rows:
            print(
                f"{row['name']}: move={row['movement_bytes']:,} "
                f"adj={row['all_adjacent_movement_lower_bound']:,} "
                f"minla_lb={row['rigorous_relaxed_movement_lower_bound']:,} "
                f"result_lb={row['rigorous_relaxed_result_lower_bound']:,}"
            )


if __name__ == "__main__":
    main()
