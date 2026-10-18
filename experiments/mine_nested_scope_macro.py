from __future__ import annotations

"""Costed, proof-gated nonadjacent macro mining INSIDE BF lexical loops.

Every loop-body invocation begins with arbitrary tape contents. Therefore
the inner miner starts with default UNKNOWN cells; it accepts scratch
only if its own body-prefix proves explicit zero facts, or recovers
relative zero after a terminating moving-loop barrier.

This pass scans lexical loop-body ranges (including nested loops) and
tries a bounded number of substantial scopes. Each accepted source
replacement changes only the selected body, preserving its pointer,
I/O, memory and divergence on every execution. Thus replacing the body
inside the containing BF loop also preserves complete program behavior.
It is an exact-source-cost candidate selector, not an optimal grammar
finder.

Large/global macro dictionaries across unrelated lexical scopes still
require shared runtime dispatch / a semantic interpreter, outside this
restricted direct BF pass.
"""

from dataclasses import dataclass

from mine_epoch_nonadjacent_macro import mine_epoch_macros


@dataclass(frozen=True)
class NestedMiningResult:
    source: str
    original_chars: int
    result_chars: int
    saved_chars: int
    selected: bool
    lexical_loops: int
    considered_scopes: int
    chosen_depth: int
    chosen_body_chars: int


def loop_body_ranges(code: str):
    stack: list[tuple[int,int]] = []
    scopes: list[tuple[int,int,int]] = []
    for i,ch in enumerate(code):
        if ch=="[":
            stack.append((i,len(stack)+1))
        elif ch=="]":
            if not stack: raise ValueError("unmatched closing bracket")
            start,depth=stack.pop()
            scopes.append((start+1,i,depth))
        elif ch not in "><+-.,[]":
            raise ValueError("input must be pure BF")
    if stack: raise ValueError("unmatched opening bracket")
    return scopes


def mine_nested_once(
    code: str, *,
    max_scopes: int = 72,
    min_body_chars: int = 150,
    max_body_chars: int = 35_000,
    max_atoms_per_epoch: int = 2_500,
    max_period: int = 128,
):
    scopes=loop_body_ranges(code)
    supported=[
        (start,end,depth)
        for start,end,depth in scopes
        if min_body_chars <= end-start <= max_body_chars
    ]
    # The largest supported bodies expose the most macro repetition by
    # source mass, but this sampling heuristic is not a completeness claim.
    supported.sort(key=lambda t:t[1]-t[0],reverse=True)
    best=code
    best_depth=-1
    chosen_len=0
    considered=0
    for start,end,depth in supported[:max_scopes]:
        body=code[start:end]
        candidate=mine_epoch_macros(
            body,
            max_atoms_per_epoch=max_atoms_per_epoch,
            max_period=max_period,
            max_groups_per_epoch=8,
            max_calls=5,
            min_macro_chars=48,
            initial_zero_tape=False,
        )
        considered+=1
        if not candidate.selected:
            continue
        after=code[:start]+candidate.source+code[end:]
        if len(after)<len(best):
            best=after
            best_depth=depth
            chosen_len=len(body)
    return NestedMiningResult(
        source=best, original_chars=len(code), result_chars=len(best),
        saved_chars=len(code)-len(best), selected=len(best)<len(code),
        lexical_loops=len(scopes), considered_scopes=considered,
        chosen_depth=best_depth, chosen_body_chars=chosen_len,
    )
