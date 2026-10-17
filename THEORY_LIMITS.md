# Source-Length Limits and Proof Obligations

This note separates **proved exact optima in restricted BF languages** from
*measured achievable constructions* and *nonconstructive information bounds*.
The objective is executable, self-contained standard Brainfuck source with
the eight instructions `><+-.,[]`; external compressed data files, extra
input, nonstandard macro syntaxes, and BF comments do not count as solutions.

## 1. Semantic contract

For a fixed, explicitly declared Brainfuck runtime model, a valid replacement
must preserve the complete intended observation, including:

* output bytes and their order;
* input consumption and behavior on every permitted input/EOF condition;
* termination versus divergence, not equal intermediate states after a
  fixed instruction budget;
* final pointer and all observable final tape bytes on termination;
* tape boundaries / cell wrapping behavior.

Programs are compared using the **same** runtime model. The EOF convention
must be settled before any pass assumes `,` overwrites a cell (issue #3).

The primary metric is **the complete generated BF source length**:

```
L_full = L_payload_constructor + L_decoder + L_VM + L_cleanup
```

This decomposition may share code between stages; do not double-count shared
code, and do not omit the runtime epilogue. Every test artifact is standalone:
a decoder shared as a *concept* must still be counted once in **each**
artifact's BF output. The benchmark's weighted total compression factor is

`R_weighted = sum(L_original_i) / sum(L_full_i)`.

A second, distribution-sensitive report should include individual ratios
`L_original_i/L_full_i` and the number of artifacts improved, so a large
example cannot hide regressions on smaller programs. The target `10x`
means the seven-artifact aggregate full source length is at most 206,632
characters relative to the pinned 2,066,322-character baseline.

## 2. Impossibility of a universal exact shortest-source algorithm

On the standard unbounded-tape computational model, BF is Turing complete.
The unrestricted semantic-equivalence problem is undecidable; a total,
computable algorithm that always returns a *globally shortest* equivalent BF
program for every source cannot exist.

One way to make the obstruction precise is through description complexity.
Fix a canonical observation consisting of a finite output string `x`,
termination, no consumed input, a zero final tape, and final pointer 0.
There is a computable mapping `x -> P_x` producing such an observation
(a literal emitter followed by cleanup). If a total global minimizer existed,
the minimum BF source length `h(x) = |minimize(P_x)|` would be computable.

However, only finitely many BF sources are shorter than an integer `k`,
whereas infinitely many finite strings exist. Hence we could algorithmically
find the first `x` with `h(x)>k`. A fixed BF program implementing that
algorithm given `k` would describe `x` in `O(log k)` program symbols,
including a fixed implementation and cleanup convention. For sufficiently
large `k`, this contradicts `h(x)>k`: a standard Berry-paradox /
Kolmogorov-complexity diagonal argument.

Consequences:
* no globally exact optimizer for arbitrary BF can be total and computable;
* a fixed 10x compression guarantee cannot hold on every semantic program;
* this does **not** preclude very large compression on structured,
  compiler-generated families or proving optimality in restricted classes;
* a bounded enumerative optimizer can prove shortestness **up to the
  explicitly explored source length/grammar**, not in general.

## 3. An exact one-cell output/state theorem

Implementation: `experiments/exact_one_cell_literal.py`.
Verifier: `experiments/verify_exact_one_cell_literal.py`.

The source fragment consists only of arithmetic `+`, `-`, output `.`
and `[-]` (the three-character clear), operates on a single initially-zero
8-bit cell, never reads input and never moves its pointer. The desired
observation is a fixed output sequence `b_1,...,b_m` and a final cell value
`f`. For known `s,t in Z/256Z`, define

```
d(s,t) = min((t-s) mod 256, (s-t) mod 256)
C(s,t) = min(d(s,t), 3+d(0,t)).
```

The optimal number of literal source characters in this language is

```
L* = m + C(0,b_1) + sum_{i=2..m} C(b_{i-1},b_i) + C(b_m,f)
```

with `b_m=0` if `m=0` (so the last term is `C(0,f)`).

**Proof.** Between consecutive outputs, any program without a clear
requires at least `d(s,t)` increments/decrements to reach `t`. If it
contains a clear, discard every command through its last clear: all
earlier arithmetic work was overwritten. The final clear costs at least
three source symbols, and creating `t` from zero costs at least
`d(0,t)`. Both lower bounds are realized. One `.` is required per
output event by this language. Each boundary value is fixed by the
observable trace, so these minimum segment costs add independently.
QED.

This is the exact optimum **within this language**. General BF with
extra scratch cells and other loop forms may be shorter.

## 4. An exact multicell straight-line theorem

Implementation: `experiments/exact_zero_tape_straight.py`.
Verifier: `experiments/verify_exact_zero_tape_straight.py`.

The fragment `+,-,<,>` starts with a zero tape and pointer 0, has
no I/O, no loops, and never crosses the left boundary. Let the final
pointer be `p>=0`, and let `v_i` be all final tape byte values
(finitely many nonzero). Set

```
R = max{i : v_i != 0}, default 0
T = max(R,p)
D(v) = min(v,256-v)

L* = sum_i D(v_i) + (2*T-p).
```

**Proof.** Each cell with final residue `v_i` independently requires
at least `D(v_i)` arithmetic commands. The pointer must reach
`T` from 0 and end at `p`, incurring at least `2*T-p` moves. A
single monotonically rightward pass writes each nonzero cell using the
shortest plus/minus residue, reaches `T`, and returns to `p`.
This meets both lower bounds simultaneously. QED.

It is an exact global optimum in this four-instruction fragment, not a
general optimal-BF claim. It can serve as a certified alternative for
zero-initialized straight-line *whole programs* and suitable proven-zero
regions, but must not be applied to regions with unknown entry state.

## 5. Source-alphabet information bounds are not executable codecs

BF has eight instruction symbols, so at most `8^L` syntactic strings
have exact source length `L` and the raw information ceiling is three
bits per literal BF instruction. This is a *counting upper bound*, not a
recipe for embedding arbitrary bits at three bits per BF command.

In particular, a BF program cannot simply read appended source text as
an ordinary input data file. Executable constructors/decoders must
generate and consume encoded data while preserving the semantic ABI.
The balanced-cell prefix-channel capacity computed in
`profile_bf_native_channel.py` applies only to its constrained
independent-fresh-zero-cell encoding model. It is **not** a universal
lower bound on the size of every possible self-extracting BF program.

## 6. Status of measured compression techniques

* Known-zero/dead-affine fixed-point: genuine executable BF,
  2,066,322 -> 1,942,406 chars, with differential tests.
* HexLane, fused balanced-nibble and fused octal: genuinely executable
  kernels but only under their declared ABI assumptions.
* Relational macro / periodic-pattern / LZSS profile: a compact encoded
  semantic-token payload with exact token-stream round-trip in its
  tested class. It does **not** yet include a complete general-purpose
  BF grammar decoder, pointer-moving tape interpreter, and cleanup.
* Lower bounds for fixed static epoch relayout are bounds for the
  restricted relayout model; they do not exclude changing the
  representation, doing a semantic resynthesis, or using a VM.

Avoid presenting the ~82k payload-loader number as a measured complete
10x executable BF program. The remaining runtime and cleanup need both
implementation and full-state differential verification.

## 7. Research direction

1. Run the two new **provably optimal** fragments as competing baselines,
   not only against raw sources. Prefer exact semantic normalization when
   it dominates a data-driven VM.
2. In regions with persistent unknown state, use certified dataflow
   preconditions rather than the zero-initialized theorems above.
3. Build a real grammar-threaded executor with complete source accounting
   and an explicit memory/EOF ABI. Start with one restricted command
   family, then add pointer motion, loops, I/O and affine calls.
4. Use a *costed portfolio*: zero-fragment exact optimizer; known-zero/
   dead-affine; specialized lane-reroll; relational grammar + LZSS/VM;
   untouched original. Measure the actual runnable source after every
   candidate, including any decoder/epilogue. Pick the shortest valid one.
5. Move only source-size improvements supported by full-state differential
   tests and, where possible, local formal proof obligations to production.


## 8. A shortest one-cell periodic-output grammar

Implementation: `experiments/exact_one_cell_loop_grammar.py`.
Verifier: `experiments/verify_exact_one_cell_loop_grammar.py`.

The one-cell literal grammar in Section 3 is extended with exactly the
terminating instruction `[.delta]` (an arithmetic increment/decrement
followed by no other operations). The current nonzero cell is printed,
then updated by the fixed signed increment `delta`; the loop stops
when the updated cell reaches zero. A loop with `delta=0` is excluded.

For a fixed output trace, after every literal output the current cell
equals the last emitted byte, whereas after a completed `[.delta]` loop
the cell is zero. Thus only these two state classes are needed per output
position. The shortest source over this **extended normal-form grammar**
is a shortest path over an acyclic directed graph indexed by output
position and those two possible current bytes.

A `[.delta]` loop of length >=2 determines its unique increment from
the first two observed bytes. A loop of length 1 must use
`delta=-first_byte mod 256`. Every candidate is simulated for one full
cycle to ensure it terminates exactly where the observed trace does.
The dynamic program therefore considers all loops in this grammar and
finds the shortest complete candidate, with final-cell restoration
charged.

CI passed 1,138 full-memory differential cases. Measured on that suite:

* Original literal/reference: **100,700 BF chars**.
* Section 3's exact straight literal: **29,945 BF chars**.
* Loop-augmented grammar: **27,364 BF chars**.

For example, the observed output bytes `5,4,3,2,1` and final zero
cell have straight-literal optimum 15, but loop-grammar optimum 9:

```bf
+++++[.-]
```

The dynamic program is globally optimal only within its explicitly
defined grammar, not across arbitrary BF loops or multiple scratch cells.

## 9. Resynthesizing a flat odd-control affine loop

Implementation: `experiments/affine_loop_resynthesis.py`.
Verifier: `experiments/verify_affine_loop_resynthesis.py`.

For flat balanced loops without I/O, whose control-cell net increment
`c` is odd modulo 256, every 8-bit control entry terminates. With
initial control `x`, each noncontrol target increment `a_j` induces

`y_j' = y_j - x * a_j * inverse(c) (mod 256)`.

Any other odd control increment `c'` together with
`a'_j=a_j*inverse(c)*c' mod 256` realizes **the same affine state
transformation for every possible entry tape**.

We enumerate all 128 odd `c'`, use shortest signed byte spellings
for all updates, and take the shortest path visiting the original
relative pointer extrema `L,R` and returning to control, costing
`2(R-L)` moves. This finds a shortest loop in the normalized family
with a single update for each nonzero target and the original excursion
extrema. Only strict source-length improvements are accepted.

All even-control loops, unbalanced-pointer loops, loops with nested
loops and loops with I/O are left unchanged. The 8-bit wrapping and
left-boundary preconditions are essential. The full seven-artifact
opportunity result is measured separately; do not extrapolate from
synthetic loop savings.

## 10. Verified external-optimizer ABI mismatch

While checking the exact multicell straight theorem, the existing
translator's `optimize_bf` sometimes removed trailing pointer routing
because its internal optimization contract does not appear to observe
the final pointer. Under this project's stronger final-state contract
this is **not** a valid replacement.

On 88 deliberately chosen straight-line cases, this legacy optimizer's
result differed in final pointer in **56 cases**, although output,
input consumption, and memory still matched. The new exact optimizer
preserved the pointer in all 88 cases.

Consequently any future production composition must either tighten
the legacy optimizer's ABI, add and verify a pointer-repair suffix,
or reject outputs that do not satisfy full-state equivalence. It is
incorrect to compare full-state-exact candidates against a weaker
optimizer and assume equivalent behavior without a repair.
