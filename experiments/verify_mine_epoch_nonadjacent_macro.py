from __future__ import annotations

"""Differential tests for root-scope relative-epoch macro mining."""

from random import Random

from bf_runtime import run_bf
from mine_epoch_nonadjacent_macro import lexical_epochs, mine_epoch_macros


def obs(r):
    return r.output, r.input_consumed, r.pointer, r.memory


def check(src: str, data: str = ""):
    found=mine_epoch_macros(
        src, max_atoms_per_epoch=3_000, max_period=256,
        max_groups_per_epoch=16, max_calls=5
    )
    assert found.result_chars <= found.initial_chars
    baseline=run_bf(src, input_data=data, memory_size=320, step_limit=15_000_000)
    actual=run_bf(found.source, input_data=data, memory_size=320, step_limit=15_000_000)
    assert obs(baseline)==obs(actual), (src, found.source, obs(baseline)[:3],obs(actual)[:3])
    return found


def main():
    moving = ",[>]" + ">[-]" * 12 + "<" * 12
    static = ">[-]" * 12 + "<" * 12
    assert len(lexical_epochs(moving + "+."*70)) >= 2
    assert len(lexical_epochs("+++[->+<]+."*25)) == 1

    block = "+.-."*48
    cases=[
        (moving + block+"[-]."+block+"++."+block, "A"),
        (moving + block+"[-]."+block+"++."+block+"---."+block, "\0"),
        (moving + ".,."*70 + "++." + ".,."*70 + "[-]." + ".,."*70, "xyz"),
        ("++[>]" + static + block + "." + block + "++." + block, ""),
        (moving + "[->+<]."*40 + "++." + "[->+<]."*40 + "[-]." + "[->+<]."*40, "Hello"),
        (","+">,"*15+"<"*15+block+"[-]."+block, "test"),
        ("++[>]" + static + (">+.<"*30) + "++." + (">+.<"*30), ""),
    ]
    rng=Random(0xE90C)
    for i in range(15):
        macro="".join(rng.choice(("+.", "-.", ".", ",.", "[-].")) for _ in range(rng.randrange(40, 85)))
        gap="".join(rng.choice(("+.", ".", "[-].")) for _ in range(3))
        src=moving+macro+gap+macro+"+++."+macro
        data="".join(chr(rng.randrange(32,127)) for _ in range(36))
        cases.append((src,data))
    rows=[check(source,data) for source,data in cases]
    print(f"epoch-aware automatic nonadjacent macro differential cases passed: {len(rows)}")
    print(f"aggregate: raw={sum(r.initial_chars for r in rows):,} optimized={sum(r.result_chars for r in rows):,}")
    print(f"selected={sum(r.selected for r in rows)}/{len(rows)}")
    for i,r in enumerate(rows[:7]):
        print(f"case {i}: {r.initial_chars:,}->{r.result_chars:,}; "
              f"epochs={r.epoch_count} groups={r.considered_groups} selected={r.selected}")


if __name__ == "__main__":
    main()
