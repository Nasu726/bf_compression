from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from region_zero_opt import optimize_region_zero, strip_bf


@dataclass(frozen=True)
class Result:
    terminated: bool
    ptr: int
    tape: tuple[tuple[int, int], ...]
    output: bytes
    input_pos: int


def run(code: str, data: bytes = b"", *, eof: str = "nochange", limit: int = 2_000_000) -> Result:
    code = strip_bf(code)
    stack: list[int] = []
    jump: dict[int, int] = {}
    for i, ch in enumerate(code):
        if ch == "[":
            stack.append(i)
        elif ch == "]":
            if not stack:
                raise ValueError("unmatched ]")
            j = stack.pop()
            jump[i] = j
            jump[j] = i
    if stack:
        raise ValueError("unmatched [")

    mem: dict[int, int] = {}
    ptr = pc = inp = steps = 0
    out = bytearray()

    def get() -> int:
        return mem.get(ptr, 0)

    def setv(v: int) -> None:
        v &= 255
        if v:
            mem[ptr] = v
        else:
            mem.pop(ptr, None)

    while pc < len(code) and steps < limit:
        steps += 1
        ch = code[pc]
        if ch == ">":
            ptr += 1
        elif ch == "<":
            ptr -= 1
            if ptr < 0:
                raise RuntimeError("left boundary")
        elif ch == "+":
            setv(get() + 1)
        elif ch == "-":
            setv(get() - 1)
        elif ch == ".":
            out.append(get())
        elif ch == ",":
            if inp < len(data):
                setv(data[inp]); inp += 1
            elif eof == "255":
                setv(255)
            elif eof == "0":
                setv(0)
            elif eof != "nochange":
                raise ValueError(eof)
        elif ch == "[" and get() == 0:
            pc = jump[pc]
        elif ch == "]" and get() != 0:
            pc = jump[pc]
        pc += 1

    return Result(
        terminated=pc >= len(code),
        ptr=ptr,
        tape=tuple(sorted(mem.items())),
        output=bytes(out),
        input_pos=inp,
    )


def same(code: str, inputs=(b"", b"A")) -> None:
    opt = optimize_region_zero(code)
    assert len(opt) <= len(strip_bf(code)), (code, opt)
    for eof in ("nochange", "255", "0"):
        for data in inputs:
            a = run(code, data, eof=eof)
            b = run(opt, data, eof=eof)
            assert a == b, (code, opt, eof, data, a, b)


def main() -> None:
    # Top-level zero initialization and ordinary balanced-loop facts.
    same("[-]")
    same("+[-][-]")
    same(">[-]<")
    same("+++[+][-]")

    # Recursive dataflow matters even when the whole program is balanced.
    # The first inner clear proves the second inner clear unreachable/no-op on
    # every executed outer iteration. The legacy optimizer only propagates at
    # top level, so this is the smallest representative of that missed class.
    nested = "+[[-][-]]"
    assert optimize_region_zero(nested) == "+[[-]]"
    same(nested)

    # A moving loop is a local address barrier, but on every terminating path
    # its exit cell is known zero. The following clear is therefore redundant.
    for n in range(1, 8):
        for stride in range(1, 5):
            same("+" * n + "[" + ">" * stride + "][-]")

    # The same exit-zero fact holds even when the loop may be skipped because
    # an input-dependent control value happens to be zero.
    same(",+[>][-]", inputs=(b"", b"\x00", b"A", b"\xff"))

    # A write after the barrier invalidates the zero fact, so the clear stays.
    code = "+[>]+[-]"
    opt = optimize_region_zero(code)
    assert opt.endswith("+[-]"), (code, opt)
    same(code)

    # Input is deliberately conservative. In particular, the leading '-' in
    # the classic '-,+': EOF normalization pattern must survive no-change EOF.
    assert optimize_region_zero("-,+") == "-,+"
    same("-,+", inputs=(b"", b"A"))

    # Body-local redundancy is safe even for a moving outer loop because each
    # executed iteration establishes the fact before it is consumed.
    same("+[[ - ][-]>]".replace(" ", ""))

    print("region-zero differential checks: OK")


if __name__ == "__main__":
    main()
