from __future__ import annotations

"""Runtime-walkable radix-16 int64 representation for 10x source research.

Persistent layout::

    [marker, nibble] * 16 + [sentinel_marker, sentinel_value]

This is the midpoint between the current 99-cell Quad64 layout and the failed
plain 16-cell Hex16 experiment.  A logical int64 occupies 34 cells, but hot
operations emit one fixed lane body and execute it sixteen times at runtime.
The per-lane marker is transient traversal metadata and is zero outside an
operation.

Arithmetic is modulo 2**64.  Value nibbles are preserved for input operands.
The first prototype supports set/copy/add/sub/unsigned >= and requires distinct
three-word operands for add/sub, matching the scope of the representation
microbenchmark.
"""

from dataclasses import dataclass

MASK64 = (1 << 64) - 1
DIGITS = 16
STRIDE = 2
WORD_CELLS = (DIGITS + 1) * STRIDE


@dataclass(frozen=True)
class HexLaneI64Ref:
    base: int

    def marker(self, digit: int) -> int:
        if not 0 <= digit <= DIGITS:
            raise IndexError(digit)
        return self.base + STRIDE * digit

    def value(self, digit: int) -> int:
        if not 0 <= digit <= DIGITS:
            raise IndexError(digit)
        return self.base + STRIDE * digit + 1

    @property
    def cells(self) -> int:
        return WORD_CELLS


class _RelativeBuilder:
    def __init__(self) -> None:
        self.pos = 0
        self.parts: list[str] = []

    def move(self, target: int) -> None:
        delta = target - self.pos
        if delta > 0:
            self.parts.append(">" * delta)
        elif delta < 0:
            self.parts.append("<" * -delta)
        self.pos = target

    def emit(self, code: str) -> None:
        self.parts.append(code)

    def add(self, target: int, amount: int) -> None:
        self.move(target)
        amount %= 256
        if amount <= 128:
            self.parts.append("+" * amount)
        else:
            self.parts.append("-" * (256 - amount))

    def clear(self, target: int) -> None:
        self.move(target)
        self.emit("[-]")

    def transfer(self, src: int, dst: int) -> None:
        self.move(src)
        self.emit("[")
        self.add(src, -1)
        self.add(dst, 1)
        self.move(src)
        self.emit("]")

    def code(self) -> str:
        return "".join(self.parts)


def _add_preserved(r: _RelativeBuilder, src: int, total: int, tmp: int) -> None:
    """Add one 0..15 nibble into total while preserving the source."""
    r.move(src)
    r.emit("[")
    r.add(src, -1)
    r.add(total, 1)
    r.add(tmp, 1)
    r.move(src)
    r.emit("]")
    r.move(tmp)
    r.emit("[")
    r.add(tmp, -1)
    r.add(src, 1)
    r.move(tmp)
    r.emit("]")


def _add_complement_preserved(
    r: _RelativeBuilder,
    src: int,
    total: int,
    tmp: int,
) -> None:
    """Add radix complement ``15-src`` while preserving one nibble."""
    r.add(total, 15)
    r.move(src)
    r.emit("[")
    r.add(src, -1)
    r.add(total, -1)
    r.add(tmp, 1)
    r.move(src)
    r.emit("]")
    r.move(tmp)
    r.emit("[")
    r.add(tmp, -1)
    r.add(src, 1)
    r.move(tmp)
    r.emit("]")


def _map_total_base16_threshold(
    r: _RelativeBuilder,
    total: int,
    out: int,
    carry: int,
) -> None:
    """Consume total in 0..31 into low nibble + one-bit carry.

    Only sixteen guarded levels are emitted.  Once the sixteenth unit has been
    consumed, carry is known to be one and the residual total is already the
    low nibble (0..15), so it is transferred directly to ``out``.
    """
    r.clear(out)
    r.clear(carry)
    for step in range(1, 17):
        r.move(total)
        r.emit("[")
        r.add(total, -1)
        if step == 16:
            r.clear(out)
            r.add(carry, 1)
            r.transfer(total, out)
        else:
            r.add(out, 1)
    for _ in range(16):
        r.move(total)
        r.emit("]")


class HexLaneI64Core:
    """Fixed-body radix-16 arithmetic over marker+nibble lanes."""

    def __init__(self, bf) -> None:
        self.bf = bf

    def set_u64(self, dst: HexLaneI64Ref, value: int) -> None:
        value &= MASK64
        for digit in range(DIGITS):
            self.bf.clear(dst.marker(digit))
            self.bf.set_const(dst.value(digit), (value >> (4 * digit)) & 0xF)
        self.bf.clear(dst.marker(DIGITS))
        self.bf.clear(dst.value(DIGITS))

    def _arm(self, word: HexLaneI64Ref) -> None:
        for digit in range(DIGITS):
            self.bf.set_const(word.marker(digit), 1)
        self.bf.clear(word.marker(DIGITS))

    def copy64(self, dst: HexLaneI64Ref, src: HexLaneI64Ref) -> None:
        if dst.base == src.base:
            return
        bf = self.bf
        delta = dst.base - src.base
        self._arm(src)

        r = _RelativeBuilder()
        marker = 0
        src_value = 1
        dst_marker = delta
        dst_value = delta + 1

        r.clear(marker)
        r.clear(dst_marker)
        r.clear(dst_value)
        _add_preserved(r, src_value, dst_value, marker)
        r.move(STRIDE)

        bf.move(src.marker(0))
        bf.emit("[" + r.code() + "]")
        bf.ptr = src.marker(DIGITS)
        bf.clear(dst.marker(DIGITS))
        bf.clear(dst.value(DIGITS))

    def add64(
        self,
        dst: HexLaneI64Ref,
        a: HexLaneI64Ref,
        b: HexLaneI64Ref,
    ) -> None:
        if len({dst.base, a.base, b.base}) != 3:
            raise ValueError("hex-lane add64 requires distinct operands")

        bf = self.bf
        b_delta = b.base - a.base
        d_delta = dst.base - a.base
        self._arm(a)
        bf.clear(dst.marker(0))

        r = _RelativeBuilder()
        marker = 0
        a_value = 1
        total = b_delta
        b_value = b_delta + 1
        carry_in = d_delta
        out = d_delta + 1
        carry_out = d_delta + STRIDE

        # The B marker is lane-local total scratch.  The consumed A traversal
        # marker is restoration scratch for preserved nibble copies.
        r.clear(marker)
        r.clear(total)
        r.clear(out)
        r.clear(carry_out)
        r.transfer(carry_in, total)
        _add_preserved(r, a_value, total, marker)
        _add_preserved(r, b_value, total, marker)
        _map_total_base16_threshold(r, total, out, carry_out)
        r.move(STRIDE)

        bf.move(a.marker(0))
        bf.emit("[" + r.code() + "]")
        bf.ptr = a.marker(DIGITS)
        # Fixed-width overflow is discarded; all marker state returns to zero.
        bf.clear(dst.marker(DIGITS))
        bf.clear(dst.value(DIGITS))

    def _sub_with_carry(
        self,
        dst: HexLaneI64Ref,
        a: HexLaneI64Ref,
        b: HexLaneI64Ref,
    ) -> None:
        """Compute a-b and retain unsigned no-borrow in dst sentinel marker."""
        if len({dst.base, a.base, b.base}) != 3:
            raise ValueError("hex-lane sub64 requires distinct operands")

        bf = self.bf
        b_delta = b.base - a.base
        d_delta = dst.base - a.base
        self._arm(a)
        bf.set_const(dst.marker(0), 1)  # +1 for radix-complement subtraction

        r = _RelativeBuilder()
        marker = 0
        a_value = 1
        total = b_delta
        b_value = b_delta + 1
        carry_in = d_delta
        out = d_delta + 1
        carry_out = d_delta + STRIDE

        r.clear(marker)
        r.clear(total)
        r.clear(out)
        r.clear(carry_out)
        r.transfer(carry_in, total)
        _add_preserved(r, a_value, total, marker)
        _add_complement_preserved(r, b_value, total, marker)
        _map_total_base16_threshold(r, total, out, carry_out)
        r.move(STRIDE)

        bf.move(a.marker(0))
        bf.emit("[" + r.code() + "]")
        bf.ptr = a.marker(DIGITS)
        bf.clear(dst.value(DIGITS))

    def sub64(
        self,
        dst: HexLaneI64Ref,
        a: HexLaneI64Ref,
        b: HexLaneI64Ref,
    ) -> None:
        self._sub_with_carry(dst, a, b)
        self.bf.clear(dst.marker(DIGITS))

    def uge64(
        self,
        result: int,
        a: HexLaneI64Ref,
        b: HexLaneI64Ref,
        tmp: HexLaneI64Ref,
    ) -> None:
        if result in range(tmp.base, tmp.base + tmp.cells):
            raise ValueError("result must not alias comparison temporary")
        self._sub_with_carry(tmp, a, b)
        carry = tmp.marker(DIGITS)
        self.bf.clear(result)
        self.bf.move(carry)
        self.bf.emit("[-")
        self.bf.move(result)
        self.bf.emit("+")
        self.bf.move(carry)
        self.bf.emit("]")
        self.bf.clear(tmp.value(DIGITS))


__all__ = [
    "DIGITS",
    "STRIDE",
    "WORD_CELLS",
    "MASK64",
    "HexLaneI64Ref",
    "HexLaneI64Core",
]
