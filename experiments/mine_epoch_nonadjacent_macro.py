from __future__ import annotations

"""Find executable nonadjacent macro sharing across relative-base epochs.

Unlike the original global-scratch miner, this pass permits moving or
dynamically balanced-unknown loops elsewhere in the program. Each
top-level moving/dynamic loop creates an epoch boundary: the pointer
becomes a fresh relative origin, and later positions cannot be compared
with earlier ones as absolute addresses.

Within each epoch, search bounded, pointer-balanced macro subsequences
at equal *relative* pointer positions. The local zero-scratch proof
checks the complete prefix up to the candidate, including any prior
moving-loop barriers. A call is accepted only if that proof succeeds
and the resulting *whole* standard-BF program is strictly shorter.

This initial implementation scans only the root lexical scope and takes
the best single candidate per invocation. It deliberately does not
assume entry-tape zeros for nested lexical loop bodies. Extension to
nested scopes requires a separate unknown-initial-state abstract
interpretation and careful relative-frame rebasing.
"""

from collections import defaultdict
from dataclasses import dataclass

from mine_nonadjacent_macro import candidate_periods
from nonadjacent_epoch_macro import construct_epoch_phase_reuse
from region_zero_opt import body_static_delta, parse


@dataclass(frozen=True)
class EpochMiningResult:
    source: str
    initial_chars: int
    result_chars: int
    selected: bool
    saved_chars: int
    macro_chars: int
    call_count: int
    epoch_count: int
    considered_groups: int


def lexical_epochs(source: str):
    """Return top-level epoch atom lists, offsets and relative positions."""
    stack: list[int] = []
    partners = {}
    for i, c in enumerate(source):
        if c == "[":
            stack.append(i)
        elif c == "]":
            if not stack:
                raise ValueError("unmatched ]")
            partners[stack.pop()] = i
        elif c not in "><+-.,[]":
            raise ValueError("non-BF source")
    if stack:
        raise ValueError("unmatched [")

    scopes = []
    atoms: list[str] = []
    offsets: list[int] = []
    pointers: list[int] = []
    ptr = 0
    i = 0
    while i < len(source):
        c = source[i]
        if c == "[":
            end = partners[i] + 1
            atom = source[i:end]
            delta = body_static_delta(parse(atom[1:-1]))
            if delta is None or delta != 0:
                if atoms:
                    scopes.append((atoms, offsets, pointers))
                atoms, offsets, pointers = [], [], []
                ptr = 0
                i = end
                continue
        else:
            atom = c
            end = i+1

        atoms.append(atom)
        offsets.append(i)
        pointers.append(ptr)
        if c == ">":
            ptr += 1
        elif c == "<":
            ptr -= 1
        i = end
    if atoms:
        scopes.append((atoms, offsets, pointers))
    return scopes


def mine_epoch_macros(
    source: str, *,
    max_atoms_per_epoch: int = 4_000,
    max_period: int = 256,
    max_groups_per_epoch: int = 24,
    max_calls: int = 6,
    min_macro_chars: int = 48,
):
    scopes = lexical_epochs(source)
    best = source
    best_macro_chars = 0
    best_calls = 0
    inspected = 0

    for atoms, offsets, positions in scopes:
        n=len(atoms)
        if n > max_atoms_per_epoch or n < 2:
            continue
        lengths=[0]
        for atom in atoms:
            lengths.append(lengths[-1]+len(atom))
        mask=(1<<64)-1
        base=11400714819323198485
        prefix=[0]
        power=[1]
        for atom in atoms:
            value=(hash(atom) & mask)+1
            prefix.append((prefix[-1]*base+value)&mask)
            power.append((power[-1]*base)&mask)

        groups=defaultdict(list)
        for p in candidate_periods(max_period):
            for i in range(n-p+1):
                if positions[i+p-1] != positions[i] and p == 1:
                    continue
                # A block must itself preserve the anchor pointer.
                after = positions[i+p] if i+p < n else (
                    positions[i+p-1]
                    + (1 if atoms[i+p-1]==">" else -1 if atoms[i+p-1]=="<" else 0)
                )
                if after != positions[i]:
                    continue
                if lengths[i+p]-lengths[i] < min_macro_chars:
                    continue
                h=(prefix[i+p]-prefix[i]*power[p])&mask
                groups[(positions[i],p,h)].append(i)

        ranked=[]
        for key, starts in groups.items():
            if len(starts)<2: continue
            p=key[1]
            chosen=[]
            end=-1
            for i in starts:
                if i>=end and atoms[i:i+p]==atoms[starts[0]:starts[0]+p]:
                    chosen.append(i)
                    end=i+p
            if len(chosen)<2:continue
            optimistic=(min(max_calls,len(chosen))-1)*(lengths[chosen[0]+p]-lengths[chosen[0]])
            ranked.append((optimistic,key,chosen))
        ranked.sort(reverse=True)
        for _, key, starts in ranked[:max_groups_per_epoch]:
            inspected+=1
            p=key[1]
            sample=sorted(set(
                list(range(min(6,len(starts)-1)))
                + [max(0,len(starts)//2), max(0,len(starts)-max_calls)]
            ))
            for i in sample:
                for count in range(2,min(max_calls,len(starts)-i)+1):
                    call_positions=starts[i:i+count]
                    at=call_positions[0]
                    macro=source[offsets[at]:offsets[at]+(lengths[at+p]-lengths[at])]
                    gaps=tuple(
                        source[offsets[call_positions[j]+p-1]+len(atoms[call_positions[j]+p-1]):
                               offsets[call_positions[j+1]]]
                        for j in range(count-1)
                    )
                    if not any(gaps):
                        continue
                    prefix_source=source[:offsets[at]]
                    last=call_positions[-1]+p-1
                    suffix=source[offsets[last]+len(atoms[last]):]
                    result=construct_epoch_phase_reuse(prefix_source,macro,gaps,suffix)
                    if len(result.source)<len(best):
                        best=result.source
                        best_macro_chars=len(macro)
                        best_calls=count

    return EpochMiningResult(
        source=best, initial_chars=len(source), result_chars=len(best),
        selected=len(best)<len(source),
        saved_chars=len(source)-len(best),
        macro_chars=best_macro_chars, call_count=best_calls,
        epoch_count=len(scopes), considered_groups=inspected,
    )
