from __future__ import annotations

"""Verify local epoch-zero proof for nonadjacent macro sharing.

The reference sources include pointer-moving loops whose exit pointer
depends on input data. A global absolute scratch cell cannot be proven
unused, but explicit zeroing after the barrier gives *relative* zero
scratch witnesses. Full tape, I/O, pointer and input consumption are
checked with the existing standard BF runtime.
"""

from random import Random

from bf_runtime import run_bf
from nonadjacent_epoch_macro import (
    analyze_prefix,
    construct_epoch_phase_reuse,
    relative_accesses,
)


def obs(result):
    return result.output, result.input_consumed, result.pointer, result.memory


def check(prefix, macro, gaps, suffix="", data="", require_selected=None):
    result = construct_epoch_phase_reuse(prefix, macro, gaps, suffix)
    source = prefix + macro + "".join(g + macro for g in gaps) + suffix
    assert result.literal_source == source
    assert len(result.source) <= len(source)
    if require_selected is not None:
        assert result.selected == require_selected, (
            prefix, macro, gaps, result.selected, result.scratch_control
        )
    width = 320
    ref = run_bf(source, input_data=data, memory_size=width, step_limit=15_000_000)
    got = run_bf(result.source, input_data=data, memory_size=width, step_limit=15_000_000)
    assert obs(ref) == obs(got), (
        source, result.source, data,
        obs(ref)[:3], obs(got)[:3]
    )
    return len(source), len(result.source), result.selected


def main():
    assert analyze_prefix("++[>]").value(0) == 0
    assert analyze_prefix(",[>]").value(1) is None
    assert analyze_prefix(",[>]>[-]>[-]<<").value(1) == 0
    assert relative_accesses("[->+<]") == {0, 1}
    assert relative_accesses("[>]") is None

    moving = ",[>]" + ">[-]" * 12 + "<" * 12
    assert analyze_prefix(moving).barriers == 1
    block = "+.-." * 64
    examples = [
        (moving, block, ("++.", "[-]."), ">+.<", "A", True),
        (moving, block, (".", "--.", "+.", "[-]."), ">+.<", "\x00", True),
        ("++[>]" + ">[-]"*12 + "<"*12, ".,."*75, ("++.", "[-]."), "", "Hello!", True),
        ("++[>]" + ">[-]"*12 + "<"*12, "[->+<]."*45, ("++.", "[->+<]."), "", "", True),
        # Exhaust the small scratch search region using unknown input data.
        ("," + ">,"*99 + "<"*99, block, (".",), "", "abcdefg", False),
        # A moving loop inside the reusable macro is not pointer-balanced.
        (moving, "[>]" + "+."*100, ("++.",), "", "X", False),
        # A gap that moves and does not return to the anchor is rejected.
        (moving, block, ("+>.",), "", "X", False),
    ]
    rng = Random(0xE20C)
    for _ in range(48):
        inp = "".join(chr(rng.randrange(1, 127)) for _ in range(40))
        prefix = ",[>]" + ">[-]"*12 + "<"*12
        m = "".join(rng.choice(("+.", "-.", "[-].", ",.", "+-.")) for _ in range(rng.randrange(40, 110)))
        gaps = tuple("".join(rng.choice(("+.", "[-].", ".", "-")) for _ in range(rng.randrange(1, 5))) for _ in range(rng.randrange(1, 5)))
        examples.append((prefix, m, gaps, ">+.<", inp, None))
    rows=[check(*item) for item in examples]
    print(f"epoch-local zero-scratch full-state differential cases passed: {len(rows)}")
    print(f"source aggregate: raw={sum(x for x,_,_ in rows):,} rewritten={sum(y for _,y,_ in rows):,}")
    print(f"selected={sum(z for _,_,z in rows)}/{len(rows)}")
    for idx, (a,b,selected) in enumerate(rows[:7]):
        print(f"case {idx}: {a:,}->{b:,} selected={selected}")


if __name__ == "__main__":
    main()
