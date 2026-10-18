from __future__ import annotations

"""Verify exact-gain signed-relational grammar expansion."""

import argparse
from collections import Counter
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_exact_signed_relational_grammar import build_grammar
from profile_signed_relational_macro_grammar import ADD, CONST, NEGADD, PARAM, Occ
from profile_parametric_vm import split_token
from profile_semantic_vm import semantic_tokens
from region_zero_opt import canonicalize, parse, precanonicalize, strip_bf


def expand(occ, terminals, arities, rules):
    if occ.symbol < len(terminals):
        return [(terminals[occ.symbol], occ.args)]
    rule = rules[occ.symbol - len(terminals)]
    args = iter(occ.args)
    vector = []
    for j, spec in enumerate(rule.specs):
        if spec.kind == PARAM:
            vector.append(next(args))
        elif spec.kind == CONST:
            vector.append(spec.value)
        elif spec.kind == ADD:
            vector.append(vector[spec.ref] + spec.value)
        elif spec.kind == NEGADD:
            vector.append(-vector[spec.ref] + spec.value)
        else:
            raise AssertionError(spec.kind)
    left_arity = arities[rule.left]
    return expand(Occ(rule.left, tuple(vector[:left_arity])), terminals, arities, rules) + expand(Occ(rule.right, tuple(vector[left_arity:])), terminals, arities, rules)


def verify(tokens, limit=128):
    terminals, arities, rules, seq = build_grammar(tokens, limit)
    recovered=[]
    for occ in seq:
        recovered.extend(expand(occ, terminals, arities, rules))
    assert recovered == [split_token(t) for t in tokens]
    return len(rules), len(seq)


def tokens_from_text(text):
    nodes=canonicalize(parse(precanonicalize(strip_bf(text))))
    return semantic_tokens(nodes, Counter())


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    args=ap.parse_args()
    synthetic=[]
    for base in range(-90,91,3):
        synthetic += [("M",base),("M",7-base),("A",3)]
    verify(synthetic,64)
    for name in args.files:
        tokens=tokens_from_text(Path(name).read_text(encoding="ascii", errors="ignore"))
        rules,start=verify(tokens,128)
        print(f"{name}: exact-gain grammar round-trip ok tokens={len(tokens):,} rules={rules} start={start:,}")
    print("exact-gain signed grammar reconstruction: ok")


if __name__ == "__main__":
    main()
