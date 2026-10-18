from __future__ import annotations

"""Full-state differential tests for executable non-adjacent macro sharing."""

from random import Random

from bf_runtime import run_bf
from nonadjacent_phase_macro import construct_phase_reuse, phase_dispatcher


def observe(x):
    return x.output, x.input_consumed, x.pointer, x.memory


def test(
    prefix: str,
    macro: str,
    gaps: tuple[str, ...],
    suffix: str = "",
    input_data: str = "",
) -> tuple[int, int, bool]:
    result = construct_phase_reuse(prefix, macro, gaps, suffix)
    literal = prefix + macro + "".join(g + macro for g in gaps) + suffix
    assert result.literal_source == literal
    assert len(result.source) <= len(literal)
    assert result.selected == (len(result.source) < len(literal))
    if result.selected:
        assert result.source.count(macro) == 1, (
            "macro should appear literally only once inside the shared source",
            macro,
        )
    size = max(256, result.scratch_control + result.calls + 128)
    old = run_bf(literal, input_data=input_data, memory_size=size, step_limit=8_000_000)
    new = run_bf(result.source, input_data=input_data, memory_size=size, step_limit=8_000_000)
    assert observe(old) == observe(new), (
        literal, result.source, input_data,
        observe(old)[:3], observe(new)[:3]
    )
    return len(literal), len(result.source), result.selected


def main():
    rng = Random(0xFACE)
    block = "+.-." * 55
    cases = [
        ("", block, (".",), "", ""),
        ("", block, ("[-].", "+.", "."), "", ""),
        (">>++++<<", block, ("+.", "[-]."), ">>.<.<<", ""),
        ("", ".,." * 90, ("+[-].", ".", "-."), "", "Hello world!"),
        ("", "+." * 120, ("[-]++.", "[->+<]."), ">+<.", ""),
        ("", "[-]." * 95, ("+.", "--.", "[->+<]"), "", ""),
        ("", "+.>+<" * 60, ("++.", ".>",), "", ""),  # rejected gap
        ("", ">" * 18 + "+" * 50 + "<" * 18, (".", "-.", "."), "", ""),
        ("", "." * 220, (",.", "++."), ".", "abc"),
        ("", "[->+<]." * 35, ("++.", ">[-]<"), "", ""),
    ]
    rejected = [
        ("", "+.>", (".",), ""),
        ("", "[>]", (".",), ""),
        ("", "+.", (">",), ""),
        ("", "+.", (",.",), "[>]"),
    ]
    for prefix, macro, gaps, suffix in rejected:
        x=construct_phase_reuse(prefix, macro, gaps, suffix)
        assert not x.selected
        assert x.source == x.literal_source

    # Long enough bodies make the sharing useful. Other examples may be
    # intentionally rejected by exact source-length cost.
    for _ in range(60):
        macro = "".join(rng.choice(("+.", "-.", "[-].", "+-.", ",.")) for _ in range(rng.randrange(45, 140)))
        gaps = tuple(
            "".join(rng.choice((".", "+.", "-", "[-]")) for _ in range(rng.randrange(1, 5)))
            for _ in range(rng.randrange(1, 6))
        )
        prefix = "+" * rng.randrange(8)
        cases.append((prefix, macro, gaps, "", "".join(chr(rng.randrange(32, 126)) for _ in range(50))))

    results = []
    for prefix, macro, gaps, suffix, data in cases:
        # Reject invalid input regions with no forced rewriting.
        result=construct_phase_reuse(prefix, macro, gaps, suffix)
        if not result.selected and (macro.endswith(">") or any(g == ".>" for g in gaps)):
            assert result.source == result.literal_source
            continue
        results.append(test(prefix, macro, gaps, suffix, data))

    assert any(chosen for _, _, chosen in results)
    print(f"nonadjacent phase-macro full-state cases passed: {len(results)}")
    print(
        f"source aggregate: literal={sum(a for a, _, _ in results):,} "
        f"selected={sum(b for _, b, _ in results):,} "
        f"profitable={sum(s for _, _, s in results)}"
    )
    for prefix, macro, gaps, suffix, data in cases[:5]:
        x=construct_phase_reuse(prefix, macro, gaps, suffix)
        print(
            f"macro length={len(macro)}, calls={len(gaps)+1}, gaps={list(map(len,gaps))}: "
            f"literal={len(x.literal_source)} candidate={len(x.source)} selected={x.selected}"
        )


if __name__ == "__main__":
    main()
