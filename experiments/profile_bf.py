from __future__ import annotations

import argparse
import json
import math
import pickle
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path

BF = set('><+-.,[]')


def strip_bf(text: str) -> str:
    return ''.join(ch for ch in text if ch in BF)


def q(z: int) -> int:
    z %= 256
    return min(z, 256-z)


def closed_route_cost(offsets: list[int]) -> int:
    if not offsets:
        return 0
    lo = min([0, *offsets])
    hi = max([0, *offsets])
    return 2 * (hi-lo)


def egcd(a,b):
    if b == 0: return a,1,0
    g,x,y = egcd(b,a%b)
    return g,y,x-(a//b)*y


def inv_mod(a,m):
    g,x,_ = egcd(a % m,m)
    if g != 1: raise ValueError
    return x % m

@dataclass
class Loop:
    start: int
    end: int
    body: str
    depth: int
    children: list['Loop'] = field(default_factory=list)


def parse_loops(code: str) -> list[Loop]:
    stack: list[tuple[int,int,list[Loop]]] = []
    roots: list[Loop] = []
    for i,ch in enumerate(code):
        if ch == '[':
            stack.append((i, len(stack)+1, []))
        elif ch == ']':
            if not stack:
                raise ValueError(f'unmatched ] at {i}')
            s,d,kids = stack.pop()
            lp = Loop(s,i,code[s+1:i],d,kids)
            if stack:
                stack[-1][2].append(lp)
            else:
                roots.append(lp)
    if stack: raise ValueError('unmatched [')
    return roots


def flatten_loops(roots):
    out=[]
    def rec(x):
        out.append(x)
        for y in x.children: rec(y)
    for r in roots: rec(r)
    return out


def body_effect(body: str):
    if '[' in body or ']' in body or '.' in body or ',' in body:
        return None
    p=0
    coeff=Counter()
    minp=maxp=0
    for ch in body:
        if ch == '>': p += 1
        elif ch == '<': p -= 1
        elif ch == '+': coeff[p] = (coeff[p]+1) & 255
        elif ch == '-': coeff[p] = (coeff[p]-1) & 255
        minp=min(minp,p); maxp=max(maxp,p)
    coeff={k:v for k,v in coeff.items() if v}
    return p, coeff, minp, maxp


def exact_flat_best(coeff: dict[int,int]) -> tuple[int|None,int|None]:
    c=coeff.get(0,0)
    targets={i:a for i,a in coeff.items() if i != 0 and a % 256}
    if c == 0:
        return 2,0
    g=math.gcd(c,256)
    orig_gen_locked = any(a % g for a in targets.values())
    if orig_gen_locked:
        candidates=[c]
    else:
        M=256//g
        c0=(c//g)%M
        invc=inv_mod(c0,M)
        candidates=[(g*d0)%256 for d0 in range(1,M,2)]
    best=None; bestd=None
    for d in candidates:
        if orig_gen_locked:
            new=targets
        else:
            M=256//g; d0=(d//g)%M
            factor=(d0*invc)%M
            new={i:(g*((a//g)*factor % M))%256 for i,a in targets.items()}
            new={i:a for i,a in new.items() if a}
        L=2+q(d)+sum(q(a) for a in new.values())+closed_route_cost(list(new))
        if best is None or L<best:
            best,bestd=L,d
    return best,bestd


def _load_nested_tables():
    table_path=Path(__file__).resolve().parents[1]/'results'/'nested_tables.pkl'
    if not table_path.exists():
        raise SystemExit('missing results/nested_tables.pkl; run: python experiments/precompute_tables.py')
    data=pickle.loads(table_path.read_bytes())
    return data['kappa'], data['decomp']

_KAPPA,_DECOMP=_load_nested_tables()


def nested_one_scratch_upper(targets: dict[int,int]) -> int|None:
    if not targets: return None
    offs=sorted(targets)
    if all(i>0 for i in offs):
        t={i:targets[i] for i in offs}
    elif all(i<0 for i in offs):
        t={-i:targets[i] for i in offs}
    else:
        return None
    S=max(t)+1
    best=None
    for f in range(1,256):
        bs={}; arith=0
        for i,k in t.items():
            cost,b,r=_DECOMP[f][k]
            bs[i]=b; arith += cost
        active=[i for i,b in bs.items() if b]
        if not active: continue
        L=2+1+2+_KAPPA[f]+arith+2*S+2*(S-min(active))
        if best is None or L<best: best=L
    return best

@dataclass
class Profile:
    name: str
    bf_bytes: int
    loops: int
    max_depth: int
    leaf_loops: int
    leaf_arithmetic: int
    leaf_arith_balanced: int
    leaf_arith_moving: int
    c0_leaf_arith_balanced: int
    rescale_eligible: int
    rescale_profitable: int
    rescale_savings: int
    transfer_like: int
    clear_like: int
    io_commands: int
    max_abs_pointer_run: int
    moving_leaf_deltas: dict[str,int]
    control_gcds: dict[str,int]
    target_counts: dict[str,int]
    standard_one_side_transfers: int
    nested_if_zero_scratch_profitable: int
    nested_if_zero_scratch_savings: int
    pure_scan_leaf_loops: int
    arithmetic_moving_leaf_loops: int
    recursively_static_balanced_loops: int
    recursively_static_moving_loops: int
    recursively_dynamic_loops: int


def recursive_static_classes(code: str, roots: list[Loop]):
    cache={}
    def rec(lp: Loop):
        child_by_start={c.start:c for c in lp.children}
        i=lp.start+1; delta=0
        while i<lp.end:
            c=child_by_start.get(i)
            if c is not None:
                cd=rec(c)
                if cd is None or cd != 0:
                    cache[(lp.start,lp.end)]=None
                    return None
                i=c.end+1
                continue
            ch=code[i]
            if ch=='>': delta+=1
            elif ch=='<': delta-=1
            i+=1
        cache[(lp.start,lp.end)]=delta
        return delta
    counts=Counter()
    for lp in flatten_loops(roots):
        d=rec(lp)
        if d is None: counts['dynamic']+=1
        elif d==0: counts['balanced']+=1
        else: counts['moving']+=1
    return counts


def profile(name,text):
    code=strip_bf(text)
    roots=parse_loops(code)
    loops=flatten_loops(roots)
    leaf=[lp for lp in loops if not lp.children]
    rescale_eligible=rescale_profitable=rescale_savings=0
    leaf_arithmetic=leaf_bal=leaf_mov=c0=transfer_like=clear_like=0
    one_side=nest_prof=nest_save=0
    pure_scan=moving_arith=0
    gcds=Counter(); targets=Counter(); moving=Counter()
    for lp in leaf:
        eff=body_effect(lp.body)
        if eff is None: continue
        leaf_arithmetic += 1
        dp, coeff, _, _ = eff
        if dp != 0:
            leaf_mov += 1; moving[dp]+=1
            if set(lp.body) <= {'>'} or set(lp.body) <= {'<'}:
                pure_scan += 1
            else:
                moving_arith += 1
            continue
        leaf_bal += 1
        c=coeff.get(0,0)
        if c == 0: c0 += 1
        else: gcds[math.gcd(c,256)] += 1
        t={i:a for i,a in coeff.items() if i != 0 and a}
        targets[len(t)] += 1
        if len(t)==0: clear_like += 1
        if c in (1,255) and t: transfer_like += 1
        if c == 255 and t and (all(i>0 for i in t) or all(i<0 for i in t)):
            one_side += 1
            nested = nested_one_scratch_upper(t)
            flat,_tmp = exact_flat_best(coeff)
            if nested is not None and flat is not None and nested < flat:
                nest_prof += 1
                nest_save += flat-nested
        best,_=exact_flat_best(coeff)
        if c != 0:
            g=math.gcd(c,256)
            if not any(a%g for a in t.values()): rescale_eligible += 1
        if best is not None:
            orig=len(lp.body)+2
            if best < orig:
                rescale_profitable += 1; rescale_savings += orig-best
    static_classes=recursive_static_classes(code, roots)
    run=mx=0; prev=None
    for ch in code:
        if ch in '<>':
            if ch==prev: run += 1
            else: run=1; prev=ch
            mx=max(mx,run)
        else: run=0; prev=None
    return Profile(
        name=name,bf_bytes=len(code),loops=len(loops),max_depth=max((x.depth for x in loops),default=0),
        leaf_loops=len(leaf),leaf_arithmetic=leaf_arithmetic,leaf_arith_balanced=leaf_bal,
        leaf_arith_moving=leaf_mov,c0_leaf_arith_balanced=c0,rescale_eligible=rescale_eligible,
        rescale_profitable=rescale_profitable,rescale_savings=rescale_savings,
        transfer_like=transfer_like,clear_like=clear_like,io_commands=code.count('.')+code.count(','),
        max_abs_pointer_run=mx,moving_leaf_deltas={str(k):v for k,v in moving.most_common()},
        control_gcds={str(k):v for k,v in sorted(gcds.items())},
        target_counts={str(k):v for k,v in sorted(targets.items())},
        standard_one_side_transfers=one_side,
        nested_if_zero_scratch_profitable=nest_prof,
        nested_if_zero_scratch_savings=nest_save,
        pure_scan_leaf_loops=pure_scan,
        arithmetic_moving_leaf_loops=moving_arith,
        recursively_static_balanced_loops=static_classes['balanced'],
        recursively_static_moving_loops=static_classes['moving'],
        recursively_dynamic_loops=static_classes['dynamic']
    )


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('files', nargs='+')
    ap.add_argument('--json', action='store_true')
    args=ap.parse_args()
    profiles=[]
    for f in args.files:
        p=Path(f); profiles.append(profile(p.name,p.read_text(errors='ignore')))
    if args.json:
        print(json.dumps([asdict(p) for p in profiles],indent=2))
    else:
        for p in profiles:
            print(p)

if __name__=='__main__': main()
