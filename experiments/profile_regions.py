from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

BF = set("><+-.,[]")


def strip_bf(text: str) -> str:
    return "".join(ch for ch in text if ch in BF)


@dataclass
class Loop:
    start: int
    end: int
    children: list["Loop"] = field(default_factory=list)
    delta: int | None = None


def parse_loops(code: str) -> list[Loop]:
    stack: list[tuple[int, list[Loop]]] = []
    roots: list[Loop] = []
    for i, ch in enumerate(code):
        if ch == "[":
            stack.append((i, []))
        elif ch == "]":
            if not stack:
                raise ValueError(f"unmatched ] at {i}")
            start, children = stack.pop()
            loop = Loop(start, i, children)
            if stack:
                stack[-1][1].append(loop)
            else:
                roots.append(loop)
    if stack:
        raise ValueError("unmatched [")
    return roots


def classify_delta(code: str, loop: Loop) -> int | None:
    """Return net pointer delta iff every nested loop is recursively balanced."""
    for child in loop.children:
        classify_delta(code, child)
    if any(child.delta != 0 for child in loop.children):
        loop.delta = None
        return None

    children = {child.start: child for child in loop.children}
    i = loop.start + 1
    delta = 0
    while i < loop.end:
        child = children.get(i)
        if child is not None:
            i = child.end + 1
            continue
        if code[i] == ">":
            delta += 1
        elif code[i] == "<":
            delta -= 1
        i += 1
    loop.delta = delta
    return delta


def flatten(roots: list[Loop]) -> list[Loop]:
    out: list[Loop] = []

    def visit(loop: Loop) -> None:
        out.append(loop)
        for child in loop.children:
            visit(child)

    for root in roots:
        visit(root)
    return out


def collect_epochs(code: str, roots: list[Loop]) -> list[tuple[int, int, int]]:
    """Collect disjoint maximal relative-base epochs.

    Recursively balanced child loops stay in the current epoch. A moving or
    dynamic child loop is a barrier. Its body is recursively segmented using a
    fresh unknown base pointer. Barrier brackets are intentionally uncovered.
    """
    for root in roots:
        classify_delta(code, root)

    epochs: list[tuple[int, int, int]] = []

    def visit_scope(
        start: int, end: int, children: list[Loop], depth: int
    ) -> None:
        current = start
        for child in children:
            if child.delta == 0:
                continue
            if current < child.start:
                epochs.append((current, child.start, depth))
            visit_scope(child.start + 1, child.end, child.children, depth + 1)
            current = child.end + 1
        if current < end:
            epochs.append((current, end, depth))

    visit_scope(0, len(code), roots, 0)
    return epochs


@dataclass
class RegionProfile:
    name: str
    bf_bytes: int
    loops: int
    balanced_loops: int
    moving_loops: int
    dynamic_loops: int
    epochs: int
    epoch_covered_bytes: int
    epoch_coverage_pct: float
    epoch_bytes_ge_4: int
    epoch_bytes_ge_8: int
    epoch_bytes_ge_16: int
    epoch_bytes_ge_32: int
    epochs_with_balanced_loop: int
    bytes_in_epochs_with_balanced_loop: int
    longest_epoch: int
    mean_epoch_len: float


def profile(name: str, text: str) -> RegionProfile:
    code = strip_bf(text)
    roots = parse_loops(code)
    epochs = collect_epochs(code, roots)
    loops = flatten(roots)

    lengths = [end - start for start, end, _ in epochs if start < end]
    covered = sum(lengths)
    balanced_loops = [loop for loop in loops if loop.delta == 0]
    moving_loops = sum(loop.delta not in (0, None) for loop in loops)
    dynamic_loops = sum(loop.delta is None for loop in loops)
    barriers = moving_loops + dynamic_loops

    ordered_epochs = sorted(epochs)
    assert all(
        left[1] <= right[0]
        for left, right in zip(ordered_epochs, ordered_epochs[1:])
    ), "epoch ranges overlap"
    assert covered + 2 * barriers == len(code), (
        "every moving/dynamic loop must contribute exactly its two barrier brackets"
    )

    loop_epoch_lengths: list[int] = []
    for start, end, _ in epochs:
        if any(start <= loop.start and loop.end < end for loop in balanced_loops):
            loop_epoch_lengths.append(end - start)

    return RegionProfile(
        name=name,
        bf_bytes=len(code),
        loops=len(loops),
        balanced_loops=len(balanced_loops),
        moving_loops=moving_loops,
        dynamic_loops=dynamic_loops,
        epochs=len(lengths),
        epoch_covered_bytes=covered,
        epoch_coverage_pct=round(100.0 * covered / len(code), 2) if code else 100.0,
        epoch_bytes_ge_4=sum(length for length in lengths if length >= 4),
        epoch_bytes_ge_8=sum(length for length in lengths if length >= 8),
        epoch_bytes_ge_16=sum(length for length in lengths if length >= 16),
        epoch_bytes_ge_32=sum(length for length in lengths if length >= 32),
        epochs_with_balanced_loop=len(loop_epoch_lengths),
        bytes_in_epochs_with_balanced_loop=sum(loop_epoch_lengths),
        longest_epoch=max(lengths, default=0),
        mean_epoch_len=round(covered / len(lengths), 3) if lengths else 0.0,
    )


def aggregate(profiles: list[RegionProfile]) -> dict[str, int | float]:
    total = sum(item.bf_bytes for item in profiles)
    epochs = sum(item.epochs for item in profiles)
    fields = [
        "bf_bytes", "loops", "balanced_loops", "moving_loops", "dynamic_loops",
        "epochs", "epoch_covered_bytes", "epoch_bytes_ge_4", "epoch_bytes_ge_8",
        "epoch_bytes_ge_16", "epoch_bytes_ge_32", "epochs_with_balanced_loop",
        "bytes_in_epochs_with_balanced_loop",
    ]
    out = {field: sum(getattr(item, field) for item in profiles) for field in fields}
    out["epoch_coverage_pct"] = round(100.0 * out["epoch_covered_bytes"] / total, 2) if total else 100.0
    out["epoch_ge_4_pct"] = round(100.0 * out["epoch_bytes_ge_4"] / total, 2) if total else 100.0
    out["epoch_ge_8_pct"] = round(100.0 * out["epoch_bytes_ge_8"] / total, 2) if total else 100.0
    out["epoch_ge_16_pct"] = round(100.0 * out["epoch_bytes_ge_16"] / total, 2) if total else 100.0
    out["epoch_ge_32_pct"] = round(100.0 * out["epoch_bytes_ge_32"] / total, 2) if total else 100.0
    out["balanced_loop_epoch_pct"] = round(100.0 * out["bytes_in_epochs_with_balanced_loop"] / total, 2) if total else 100.0
    out["longest_epoch"] = max((item.longest_epoch for item in profiles), default=0)
    out["mean_epoch_len"] = round(out["epoch_covered_bytes"] / epochs, 3) if epochs else 0.0
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    profiles = [
        profile(Path(path).name, Path(path).read_text(errors="ignore"))
        for path in args.files
    ]
    if args.json:
        print(json.dumps({
            "definition": (
                "A relative-base epoch is a maximal lexical-scope interval in which "
                "every nested loop returns the pointer to its entry cell. Moving or "
                "dynamic child loops split the epoch; their bodies are recursively "
                "segmented with a fresh unknown base. Coverage is analyzability, not "
                "a claimed compression ratio."
            ),
            "profiles": [asdict(item) for item in profiles],
            "aggregate": aggregate(profiles),
        }, indent=2))
    else:
        for item in profiles:
            print(item)
        print("aggregate", aggregate(profiles))


if __name__ == "__main__":
    main()
