from __future__ import annotations

"""Compact signed-decimal output for the experimental HexLane scalar ABI.

The current generic Quad printer builds fixed Boolean/decimal workspaces and is
one of the largest source emitters in the compiler.  This prototype instead
copies the sixteen radix-16 nibbles into a *temporary dense division chain* and
performs twenty carried divide-by-ten rounds.  Each round occupies only 25 tape
cells, versus the 66-cell runtime record reused by the specialized partition
printer.

Persistent HexLane input is preserved.  The temporary chain is destructive and
private to printing.  Runtime is intentionally secondary to emitted standard-BF
source length.
"""

from functools import lru_cache

from hexlane_scalar_core import DIGITS, HexLaneI64Ref, _RelativeBuilder

RECORD_STRIDE = 25
MARKER = 0
BACK = 1
WORD = 2
REM = 18
COMBINED = 19
QUOT = 20
COUNTDOWN = 21
ZERO = 22
TMP = 23
RESTORE = 24

# Reverse-print aliases after division scratch becomes dead.
STARTED = COMBINED
ASCII = QUOT
GATE = COUNTDOWN

DECIMAL_DIGITS = 20


def _copy_preserved(r: _RelativeBuilder, src: int, dst: int, tmp: int) -> None:
    r.clear(dst)
    r.clear(tmp)
    r.move(src)
    r.emit("[")
    r.add(src, -1)
    r.add(dst, 1)
    r.add(tmp, 1)
    r.move(src)
    r.emit("]")
    r.move(tmp)
    r.emit("[")
    r.add(tmp, -1)
    r.add(src, 1)
    r.move(tmp)
    r.emit("]")


def _flag_zero(r: _RelativeBuilder, result: int, src: int, tmp: int, restore: int) -> None:
    r.clear(result)
    r.add(result, 1)
    _copy_preserved(r, src, tmp, restore)
    r.move(tmp)
    r.emit("[")
    r.clear(tmp)
    r.clear(result)
    r.move(tmp)
    r.emit("]")


def _nibble_ge8(r: _RelativeBuilder, result: int, src: int, tmp: int, restore: int) -> None:
    r.clear(result)
    _copy_preserved(r, src, tmp, restore)
    for step in range(1, 9):
        r.move(tmp)
        r.emit("[")
        r.add(tmp, -1)
        if step == 8:
            r.add(result, 1)
            r.clear(tmp)
    for _ in range(8):
        r.move(tmp)
        r.emit("]")


def _map_total_base16_threshold(r: _RelativeBuilder, total: int, out: int, carry: int) -> None:
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


def _negate_dense_word(r: _RelativeBuilder) -> None:
    carry = COMBINED
    total = QUOT
    r.clear(carry)
    r.add(carry, 1)
    for i in range(DIGITS):
        cell = WORD + i
        r.clear(total)
        r.add(total, 15)
        r.move(cell)
        r.emit("[")
        r.add(cell, -1)
        r.add(total, -1)
        r.move(cell)
        r.emit("]")
        r.transfer(carry, total)
        _map_total_base16_threshold(r, total, cell, carry)
    r.clear(carry)
    r.clear(total)


def _copy_hexlane_to_dense(bf, src: HexLaneI64Ref, base: int) -> None:
    # Source and first print record are both compile-time addressed.  Only this
    # boundary is unrolled; all 20 division rounds share one runtime body.
    tmp = base + TMP
    for i in range(DIGITS):
        dst = base + WORD + i
        bf.clear(dst)
        bf.clear(tmp)
        cell = src.value(i)
        bf.begin_while(cell)
        bf.add_const(cell, -1)
        bf.add_const(dst, 1)
        bf.add_const(tmp, 1)
        bf.end_while(cell)
        bf.begin_while(tmp)
        bf.add_const(tmp, -1)
        bf.add_const(cell, 1)
        bf.end_while(tmp)


@lru_cache(maxsize=1)
def _signed_prefix_body() -> str:
    r = _RelativeBuilder()
    sign = REM
    ascii_cell = COUNTDOWN
    _nibble_ge8(r, sign, WORD + DIGITS - 1, TMP, RESTORE)
    r.move(sign)
    r.emit("[")
    r.add(sign, -1)
    r.clear(ascii_cell)
    r.add(ascii_cell, ord("-"))
    r.move(ascii_cell)
    r.emit(".")
    _negate_dense_word(r)
    r.move(sign)
    r.emit("]")
    for cell in (sign, ascii_cell, TMP, RESTORE, COMBINED, QUOT):
        r.clear(cell)
    r.move(MARKER)
    return r.code()


@lru_cache(maxsize=1)
def _div10_body() -> str:
    r = _RelativeBuilder()
    r.add(MARKER, -1)
    r.clear(REM)

    for i in range(DIGITS - 1, -1, -1):
        src = WORD + i
        dst = RECORD_STRIDE + WORD + i
        r.clear(COMBINED)
        r.clear(QUOT)
        r.clear(COUNTDOWN)
        r.add(COUNTDOWN, 10)

        # combined = previous remainder * 16 + current nibble.
        r.transfer(src, COMBINED)
        r.move(REM)
        r.emit("[")
        r.add(REM, -1)
        r.add(COMBINED, 16)
        r.move(REM)
        r.emit("]")

        # Bounded 0..159 divmod 10. Runtime-heavy but source-compact.
        r.move(COMBINED)
        r.emit("[")
        r.add(COMBINED, -1)
        r.add(REM, 1)
        r.add(COUNTDOWN, -1)
        _flag_zero(r, ZERO, COUNTDOWN, TMP, RESTORE)
        r.move(ZERO)
        r.emit("[")
        r.add(ZERO, -1)
        r.add(QUOT, 1)
        r.clear(REM)
        r.clear(COUNTDOWN)
        r.add(COUNTDOWN, 10)
        r.move(ZERO)
        r.emit("]")
        r.move(COMBINED)
        r.emit("]")

        r.clear(dst)
        r.transfer(QUOT, dst)
        for scratch in (COUNTDOWN, ZERO, TMP, RESTORE):
            r.clear(scratch)

    r.clear(RECORD_STRIDE + BACK)
    r.add(RECORD_STRIDE + BACK, 1)
    r.clear(RECORD_STRIDE + MARKER)
    r.transfer(MARKER, RECORD_STRIDE + MARKER)
    r.move(RECORD_STRIDE + MARKER)
    return r.code()


@lru_cache(maxsize=1)
def _reverse_print_body() -> str:
    r = _RelativeBuilder()
    r.pos = BACK

    prev_started = STARTED - RECORD_STRIDE
    prev_ascii = ASCII - RECORD_STRIDE
    prev_digit = REM - RECORD_STRIDE
    prev_gate = GATE - RECORD_STRIDE
    prev_tmp = TMP - RECORD_STRIDE
    prev_restore = RESTORE - RECORD_STRIDE
    prev_back = BACK - RECORD_STRIDE

    r.clear(prev_started)
    r.transfer(STARTED, prev_started)
    r.clear(prev_ascii)
    r.add(prev_ascii, ord("0"))

    r.move(prev_digit)
    r.emit("[")
    r.add(prev_digit, -1)
    r.add(prev_ascii, 1)
    r.clear(prev_started)
    r.add(prev_started, 1)
    r.move(prev_digit)
    r.emit("]")

    # BACK is zero only for record zero, which must print one digit even when
    # every remainder was zero.
    _flag_zero(r, prev_gate, prev_back, prev_tmp, prev_restore)
    r.move(prev_gate)
    r.emit("[")
    r.add(prev_gate, -1)
    r.clear(prev_started)
    r.add(prev_started, 1)
    r.move(prev_gate)
    r.emit("]")

    _copy_preserved(r, prev_started, prev_gate, prev_tmp)
    r.move(prev_gate)
    r.emit("[")
    r.add(prev_gate, -1)
    r.move(prev_ascii)
    r.emit(".")
    r.move(prev_gate)
    r.emit("]")

    r.clear(prev_tmp)
    r.clear(prev_restore)
    r.move(prev_back)
    return r.code()


def print_hexlane_s64_compact(bf, src: HexLaneI64Ref, workspace_base: int) -> None:
    """Print one signed HexLane int64, preserving ``src`` and no trailing LF."""
    if workspace_base <= src.base + src.cells:
        raise ValueError("print workspace must be placed after the source word")

    _copy_hexlane_to_dense(bf, src, workspace_base)

    bf.move(workspace_base + MARKER)
    bf.emit(_signed_prefix_body())
    bf.ptr = workspace_base + MARKER

    bf.set_const(workspace_base + MARKER, DECIMAL_DIGITS)
    bf.move(workspace_base + MARKER)
    bf.emit("[" + _div10_body() + "]")
    bf.ptr = workspace_base + DECIMAL_DIGITS * RECORD_STRIDE + MARKER

    # Record 20 starts with zero BACK. STARTED is the reverse state carried left.
    bf.clear(workspace_base + DECIMAL_DIGITS * RECORD_STRIDE + STARTED)
    bf.move(workspace_base + DECIMAL_DIGITS * RECORD_STRIDE + BACK)
    bf.emit("[" + _reverse_print_body() + "]")
    bf.ptr = workspace_base + BACK
    bf.move(workspace_base)


__all__ = ["RECORD_STRIDE", "print_hexlane_s64_compact"]
