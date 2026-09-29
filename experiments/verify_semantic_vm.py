from __future__ import annotations

from collections import Counter

from profile_semantic_vm import (
    semantic_loop_token,
    semantic_tokens,
    token_definition,
)
from region_zero_opt import canonicalize, parse, precanonicalize


def parse_one_loop(code: str):
    nodes = canonicalize(parse(precanonicalize(code)))
    assert len(nodes) == 1
    return nodes[0]


def verify_odd_affine_formula() -> None:
    # For odd c, repeated x <- x+c reaches zero after the unique
    # k = -x*c^{-1} (mod 256) iterations.  Exhaust every odd generator and
    # every entry control value; this is the algebraic precondition behind the
    # AFFINE VM instruction.
    for c in range(1, 256, 2):
        inv = pow(c, -1, 256)
        for x in range(256):
            k_formula = (-x * inv) & 255
            cur = x
            k = 0
            while cur:
                cur = (cur + c) & 255
                k += 1
                assert k <= 255
            assert k == k_formula, (c, x, k, k_formula)
            for a in (1, 2, 7, 127, 128, 255):
                direct = (a * k) & 255
                transfer = (-a * inv) & 255
                summarized = (transfer * x) & 255
                assert direct == summarized, (c, x, a, direct, summarized)


def main() -> None:
    verify_odd_affine_formula()

    loop = parse_one_loop("[+++>++++++<]")
    token = semantic_loop_token(canonicalize(loop.body))
    assert token == ("AFFINE", ((1, 254),)), token

    loop = parse_one_loop("[-->+<]")
    token = semantic_loop_token(canonicalize(loop.body))
    assert token == ("LINEAR_LOOP", ((0, 254), (1, 1))), token

    loop = parse_one_loop("[>>>]")
    assert semantic_loop_token(canonicalize(loop.body)) == ("SCAN", 3)

    loop = parse_one_loop("[-]")
    assert semantic_loop_token(canonicalize(loop.body)) == ("CLEAR",)
    loop = parse_one_loop("[+]")
    assert semantic_loop_token(canonicalize(loop.body)) == ("CLEAR",)

    nodes = canonicalize(parse(precanonicalize(">>>><<++++--.[->+<]")))
    stats: Counter[str] = Counter()
    toks = semantic_tokens(nodes, stats)
    assert toks[0] == ("M", 2), toks
    assert toks[1] == ("A", 2), toks
    assert toks[2] == ("OUT",), toks
    assert toks[3] == ("AFFINE", ((1, 1),)), toks

    nested = canonicalize(parse(precanonicalize("[[->+<]>]")))
    stats = Counter()
    toks = semantic_tokens(nested, stats)
    assert toks == [
        ("LOOP_BEGIN",),
        ("AFFINE", ((1, 1),)),
        ("M", 1),
        ("LOOP_END",),
    ], toks

    # Definitions are self-delimiting once prefixed by their length in the
    # grammar serializer; every VM terminal kind used above has a nonempty
    # concrete representation.
    for tok in toks + [
        ("CLEAR",),
        ("SCAN", -7),
        ("LINEAR_LOOP", ((0, 2), (3, 255))),
        ("IN",),
    ]:
        assert token_definition(tok)

    print("semantic VM verification: ok")


if __name__ == "__main__":
    main()
