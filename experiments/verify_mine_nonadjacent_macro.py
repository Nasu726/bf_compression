from __future__ import annotations

"""Independent differential validation of automatic non-adjacent BF mining."""

from random import Random

from bf_runtime import run_bf
from mine_nonadjacent_macro import mine_nonadjacent


def observed(result):
    return result.output, result.input_consumed, result.pointer, result.memory


def check(source: str, inputs: str = ""):
    result = mine_nonadjacent(
        source, max_atoms=2_500, max_period=256,
        max_groups=20, max_calls=5
    )
    assert result.result_chars <= result.baseline_chars
    assert len(result.source) == result.result_chars
    if result.selected:
        assert result.macro_chars >= 36
        assert result.calls >= 2
        assert any(result.gap_chars)
    old = run_bf(source, input_data=inputs, memory_size=256, step_limit=8_000_000)
    new = run_bf(result.source, input_data=inputs, memory_size=256, step_limit=8_000_000)
    assert observed(old) == observed(new), (
        source, result.source,
        observed(old)[:3], observed(new)[:3]
    )
    return result


def main():
    seed=Random(0xDEADBEEF)
    longblock="+.-." * 48
    cases=[
        (longblock+"[-]."+longblock+"++."+longblock, ""),
        ("++++"+longblock+"[-]."+longblock+"++."+longblock+"---."+longblock, ""),
        (">>++++<<"+longblock+">.<"+longblock+"++."+longblock+"[-]."+longblock, ""),
        ("+."*85+"[-]."+"+."*85+"++."+"+."*85, ""),
        (".,."*80+"++."+".,."*80+"[-]."+".,."*80, "Hello world"),
        ("++++[->+<]"*12, ""),
    ]
    for _ in range(16):
        block = "".join(seed.choice(("+.", "-.", ".+", "[-].", ",.", "+-.")) for _ in range(seed.randrange(30, 95)))
        gaps = ["+"*seed.randrange(1, 4)+".", "[-]+.", "--." ]
        seq = block+gaps[0]+block+gaps[1]+block+gaps[2]+block
        cases.append((seq, "".join(chr(seed.randrange(32, 127)) for _ in range(45))))
    records = [check(src, data) for src, data in cases]
    assert any(row.selected for row in records)
    print(f"automatic nonadjacent macro cases passed: {len(records)}")
    print(
        f"aggregate: raw={sum(r.baseline_chars for r in records):,} "
        f"shorter={sum(r.result_chars for r in records):,}; "
        f"selected={sum(r.selected for r in records)}/{len(records)}"
    )
    for i,row in enumerate(records[:6]):
        print(f"case {i}: {row.baseline_chars:,}->{row.result_chars:,}; "
              f"calls={row.calls}, macro={row.macro_chars}, "
              f"groups={row.considered_groups}, reason={row.reason}")


if __name__ == "__main__":
    main()
