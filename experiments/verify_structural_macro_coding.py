from __future__ import annotations

"""Verify reversible start-stream coding used by structural macro serialization."""

from collections import defaultdict
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_relational_macro_grammar import Occ, enc_signed
from profile_semantic_vm import encode_uleb


def read_uleb(data, pos):
    value = 0
    shift = 0
    while True:
        b = data[pos]
        pos += 1
        value |= (b & 127) << shift
        if not (b & 128):
            return value, pos
        shift += 7


def read_signed(data, pos):
    value, pos = read_uleb(data, pos)
    return (value >> 1) ^ -(value & 1), pos


def encode_start(seq, *, context_args, delta_symbols):
    out = bytearray()
    prev_args = defaultdict(int)
    prev_symbol = 0
    for occ in seq:
        if delta_symbols:
            out += enc_signed(occ.symbol - prev_symbol)
            prev_symbol = occ.symbol
        else:
            out += encode_uleb(occ.symbol)
        for slot, value in enumerate(occ.args):
            if context_args:
                key = (occ.symbol, slot)
                out += enc_signed(value - prev_args[key])
                prev_args[key] = value
            else:
                out += enc_signed(value)
    return bytes(out)


def decode_start(data, arities, count, *, context_args, delta_symbols):
    out = []
    pos = 0
    prev_args = defaultdict(int)
    prev_symbol = 0
    for _ in range(count):
        raw, pos = read_signed(data, pos) if delta_symbols else read_uleb(data, pos)
        symbol = prev_symbol + raw if delta_symbols else raw
        if delta_symbols:
            prev_symbol = symbol
        args = []
        for slot in range(arities[symbol]):
            raw, pos = read_signed(data, pos)
            if context_args:
                key = (symbol, slot)
                value = prev_args[key] + raw
                prev_args[key] = value
            else:
                value = raw
            args.append(value)
        out.append(Occ(symbol, tuple(args)))
    assert pos == len(data)
    return out


def main():
    rng = random.Random(20260918)
    arities = [0, 1, 2, 4]
    seq = []
    state = {(s, k): 0 for s, a in enumerate(arities) for k in range(a)}
    for _ in range(500):
        symbol = rng.randrange(len(arities))
        args = []
        for slot in range(arities[symbol]):
            state[(symbol, slot)] += rng.randint(-9, 9)
            args.append(state[(symbol, slot)])
        seq.append(Occ(symbol, tuple(args)))
    for context in (False, True):
        for delta_symbols in (False, True):
            data = encode_start(seq, context_args=context, delta_symbols=delta_symbols)
            assert decode_start(data, arities, len(seq), context_args=context, delta_symbols=delta_symbols) == seq
    print("structural macro start coding: ok")


if __name__ == "__main__":
    main()
