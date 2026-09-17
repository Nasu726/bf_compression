from __future__ import annotations

import random

from profile_tiny_lzss import tiny_lzss_decode, tiny_lzss_encode


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
    for n in (1, 2, 3, 17, 18, 19, 255, 4095, 4096, 4097, 10000):
        cases.append(bytes(rng.randrange(256) for _ in range(n)))
    for blob in cases:
        enc = tiny_lzss_encode(blob)
        dec = tiny_lzss_decode(enc)
        assert dec == blob, (len(blob), len(enc))
    print("tiny LZSS verification: ok")


if __name__ == "__main__":
    main()
