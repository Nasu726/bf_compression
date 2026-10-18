from __future__ import annotations

"""Runnable BF macro dictionary variants with numeric IDs and counted RUNs.

One-level, known-bound W-cell tape-window ABI. A macro may contain input,
output and statically balanced nested loops, but must return to the anchor,
stay inside W cells, and never access metadata. All generated BF is standalone
and restores pointer 0, final logical tape and zero scratch on termination.

The portfolio charges the *complete* source: constructor, shared dictionary
body, dispatch, runtime count loops, state transfers and cleanup. The grammar
is neither recursive nor parameterized and is not a universal BF compressor.
The runtime assumes wrapping 8-bit cells, zero tape and zero-byte EOF.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from threaded_window_macro_vm import check_window_macro, literal_program
from threaded_window_macro_vm import build_threaded as onehot_program


def signed_initializer(value: int) -> str:
    value &= 255
    return "+" * value if value <= 128 else "-" * (256 - value)


def _verify(macros: Sequence[str], calls: Sequence[int], width: int):
    if not 1 <= len(macros) <= 128:
        raise ValueError("1..128 dictionary symbols required")
    for m in macros:
        check_window_macro(m, width)
    if any(not isinstance(i, int) or not 0 <= i < len(macros) for i in calls):
        raise ValueError("macro ID out of range")


def numeric_payload(macros: Sequence[str], calls: Sequence[int], width: int) -> str:
    _verify(macros, calls, width)
    if not calls:
        return ""
    r = width + 4
    code = [">" * r]
    for i in reversed(calls):
        code += [">" * width, signed_initializer(i), ">>>+>"]
    return "".join(code)


def numeric_executor(macros: Sequence[str], width: int) -> str:
    _verify(macros, (), width)
    r = width + 4
    body = ["[-]<<<"]  # live -> numeric symbol Q
    for macro in macros:
        # Q at W, T at W+1 and R at W+2.
        # Preserve Q and leave T=1 exactly when Q was zero.
        body += [">+<", "[->[-]>+<<]", ">>[-<<+>>]<<"]
        # On the selected branch set Q to 255, call macro once, and
        # return to the test flag. The flag is consumed.
        body += [">[-<-", "<" * width, macro, ">" * width, ">]<"]
        # Before a match Q counts down to zero; after a match it starts
        # at 254 and cannot reach zero again with <=128 cases.
        body.append("-")
    body += ["[-]<"]  # clear Q, move to last logical data cell
    for j in range(width - 1, -1, -1):
        body += ["[-", "<" * r, "+", ">" * r, "]"]
        if j:
            body.append("<")
    body.append("<")  # previous record live flag
    return "[" + "".join(body) + "]"


def numeric_program(macros: Sequence[str], calls: Sequence[int], width: int) -> str:
    _verify(macros, calls, width)
    if not calls:
        return ""
    r = width + 4
    return numeric_payload(macros, calls, width) + "<" + numeric_executor(macros, width) + "<" * (r - 1)


def compress_calls(calls: Sequence[int], k: int, width: int, *, cost_per_record=None):
    """Optimal RLE segmentation for the supplied exact constructor cost."""
    if not 1 <= k <= 128 or width < 1:
        raise ValueError("invalid dictionary/window")
    if any(not isinstance(i, int) or not 0 <= i < k for i in calls):
        raise ValueError("invalid call")
    n = len(calls)
    r = width + k + 2
    best = [10**18] * (n + 1)
    choice = [None] * n
    best[n] = 0
    for i in range(n - 1, -1, -1):
        for j in range(i, min(n, i + 255)):
            if calls[j] != calls[i]:
                break
            count = j - i + 1
            source_cost = (
                r + 2 + len(signed_initializer(count))
                if cost_per_record is None
                else cost_per_record(calls[i], count)
            )
            total = source_cost + best[j + 1]
            if total < best[i]:
                best[i] = total
                choice[i] = (j + 1, calls[i], count)
    result = []
    i = 0
    while i < n:
        stop, symbol, count = choice[i]
        result.append((symbol, count))
        i = stop
    return tuple(result)


def rle_onehot_payload(macros: Sequence[str], calls: Sequence[int], width: int) -> str:
    k = len(macros)
    if not k:
        raise ValueError("empty dictionary")
    for m in macros:
        check_window_macro(m, width)
    runs = compress_calls(calls, k, width)
    if not runs:
        return ""
    r = width + k + 2
    code = [">" * r]
    for symbol, count in reversed(runs):
        code.append(">" * width)
        for j in range(k):
            if j:
                code.append(">")
            if j == symbol:
                code.append("+")
        code += [">", signed_initializer(count), ">+>"]
    return "".join(code)


def rle_onehot_executor(macros: Sequence[str], width: int) -> str:
    k = len(macros)
    if not k:
        raise ValueError("empty dictionary")
    for m in macros:
        check_window_macro(m, width)
    r = width + k + 2
    code = ["[", "-<"]  # live -> count C
    for j in range(k - 1, -1, -1):
        dist = k - j
        to_data = width + k
        # Selected macro executes C times on the same W-cell state.
        code += ["<", "[-", ">" * dist, "[", "<" * to_data,
                 macros[j], ">" * to_data, "-]", "<" * dist, "]"]
    code.append("<")
    for j in range(width - 1, -1, -1):
        code += ["[-", "<" * r, "+", ">" * r, "]"]
        if j:
            code.append("<")
    code += ["<", "]"]
    return "".join(code)


def rle_onehot_program(macros: Sequence[str], calls: Sequence[int], width: int) -> str:
    if not calls:
        return ""
    k = len(macros)
    r = width + k + 2
    return rle_onehot_payload(macros, calls, width) + "<" + rle_onehot_executor(macros, width) + "<" * (r - 1)


def rle_numeric_payload(macros: Sequence[str], calls: Sequence[int], width: int) -> str:
    _verify(macros, calls, width)
    runs = compress_calls(
        calls, len(macros), width,
        cost_per_record=lambda symbol, count: (
            width + 6 + len(signed_initializer(symbol))
            + len(signed_initializer(count))
        ),
    )
    if not runs:
        return ""
    r = width + 5
    code = [">" * r]
    for symbol, count in reversed(runs):
        code += [">" * width, signed_initializer(symbol),
                 ">>>", signed_initializer(count), ">+>"]
    return "".join(code)


def rle_numeric_executor(macros: Sequence[str], width: int) -> str:
    _verify(macros, (), width)
    r = width + 5
    code = ["[", "-<<<<"]  # live -> numeric symbol Q
    for macro in macros:
        code += [">+<", "[->[-]>+<<]", ">>[-<<+>>]<<"]
        # Selected branch consumes C repeats, retaining logical state.
        code += [">[-<-", ">>>[", "<" * (width + 3), macro,
                 ">" * (width + 3), "-]", "<<<", ">]<", "-"]
    code += ["[-]<"]
    for j in range(width - 1, -1, -1):
        code += ["[-", "<" * r, "+", ">" * r, "]"]
        if j:
            code.append("<")
    code += ["<", "]"]
    return "".join(code)


def rle_numeric_program(macros: Sequence[str], calls: Sequence[int], width: int) -> str:
    _verify(macros, calls, width)
    if not calls:
        return ""
    r = width + 5
    return rle_numeric_payload(macros, calls, width) + "<" + rle_numeric_executor(macros, width) + "<" * (r - 1)


def normalize_dictionary(macros: Sequence[str], calls: Sequence[int], width: int, *, run_weighted: bool = False):
    """Dedup definitions and sort by call frequency or RLE record frequency."""
    for m in macros:
        check_window_macro(m, width)
    if any(not isinstance(i, int) or not 0 <= i < len(macros) for i in calls):
        raise ValueError("invalid call index")
    if not calls:
        return (), ()
    dedup, ids, mapped = [], {}, []
    for i in calls:
        body = macros[i]
        if body not in ids:
            ids[body] = len(dedup)
            dedup.append(body)
        mapped.append(ids[body])
    if run_weighted:
        # For a *fixed* run split, descending frequency minimizes numeric
        # opcode initializer cost. The split may change after renumbering.
        frequencies = Counter(i for i, count in compress_calls(mapped, len(dedup), width))
    else:
        frequencies = Counter(mapped)
    order = sorted(range(len(dedup)), key=lambda i: (-frequencies[i], i))
    remap = {i: j for j, i in enumerate(order)}
    return tuple(dedup[i] for i in order), tuple(remap[i] for i in mapped)


@dataclass(frozen=True)
class PortfolioResult:
    selected_family: str
    baseline_chars: int
    selected_chars: int
    candidates: tuple[tuple[str, int], ...]
    original_dictionary_size: int
    distinct_used_macros: int
    calls: int
    run_records: int


def choose_shortest(macros: Sequence[str], calls: Sequence[int], width: int):
    """Measure complete BF source length for each valid candidate."""
    literal = literal_program(macros, calls)
    candidates = {"literal": literal}
    if calls:
        for mode in (False, True):
            bodies, remapped = normalize_dictionary(macros, calls, width, run_weighted=mode)
            suffix = "_record_freq" if mode else "_call_freq"
            if not mode:
                candidates["onehot" + suffix] = onehot_program(bodies, remapped, width)
                if len(bodies) <= 128:
                    candidates["numeric" + suffix] = numeric_program(bodies, remapped, width)
            candidates["rle_onehot" + suffix] = rle_onehot_program(bodies, remapped, width)
            if len(bodies) <= 128:
                candidates["rle_numeric" + suffix] = rle_numeric_program(bodies, remapped, width)
    best = min(candidates, key=lambda key: (len(candidates[key]), key))
    dedup, remapped = normalize_dictionary(macros, calls, width)
    return candidates[best], PortfolioResult(
        best, len(literal), len(candidates[best]),
        tuple(sorted((name, len(src)) for name, src in candidates.items())),
        len(macros), len(dedup), len(calls),
        len(compress_calls(remapped, len(dedup), width)) if calls else 0,
    )
