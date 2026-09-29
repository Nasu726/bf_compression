from __future__ import annotations

"""Compare payload encodings using actual BF constructor/decoder source costs.

The grammar profilers historically ranked channels by constructor length only.
That is appropriate for information-headroom work, but not for a self-contained
compressed BF program: a denser bit channel can lose once its decoder is added.

This profiler reuses the relational + periodic-call grammar and compares:

* direct-byte: fully realized constructor; no channel decoder;
* prefix16: dense constructor; BF bitstream decoder still unimplemented;
* balanced-nibble: fully realized constructor + 58-char moving decoder;
* tiny-LZSS variants of the above: constructor/channel costs are measured, but
  an LZSS decoder is still an explicit outstanding cost.

The output deliberately labels unrealized decoder obligations instead of
pretending their cost is zero.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_bf_native_channel import direct_byte_loader_chars, loader_source_for_bytes
from profile_periodic_call_runs import serialize_with_patterns
from profile_relational_macro_grammar import build_grammar
from profile_semantic_vm import semantic_tokens
from profile_tiny_lzss import tiny_lzss_ext_decode, tiny_lzss_ext_encode
from region_zero_opt import canonicalize, parse, precanonicalize, strip_bf
from self_extracting_balanced_nibble_channel import total_channel_chars


def channel_row(payload: bytes) -> dict[str, int]:
    ext = tiny_lzss_ext_encode(payload)
    assert tiny_lzss_ext_decode(ext) == payload
    return {
        "payload_bytes": len(payload),
        "direct_byte_chars": direct_byte_loader_chars(payload),
        "prefix16_constructor_chars": len(loader_source_for_bytes(payload)[0]),
        "balanced_nibble_total_chars": total_channel_chars(payload),
        "ext_lzss_bytes": len(ext),
        "ext_direct_byte_chars": direct_byte_loader_chars(ext),
        "ext_prefix16_constructor_chars": len(loader_source_for_bytes(ext)[0]),
        "ext_balanced_nibble_channel_chars": total_channel_chars(ext),
    }


def profile_text(text: str, max_period: int = 8) -> dict[str, object]:
    raw = strip_bf(text)
    nodes = canonicalize(parse(precanonicalize(raw)))
    tokens = semantic_tokens(nodes, Counter())
    sweep = []
    for limit in (0, 16, 32, 64, 128):
        terminals, arities, rules, seq, _ = build_grammar(tokens, limit)
        payload, runs, patterns, covered = serialize_with_patterns(
            terminals, rules, seq, max_period
        )
        row = {
            "max_rules": limit,
            "affine_run_records": runs,
            "pattern_run_records": patterns,
            "run_covered_calls": covered,
            **channel_row(payload),
        }
        sweep.append(row)

    selectors = {
        # Fully realized at the channel layer.  The grammar VM remains extra.
        "direct_byte": min(sweep, key=lambda r: int(r["direct_byte_chars"])),
        "balanced_nibble": min(sweep, key=lambda r: int(r["balanced_nibble_total_chars"])),
        # These retain explicit decoder obligations.
        "prefix16_constructor_only": min(sweep, key=lambda r: int(r["prefix16_constructor_chars"])),
        "ext_lzss_prefix16_constructor_only": min(sweep, key=lambda r: int(r["ext_prefix16_constructor_chars"])),
        "ext_lzss_balanced_channel_only": min(sweep, key=lambda r: int(r["ext_balanced_nibble_channel_chars"])),
    }
    return {
        "bf_bytes": len(raw),
        "semantic_tokens": len(tokens),
        "sweep": sweep,
        "best": selectors,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--max-period", type=int, default=8)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows = []
    for name in args.files:
        p = Path(name)
        rows.append({
            "name": str(p),
            **profile_text(p.read_text(encoding="ascii", errors="ignore"), args.max_period),
        })

    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
        return

    total = sum(int(r["bf_bytes"]) for r in rows)
    target = total // 10
    direct = sum(int(r["best"]["direct_byte"]["direct_byte_chars"]) for r in rows)
    balanced = sum(int(r["best"]["balanced_nibble"]["balanced_nibble_total_chars"]) for r in rows)
    prefix = sum(int(r["best"]["prefix16_constructor_only"]["prefix16_constructor_chars"]) for r in rows)
    ext_prefix = sum(int(r["best"]["ext_lzss_prefix16_constructor_only"]["ext_prefix16_constructor_chars"]) for r in rows)
    ext_balanced = sum(int(r["best"]["ext_lzss_balanced_channel_only"]["ext_balanced_nibble_channel_chars"]) for r in rows)
    print(f"original={total:,} target10x={target:,}")
    print(f"direct_byte_realized_channel={direct:,} budget={target-direct:,}")
    print(f"balanced_nibble_realized_channel={balanced:,} budget={target-balanced:,}")
    print(f"prefix16_constructor_only={prefix:,} unresolved=prefix_decoder")
    print(f"ext_lzss_prefix16_constructor_only={ext_prefix:,} unresolved=prefix_decoder+lzss_decoder")
    print(f"ext_lzss_balanced_channel={ext_balanced:,} unresolved=lzss_decoder")
    for row in rows:
        b = row["best"]
        print(
            f"{row['name']}: direct={b['direct_byte']['direct_byte_chars']:,}; "
            f"balanced={b['balanced_nibble']['balanced_nibble_total_chars']:,}; "
            f"prefix={b['prefix16_constructor_only']['prefix16_constructor_chars']:,}; "
            f"ext+balanced={b['ext_lzss_balanced_channel_only']['ext_balanced_nibble_channel_chars']:,}"
        )


if __name__ == "__main__":
    main()
