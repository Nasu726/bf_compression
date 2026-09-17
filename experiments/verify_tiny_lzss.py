from __future__ import annotations

import random

from profile_tiny_lzss import (
    tiny_lzss_decode,
    tiny_lzss_encode,
    tiny_lzss_ext_decode,
    tiny_lzss_ext_encode,
)


def main() -> None:
    rng = random.Random(20260918)
    cases = [
        b"",
        b"a",
        b"abc",
        b"a" * 10000,
        b"abc" * 5000,
        bytes(range(256)) * 40,
        (b"0123456789abcdef" * 2000) + b"tail",
    ]
    for n in (1, 2, 3, 17, 18, 19, 255, 273, 274, 4095, 4096, 4097, 10000):
        cases.append(bytes(rng.randrange(256) for _ in range(n)))
    for blob in cases:
        for enc_fn, dec_fn in (
            (tiny_lzss_encode, tiny_lzss_decode),
            (tiny_lzss_ext_encode, tiny_lzss_ext_decode),
        ):
            enc = enc_fn(blob)
            dec = dec_fn(enc)
            assert dec == blob, (enc_fn.__name__, len(blob), len(enc))
    print("tiny LZSS verification: fixed18/ext273 ok")


if __name__ == "__main__":
    main()
