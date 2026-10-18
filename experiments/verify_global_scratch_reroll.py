from __future__ import annotations

"""Full-tape/input trace checks for global unused-scratch BF rerolling."""

from random import Random

from bf_runtime import run_bf
from global_scratch_reroll import analyze_global_static, reroll


def observe(result):
    return result.output, result.input_consumed, result.pointer, result.memory


def verify_case(source: str, data: str = ""):
    rewritten, events, reason = reroll(source, max_period=12)
    assert reason == "ok", (reason, source[:160])
    assert len(rewritten) <= len(source)
    old = run_bf(source, input_data=data, memory_size=256, step_limit=15_000_000)
    new = run_bf(rewritten, input_data=data, memory_size=256, step_limit=15_000_000)
    assert observe(old) == observe(new), (
        source, rewritten, data, observe(old)[:3], observe(new)[:3]
    )
    assert all(v == 0 for v in new.memory[32:])
    return len(source), len(rewritten), len(events)


def main():
    templates = [
        ("+>+.<", 100, ""),
        (",.", 100, "Hello\n"),
        ("+>+<", 100, ""),
        (">+.<", 70, ""),
        (">>+.<.<", 75, ""),
        ("[->+<]", 60, ""),
        (">[-]<", 90, ""),
        ("[->+>+<<]", 80, ""),
        (">+<[-]>.<", 60, ""),
        (">>+<<>.<", 60, ""),
        ("+.-.", 70, ""),
        ("><", 180, ""),
        ("[->+<]>[-]<", 50, ""),
    ]
    cases = [("++++++" + block * repeat, data) for block, repeat, data in templates]
    cases += [
        ("[>]", ""),  # moving loop: reject; empty initial cell means no move
        ("+[>]", ""), # moving loop: reject; finds a zero cell
        (">+<[>+<]", ""), # balanced loop syntax, may diverge, don't execute
    ]
    assert analyze_global_static("[>]") is None
    assert analyze_global_static("+[>]") is None
    for source, _ in cases[-3:]:
        result, changes, reason = reroll(source)
        if source != ">+<[>+<]":
            assert reason != "ok" and result == source and not changes

    good = cases[:-3]
    rng = Random(0x5CA7C)
    body_options = ["+>+<", "-.>", "[-]", "><", ">+<", ",.", "[->+<]"]
    # Exclude an intentionally unbalanced pointer option from construction.
    body_options.remove("-.>")
    for _ in range(75):
        parts = [rng.choice(body_options) for _ in range(rng.randrange(1, 5))]
        body = "".join(parts)
        count = rng.randrange(2, 90)
        casesrc = "+" * rng.randrange(1, 12) + body * count
        good.append((casesrc, "".join(chr(rng.randrange(32, 126)) for _ in range(60))))

    rows = [verify_case(source, data) for source, data in good]
    assert any(count for _, _, count in rows)
    print(f"global-scratch reroll full-state differential cases passed: {len(rows)}")
    print(
        f"source aggregate: {sum(a for a, _, _ in rows):,}->"
        f"{sum(b for _, b, _ in rows):,}; "
        f"profitable run records={sum(c for _, _, c in rows):,}"
    )
    for block, repeat, data in templates[:8]:
        source = "++++++" + block * repeat
        rewritten, events, reason = reroll(source)
        print(
            f"template={block!r} repeated={repeat} "
            f"raw={len(source):,} rerolled={len(rewritten):,} "
            f"runs={len(events)}"
        )


if __name__ == "__main__":
    main()
