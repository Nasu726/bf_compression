from __future__ import annotations

"""Whole-program full-state tests for loop-body, unknown-entry macro sharing."""

from random import Random

from bf_runtime import run_bf
from mine_nested_scope_macro import mine_nested_once


def observe(r):
    return r.output, r.input_consumed, r.pointer, r.memory


def outer_macro(body: str, gaps: tuple[str, ...], *, count: int = 4) -> str:
    clear = ">[-]" * 8 + "<" * 8
    segment = body + "".join(g + body for g in gaps)
    return "+"*count + "[>" + clear + segment + "<-]"


def deep_macro(body: str, gaps: tuple[str,...]) -> str:
    clear = ">[-]" * 8 + "<" * 8
    segment = body + "".join(g + body for g in gaps)
    return "++[>+++[>" + clear + segment + "<[-]]<-]"


def check(program: str, inp: str = ""):
    result=mine_nested_once(
        program, max_scopes=40, min_body_chars=100,
        max_body_chars=10_000, max_period=256
    )
    assert len(result.source)<=len(program)
    expected=run_bf(program, input_data=inp, memory_size=320, step_limit=20_000_000)
    actual=run_bf(result.source, input_data=inp, memory_size=320, step_limit=20_000_000)
    assert observe(expected)==observe(actual), (
        program, result.source, observe(expected)[:3], observe(actual)[:3]
    )
    return result


def main():
    base="+.-."*64
    cases=[
        (outer_macro(base,("++.", "[-].")), ""),
        (outer_macro(base,(".", "--.", "+."),count=3), ""),
        (outer_macro(".,."*70, ("[-].", "++."),count=2), "abcdefg"),
        (deep_macro(base, ("++.", "[-].")), ""),
        (deep_macro("[->+<]."*45, (".", "--.")), ""),
        (",[>]" + outer_macro(base,("++.",)), "X"),
        ("++++[+.-.+.-.<-]", ""),
    ]
    rng=Random(0x9A7E)
    for _ in range(15):
        macro="".join(rng.choice(("+.", "-.", ".", "[-].", ",.")) for _ in range(rng.randrange(55, 100)))
        gap="".join(rng.choice(("+.", "-.", "[-].")) for _ in range(3))
        code=outer_macro(macro,(gap,"++."),count=rng.randrange(1,5))
        data="".join(chr(rng.randrange(33,127)) for _ in range(90))
        cases.append((code,data))
    rows=[check(src,data) for src,data in cases]
    assert any(r.selected for r in rows)
    print(f"nested unknown-entry macro differential cases passed: {len(rows)}")
    print(f"aggregate: raw={sum(r.original_chars for r in rows):,} shortened={sum(r.result_chars for r in rows):,}")
    print(f"selected={sum(r.selected for r in rows)}/{len(rows)}")
    for i,r in enumerate(rows[:7]):
        print(f"case {i}: {r.original_chars:,}->{r.result_chars:,}; "
              f"loops={r.lexical_loops}, scopes={r.considered_scopes}, depth={r.chosen_depth}")


if __name__ == "__main__":
    main()
