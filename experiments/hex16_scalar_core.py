from __future__ import annotations

"""Experimental dense radix-16 int64 scalar core for source-size research.

A word is sixteen little-endian nibble cells (0..15), with no per-digit marker.
Operations are Python-unrolled over the fixed sixteen digits. Runtime speed is
not the objective; emitted standard-BF source length and physical tape width are.

This deliberately small core supports the operations needed for the first
representation comparison: set/copy/add/sub/unsigned >=. Inputs are preserved
and arithmetic is modulo 2**64. The three-word arithmetic operations currently
require distinct word bases.
"""

from dataclasses import dataclass

MASK64 = (1 << 64) - 1
DIGITS = 16
WORD_CELLS = DIGITS


@dataclass(frozen=True)
class Hex16I64Ref:
    base: int

    def digit(self, index: int) -> int:
        if not 0 <= index < DIGITS:
            raise IndexError(index)
        return self.base + index

    @property
    def cells(self) -> int:
        return WORD_CELLS


def _copy_preserved(bf, src: int, dst: int, tmp: int) -> None:
    bf.clear(dst)
    bf.clear(tmp)
    bf.begin_while(src)
    bf.add_const(src, -1)
    bf.add_const(dst, 1)
    bf.add_const(tmp, 1)
    bf.end_while(src)
    bf.begin_while(tmp)
    bf.add_const(tmp, -1)
    bf.add_const(src, 1)
    bf.end_while(tmp)


def _add_preserved(bf, src: int, total: int, tmp: int) -> None:
    bf.clear(tmp)
    bf.begin_while(src)
    bf.add_const(src, -1)
    bf.add_const(total, 1)
    bf.add_const(tmp, 1)
    bf.end_while(src)
    bf.begin_while(tmp)
    bf.add_const(tmp, -1)
    bf.add_const(src, 1)
    bf.end_while(tmp)


def _add_complement_preserved(bf, src: int, total: int, tmp: int) -> None:
    """total += 15-src while preserving one nibble source."""
    bf.add_const(total, 15)
    bf.clear(tmp)
    bf.begin_while(src)
    bf.add_const(src, -1)
    bf.add_const(total, -1)
    bf.add_const(tmp, 1)
    bf.end_while(src)
    bf.begin_while(tmp)
    bf.add_const(tmp, -1)
    bf.add_const(src, 1)
    bf.end_while(tmp)


def _map_total_base16(bf, total: int, out: int, carry: int) -> None:
    """Consume total in 0..31 into out=total%16 and carry=floor(total/16)."""
    bf.clear(out)
    bf.clear(carry)
    # Fixed nested source: only the first `original total` levels execute.
    for step in range(1, 32):
        bf.begin_while(total)
        bf.add_const(total, -1)
        if step == 16:
            bf.clear(out)
            bf.add_const(carry, 1)
        else:
            bf.add_const(out, 1)
    for _ in range(31):
        bf.end_while(total)


class Hex16I64Core:
    SCRATCH_CELLS = 4

    def __init__(self, bf, scratch_base: int) -> None:
        self.bf = bf
        self.total = scratch_base
        self.tmp = scratch_base + 1
        self.carry = scratch_base + 2
        self.next_carry = scratch_base + 3

    def _clear_scratch(self) -> None:
        for cell in (self.total, self.tmp, self.carry, self.next_carry):
            self.bf.clear(cell)

    def set_u64(self, dst: Hex16I64Ref, value: int) -> None:
        """Set one dense word without touching unrelated shared scratch."""
        value &= MASK64
        for i in range(DIGITS):
            self.bf.set_const(dst.digit(i), (value >> (4 * i)) & 0xF)

    def copy64(self, dst: Hex16I64Ref, src: Hex16I64Ref) -> None:
        if dst.base == src.base:
            return
        for i in range(DIGITS):
            _copy_preserved(self.bf, src.digit(i), dst.digit(i), self.tmp)
        self._clear_scratch()

    def add64(self, dst: Hex16I64Ref, a: Hex16I64Ref, b: Hex16I64Ref) -> None:
        if len({dst.base, a.base, b.base}) != 3:
            raise ValueError("hex16 add64 requires distinct operands")
        bf = self.bf
        self._clear_scratch()
        for i in range(DIGITS):
            bf.clear(self.total)
            bf.clear(self.next_carry)
            bf.begin_while(self.carry)
            bf.add_const(self.carry, -1)
            bf.add_const(self.total, 1)
            bf.end_while(self.carry)
            _add_preserved(bf, a.digit(i), self.total, self.tmp)
            _add_preserved(bf, b.digit(i), self.total, self.tmp)
            _map_total_base16(bf, self.total, dst.digit(i), self.next_carry)
            bf.begin_while(self.next_carry)
            bf.add_const(self.next_carry, -1)
            bf.add_const(self.carry, 1)
            bf.end_while(self.next_carry)
        self._clear_scratch()

    def _sub_with_carry(
        self,
        dst: Hex16I64Ref,
        a: Hex16I64Ref,
        b: Hex16I64Ref,
    ) -> None:
        if len({dst.base, a.base, b.base}) != 3:
            raise ValueError("hex16 sub64 requires distinct operands")
        bf = self.bf
        self._clear_scratch()
        bf.set_const(self.carry, 1)
        for i in range(DIGITS):
            bf.clear(self.total)
            bf.clear(self.next_carry)
            bf.begin_while(self.carry)
            bf.add_const(self.carry, -1)
            bf.add_const(self.total, 1)
            bf.end_while(self.carry)
            _add_preserved(bf, a.digit(i), self.total, self.tmp)
            _add_complement_preserved(bf, b.digit(i), self.total, self.tmp)
            _map_total_base16(bf, self.total, dst.digit(i), self.next_carry)
            bf.begin_while(self.next_carry)
            bf.add_const(self.next_carry, -1)
            bf.add_const(self.carry, 1)
            bf.end_while(self.next_carry)
        # carry is the final radix-complement carry (1 iff unsigned a >= b).

    def sub64(self, dst: Hex16I64Ref, a: Hex16I64Ref, b: Hex16I64Ref) -> None:
        self._sub_with_carry(dst, a, b)
        self._clear_scratch()

    def uge64(
        self,
        result: int,
        a: Hex16I64Ref,
        b: Hex16I64Ref,
        tmp_word: Hex16I64Ref,
    ) -> None:
        if result in range(tmp_word.base, tmp_word.base + tmp_word.cells):
            raise ValueError("result must not alias compare temporary")
        self._sub_with_carry(tmp_word, a, b)
        bf = self.bf
        bf.clear(result)
        bf.begin_while(self.carry)
        bf.add_const(self.carry, -1)
        bf.add_const(result, 1)
        bf.end_while(self.carry)
        self._clear_scratch()


__all__ = ["DIGITS", "WORD_CELLS", "MASK64", "Hex16I64Ref", "Hex16I64Core"]
