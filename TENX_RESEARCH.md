# 10x Compression Research Track

Target: move the compiler-generated benchmark suite from roughly 2 MB of already-optimized standard Brainfuck toward roughly 0.2 MB while preserving standalone standard-BF semantics.

## 2026-09-17 — Local semantic cleanup is not the main problem

The current forward/backward semantic fixed point reduces the seven-artifact suite from 2,066,322 bytes to 1,942,406 bytes (5.9969%). This remains useful as a baseline but is far too small for the 10x objective.

Opportunity-first macro profiling changes the research priority.

### Adjacent semantic rerolling is a negative result

`experiments/profile_macro_structure.py` canonicalizes straight arithmetic/moves and also normalizes flat odd-control affine loops by their actual transfer semantics. It then searches bounded tandem periods without double-counting nested regions.

Even with counter setup, scratch allocation, and reroll wrapper cost treated as free, exact tandem rerolling saves only 75 bytes over 2,066,322 bytes. Semantic normalization also saves only 75 bytes. Therefore adjacent executable rerolling is not a plausible primary route to 10x compression on this suite.

There is much larger non-adjacent template duplication: semantically equivalent repeated loop classes account for an unrealistic dictionary upper bound of about 989,001 duplicate bytes. Standard BF has no free subroutine-call primitive, so this is evidence for a possible future executable-dictionary/VM direction rather than immediately realizable saving.

### Tape routing dominates source size

Across the same 2,066,322-byte suite:

- `<` / `>`: 1,906,647 bytes = 92.27%;
- `+` / `-`: 79,512 bytes = 3.85%;
- `[` / `]`: 80,062 bytes = 3.87%;
- I/O: 101 bytes.

There are 74,685 contiguous movement runs, with maximum length 1,884. Movement bytes inside long runs are:

- run >= 32: 1,680,750 bytes = 81.34% of the entire program suite;
- run >= 64: 1,579,537 bytes = 76.44%;
- run >= 128: 1,282,338 bytes = 62.06%.

This makes the 10x problem primarily a tape-layout / value-representation problem, not a local BF peephole problem.

### Routing oracle

A deliberately impossible-looking but informative oracle leaves every non-movement command unchanged and charges exactly one byte for every non-empty movement run. On the original suite:

- non-movement bytes: 159,675;
- movement runs: 74,685;
- one-step-per-run oracle: 234,360 bytes.

The exact 10x target relative to 2,066,322 bytes is 206,632 bytes. Thus perfect routing alone is not quite sufficient, but it is in the right order of magnitude.

After the already-validated semantic fixed point:

- total: 1,942,406 bytes;
- movement: 1,797,391 bytes = 92.53%;
- non-movement: 145,015 bytes;
- movement runs: 70,903;
- one-step-per-run oracle: 215,918 bytes.

This is only 9,286 bytes above the original-suite 10x target. Therefore the combination of strong routing compaction plus modest remaining semantic/template reduction can plausibly approach 0.2 MB in scale. The one-step figure is an oracle, not a proof that a one-dimensional tape can realize all adjacencies simultaneously.

### Structural decomposition of movement

`experiments/profile_layout_headroom.py` classifies movement by enclosing loop structure:

- static context: 1,110,017 bytes = 58.22% of movement;
- statically periodic context: 402,418 bytes = 21.11%;
- recursively dynamic context: 394,212 bytes = 20.68%.

Static + periodic contexts therefore account for 79.32% of all pointer movement. Moving-loop strides are strikingly regular across the suite:

- stride 2: 4 loops;
- stride 3: 34 loops;
- stride 7: 192 loops;
- stride 66: 8 loops.

This makes static layout and periodic-frame compaction the first layout targets. Dynamic movement remains too large to ignore eventually.

The capped routing oracle also shows how severe the target is:

- cap each move run at 1 byte -> 234,360 total bytes;
- cap at 2 -> 272,131;
- cap at 4 -> 334,033;
- cap at 8 -> 422,939;
- cap at 16 -> 548,569;
- cap at 32 -> 728,310.

Average routing distance around two commands is still far from 0.2 MB. The target requires near-adjacency for most hot transitions, plus reductions in non-movement commands / transition count.

Machine-readable summaries:

- `results/compiler_macro_structure_summary_v1.json`
- `results/compiler_layout_headroom_summary_v1.json`

## Representation-level hypothesis

Inspection of `Python_to_BF_Translator` suggests that much of the static routing cost may be structural rather than merely poor variable ordering.

The final scalar compiler uses `Quad64Ref`. Its physical layout is 32 lanes of `[marker, bit0, bit1]` plus a sentinel lane, i.e. 99 tape cells per logical int64. This representation was designed to make hot arithmetic source-compact by walking one repeated stride-3 lane body at runtime, but it gives persistent values and workspaces a very large physical footprint.

The same compiler already contains `PackedI64Ref`, which stores the same int64 in eight ordinary byte cells for list/heap storage. It currently converts between packed storage and the arithmetic representation rather than doing general arithmetic directly in packed form.

This exposes a major 10x research direction:

1. packed-at-rest scalars with a small shared arithmetic workspace;
2. direct dense packed/radix arithmetic if conversion overhead is too large;
3. static placement optimized for weighted transition cost;
4. periodic-frame compaction for the highly regular stride-2/3/7/66 moving loops;
5. only after those, attack the remaining dynamic scans and executable-dictionary opportunity.

## 2026-09-17 — Guarded scalar benchmark and the marker+nibble radix-16 result

### Benchmark correction: zero-tape folding can invalidate primitive measurements

A first representation microbenchmark emitted standalone operations over the normal zero-initialized BF tape. This made some copy/add snippets appear to optimize to zero bytes: the existing `bfopt` correctly proved that their uninitialized source operands were zero and erased the operation.

Those zero-byte results were benchmark artifacts, not representation wins. The corrected benchmark prefixes every persistent operand/output cell with input `,` so its state is unknown, optimizes both the guard-only program and guard+operation program, and reports the difference:

`optimized(unknown-state guard + operation) - optimized(guard only)`.

This is still a microbenchmark rather than a full-program integration result, but it prevents known-zero propagation from deleting the operation under test.

### Corrected baseline: Quad64 and Base4

At `Python_to_BF_Translator` revision `6dcc60c1d38b92be901acc4383a158d254c1ecda`:

| representation | cells/int64 | copy | add | sub | unsigned >= | set const |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Quad64 | 99 | 2,084 | 6,354 | 8,797 | 13,222 | 412 |
| Base4 | 66 | 1,161 | 2,987 | 2,992 | 4,622 | 268 |
| HexLane | 34 | **617** | **2,371** | **2,388** | **3,950** | **228** |
| dense Hex16 | 16 + 4 shared scratch | 6,266 | 42,500 | 42,795 | 25,388 | **198** |

All byte counts are guarded incremental standard-BF source bytes after the existing optimizer.

Base4 remains genuinely better than Quad after correcting the benchmark. Its improvement was not an artifact of zero-tape facts.

### Negative result: plain 16-cell radix-16 arithmetic

`experiments/hex16_scalar_core.py` stores an int64 in sixteen little-endian nibble cells and uses four shared scratch cells. Eight differential BF executions cover all-word carry, all-word borrow, nibble boundaries, sign-bit boundaries, and patterned values; they pass.

The representation is spatially excellent but source-size poor for general arithmetic because each of the sixteen nibble operations is Python-unrolled into the emitted BF. Add grows to 42,500 bytes and subtraction to 42,795 bytes. Dense storage alone therefore does not solve the source-size problem.

This is an important design constraint for the 10x track: the arithmetic representation needs both high information density and a runtime traversal mechanism so the per-digit operation body is emitted once.

### Marker+nibble HexLane

`experiments/hexlane_scalar_core.py` combines the two useful properties:

- sixteen radix-16 value nibbles;
- one temporary traversal marker beside each nibble;
- one sentinel lane;
- total physical width: **34 cells/int64**;
- hot arithmetic emitted as one fixed lane body executed sixteen times at runtime.

The bounded 0..31 radix mapper uses the existing threshold idea from the compiler's hexadecimal kernels: after the sixteenth unit, carry is known to be one and the remaining 0..15 total can be transferred directly rather than emitting another fifteen nested tests.

Eight independent differential BF cases pass for add, subtract, unsigned comparison, preservation of inputs, and restoration of all marker cells to zero.

HexLane is Pareto-better than Base4 on this measured primitive set: it uses about 51.5% as many persistent cells and emits less source for every measured operation. Relative to Quad64, guarded source ratios are:

- copy: 0.2961;
- add: 0.3732;
- subtract: 0.2715;
- unsigned >=: 0.2987;
- set constant: 0.5534.

Machine-readable result: `results/scalar_representation_guarded_v1.json`.

### Interpretation and next test

HexLane becomes the current scalar representation candidate for the 10x track. It does **not** establish a whole-program improvement yet. The generic compiler still needs operations not present in the prototype, including shifts, signed comparisons, truthiness/equality helpers, decimal I/O, and packed/list conversion paths.

The next work is therefore opportunity-directed rather than a blind backend rewrite:

1. instrument the existing compiler to attribute emitted bytes to top-level Quad operations and determine which missing primitives actually dominate the generic artifacts;
2. measure the hot kernels in the specialized stride-66 hexadecimal sequence separately, because those programs do not use the generic Quad scalar path in the same way;
3. integrate HexLane first where the measured coverage is high enough to justify the missing operations;
4. require complete-artifact source-size and differential correctness results before treating the microbenchmark ratios as realized compression.

## 2026-09-17 — Source attribution says HexLane must extend through I/O

`experiments/profile_quad_backend_calls.py` attributes raw emitted BF to the outermost backend call while avoiding nested-call double counting. Across six representative generic compiler programs:

- raw source: **1,679,119 bytes**;
- final existing-optimized source: **1,678,267 bytes**;
- source attributed to backend calls: **1,473,735 bytes = 87.77% of raw**.

The largest attributed emitters are not merely arithmetic:

| backend operation | calls | raw BF bytes | movement bytes |
| --- | ---: | ---: | ---: |
| `print_s64` | 3 | **363,941** | 315,716 |
| `copy_cell` | 97 | **236,451** | 234,996 |
| `slt64` | 3 | **165,260** | 164,138 |
| `read_packed_s64_line_token` | 3 | **151,974** | 144,054 |
| `_eq_byte_const` | 14 | **106,463** | 105,471 |
| `copy64` | 19 | **103,690** | 93,834 |
| `_quad_to_decimal_bytes` | 1 | **99,701** | 88,124 |
| `add64` | 4 | 55,009 | 54,113 |
| `sub64` | 2 | 53,513 | 53,003 |

These are raw attribution measurements: final peephole optimization can coalesce across call boundaries, so the table is for prioritization rather than additive saving prediction.

The implication is strong. Replacing only Quad `copy/add/sub/compare` with HexLane would leave the dominant decimal input/output and byte-copy routing intact. A viable generic 10x backend needs radix-16-native decimal I/O and must shrink the physical distances behind `copy_cell`, `_eq_byte_const`, line handling, and related helper traffic.

The generic path remains the larger global opportunity: these six cases alone are about 1.68 MB, whereas the partition specialization is 363,109 bytes. Therefore full-program effort should prioritize the generic representation, with specialized record work used as a parallel proving ground.

### Independent confirmation in the stride-66 partition specialization

`experiments/profile_hex_specialized_kernels.py` profiles the current specialized prefix implementation:

- optimized complete partition program: **363,109 bytes**;
- cumulative raw after reading N and values: 244,014;
- after reverse-total phase: 246,392;
- partition plus terminal output: 364,477.

Its hot kernels are again overwhelmingly routing:

| kernel | bytes | movement | movement share |
| --- | ---: | ---: | ---: |
| counted prefix record body | **188,482** | 176,148 | **93.46%** |
| partition prefix body, answer extent 6 | **72,916** | 65,664 | **90.05%** |
| DATA->TOTAL add kernel | 9,853 | 8,174 | 82.96% |

This is useful independent evidence because the partition path does not use the generic Quad scalar ABI in the same way. The same pathology reappears in a dense hexadecimal record: statically unrolled nibble operations expose physical field distance as literal BF movement.

Machine-readable summary: `results/source_attribution_summary_v1.json`.

### Revised implementation priority

1. treat HexLane as an **end-to-end scalar ABI candidate**, not only an arithmetic-core replacement;
2. next implement the high-coverage missing scalar operations: signed comparison, zero/nonzero, increment/negate, and especially decimal conversion / printing directly over radix-16 lanes;
3. use one generic real artifact (direct integer input/output is the cleanest initial vertical slice) for the first integration because 99.18% of its raw source is backend-attributed;
4. in parallel, prototype one runtime-lane version of a specialized hexadecimal kernel to quantify how much static nibble unrolling can be removed without yet changing the full stride-66 record ABI;
5. only promote either path after complete-artifact differential correctness and literal-source measurements.


## 2026-09-18 — Relational semantic macros and compression portfolios

The macro track now has an exact round-trip representation that binds not only
constants, but also translation relations among parameter slots.

For a macro occurrence vector `p`, a slot may be represented as

`p[j] = p[r] + delta`

when the same signed difference holds for every observed occurrence of that
macro.  References are restricted to earlier slots, so reconstruction is
acyclic.  A slot is otherwise either a call-site parameter or a constant stored
once in the macro definition.  Rule acceptance is still based on exact
serialized payload size; an inferred relation is never accepted merely because
it looks compiler-like.

`experiments/verify_relational_macro_grammar.py` reconstructs the complete
semantic-token stream and checks exact equality.  It passes on synthetic
translation families and all seven compiler-generated artifacts.

### Measured result

On the 2,066,322-byte seven-artifact suite:

- constant-binding macro + tiny extended LZSS + BF-native prefix loader:
  **123,798 BF source chars** for the payload constructor;
- relational macro + the same lightweight LZSS/channel:
  **89,633 chars**;
- exact 10x target: **206,632 chars**;
- remaining aggregate budget for grammar decoder, semantic VM, tape
  materialization/cleanup, and final-pointer restoration: **116,999 chars**.

The selected relational grammars contain only **8,744 call-site parameter
values** and 463 stored `+delta` relations.  This is substantially stronger
than naively parameterizing every semantic operand.

The per-artifact payload-constructor measurements are:

- partition: 23,330;
- ABC153 streaming: 13,052;
- runtime character store/join: 14,328;
- direct join: 2,300;
- string-to-int: 12,912;
- int-to-string: 12,268;
- direct integer input: 11,443.

These numbers are not yet complete compressed BF programs: decoder / VM /
cleanup source is extra.

### Layering is not monotonically beneficial

Applying the already validated local semantic fixed point first changes the
relational payload-loader total only from 89,633 to **89,452** chars.  Some
artifacts improve and some get worse.  Local simplification can destroy the
regular template structure that grammar compression exploits.

Therefore the production architecture should be a **portfolio**, not a fixed
sequence of every available pass.  Each candidate representation must preserve
semantics independently; the compressor should retain the shortest final
standard-BF candidate.

With only the currently measured candidates

1. constant-bound grammar on the original BF,
2. relational grammar on the original BF,
3. relational grammar after the local semantic fixed point,

selecting the shortest candidate independently per artifact gives a payload
constructor total of **87,403 chars**, leaving **119,229 chars** under the
aggregate 10x target for the decoder/VM/cleanup layer.

The selected paths are not uniform: this is evidence that special-purpose
compressors should coexist with global grammar compression rather than being
blindly chained.

### Correctness obligation for a VM representation

A grammar-threaded semantic VM may execute directly from compressed rules; it
does not need to expand the original multi-megabyte BF source first.  However,
the project equivalence criterion is stronger than output equality.  A final VM
candidate must preserve:

- termination/nontermination;
- I/O sequence and input consumption;
- final data pointer;
- required final/live tape state;
- left-boundary safety.

Therefore VM metadata and compressed payload cannot simply remain as arbitrary
extra state if the original ABI observes those cells.  The final source-size
budget must include any materialization/cleanup epilogue needed to place virtual
state into the original tape layout and restore the final pointer.

### Next high-upside relation

The next opportunity-first experiment is an affine run of macro calls.  If the
same macro appears repeatedly with call vectors

`a, a+d, a+2d, ...`

(or with a short repeating symbol pattern whose corresponding argument vectors
advance by a fixed delta), encode the whole run as one call-pattern definition,
a count, an initial vector, and a step vector.  This composes run-length grammar
ideas with relational parameter binding and is the natural generalization of
the already validated runtime-lane transformations.


## 2026-10-18 — Fused balanced-digit semantic executors (actual BF source)

The prior grammar numbers are only *payload constructor* estimates; a full
standard-BF decoder and semantic interpreter must still be paid for.

To isolate this obligation, we built two **self-contained runnable standard-BF
program generators** for the intentionally limited one-logical-cell ISA:

- `A(delta)`: add an 8-bit value modulo 256;
- `O`: output the cell;
- `C`: clear the cell.

These run from a zero tape and preserve the complete final memory, final
pointer, input consumption, and output. They do not yet implement MOVE,
INPUT, conditional loops, or the complete grammar interpreter.

Both VMs construct reversed one-hot opcode records and then execute a
single right-to-left moving-loop body. Every temporary record is consumed to
zero; the final logical cell is materialized at physical cell 0, pointer 0.

**Fused nibble** (`self_extracting_fused_nibble_vm.py`):
- record: `[state, high-8, low-8, add, out, clear, live]`;
- ADD decodes `16*high + low` directly into state rather than first
  materializing the argument as a standalone byte;
- fixed executor + entry/exit overhead **117 BF chars**.

**Fused octal** (`self_extracting_fused_octal_vm.py`):
- record: `[state, top2-2, mid3-4, low3-4, add, out, clear, live]`;
- ADD uses Horner evaluation `((top*8)+mid)*8+low`;
- fixed executor + entry/exit overhead **130 BF chars**;
- more cells but cheaper mean encoded value cost than radix-16/16.

GitHub Actions `self-extracting-delta-output` completed successfully on
commit `61ca6d0a4e987c8e0039669725375bf19ed27308`.  **346**
full-memory differential test cases passed, including all 256 values of
single ADD byte operands, randomized opcode sequences, and optimization
of the BF source by the translator's current optimizer.

Across these 346 deliberately mixed/edge-case tests, *actual runnable BF
source* aggregates are:

| Candidate | BF source chars |
| --- | ---: |
| Literal reference | 100,651 |
| Fused balanced-nibble | 83,949 |
| Fused balanced-octal | 87,111 |
| Shortest-of literal / existing direct-byte VM / nibble / octal | **56,302** |

For 256 random ADDs (one representative reproducible seed):
literal=**16,001**, nibble=**4,511**, octal=**4,006**. On 64 ADDs:
3,986 / 1,200 / 1,111. On 16 ADDs: 867 / 413 / 370.

The octal variant beats nibble on ADD-heavy sequences, while the larger
8-cell octal record is sometimes more expensive on mixed O/C-heavy
sequences. Therefore global/region choice needs a **cost-based portfolio**,
not an unconditional encoding switch. Also note that these are *single-cell,
zero-initial-tape* experiments: results do not transfer automatically to
general BF input/output, arbitrary final tape state, or the 7 real compiler
artifacts.

Next high-priority step: integrate **grammar/RUN/periodic pattern payloads**
with a real BF runtime decoder and an interpreter supporting pointer motion
and control flow. The reported ~82k grammar payload number must never be
described as a complete 10x BF output until fixed decoder, VM, data layout,
and final state cleanup/materialization are charged and validated.


## 2026-10-18 — Exact bounded-language synthesis, with a corpus-level negative result

We deliberately re-evaluated the earlier fused-VM gains against
**semantically normalized, provably shortest restricted-language baselines**,
not just the raw unoptimized A/O/C instruction stream.

Two independent exact synthesis families are now implemented:

1. `exact_one_cell_literal.py` derives the shortest BF over
   `{+,-,.,[-]}` given a fixed output-byte sequence and final cell value;
   exhaustive cost checks covered all 65,536 byte-state transitions,
   21,845 short source candidates, and 363 full-memory differential tests.
   The 363-case aggregate was **220,561 -> 49,091** BF source chars.
2. `exact_zero_tape_straight.py` derives the shortest BF over
   `{+,-,<,>}` on a zero-initial tape given the complete final
   memory and final pointer:
   `sum_i min(v_i,256-v_i) + 2*max(R,p)-p`, where `R` is the
   highest nonzero cell and `p` the final pointer.  Verified via
   8,788 valid short source programs (1,268 distinct states) and
   88 full-memory differential cases: **18,968 -> 4,256** chars.

A *third* DP family `exact_one_cell_loop_grammar.py` extends the
first one with terminating arithmetic output loops `[.delta]`.
The DP finds the globally shortest source **inside this explicit
loop-augmented normal-form grammar**, not among all Brainfuck
programs.  Its 1,138-case differential suite reduced
**100,700 -> 27,364** chars, versus **29,945** for the
straight literal grammar.  The output sequence 5,4,3,2,1 ending
with zero is realized by `+++++[.-]` (9 chars vs 15 literal).

The resulting **runnable-source portfolio** for the earlier 346-case
fused VM benchmark is now **36,867 chars** instead of 56,302
when exact one-cell normalization and the output-loop grammar are
included. This is a correction to the benchmark methodology:
a 256-ADD source can collapse to at most 128 literal +/- symbols,
so the older 4x random-ADD VM ratio was *not* a sound measure of
distance to the shortest equivalent BF.

A fourth exact-map transformation
`affine_loop_resynthesis.py` reparameterizes flat pointer-balanced
8-bit loops whose control delta is odd.  It enumerates all 128
possible odd control increments, adjusts target coefficients to
preserve the exact affine state transformation, and chooses the
shortest normalized loop while retaining pointer extrema.
64 test families passed both symbolic state-map checks and real
BF full-memory differential tests.  Synthetic example:

```
[- followed by 85 '+' in target cell]  90 BF chars
[+++>+<]                                8 BF chars
```

However, the **actual seven compiler-generated BF artifact suite**
has **zero profitable occurrences** of this transformation:

```
  2,066,322 -> 2,066,322 BF chars; 0 changed loops
```

This is confirmed by the successful `macro-opportunity` CI profiler
`experiments/profile_affine_resynthesis.py`. The dramatic synthetic
11.25x local example is a *negative opportunity result* for the present
compiler corpus and must not be presented as a generic 10x path.

**Research consequence:** abandon broad flat odd-control coefficient
resynthesis as the main compression strategy for the current outputs.
Continue to prioritize grammar/parameter/periodic structural encoding,
a small **real executable** BF decoder/VM, and complete final-state
materialization. All 10x comparisons must include the latter costs;
the ~82k grammar figure remains payload-only.

A related ABI bug was exposed by the exact zero-tape verifier:
the existing translator `optimize_bf` changed the **final data pointer**
on 56 of the 88 chosen straight cases (output and tape bytes still
matched). Future composition must explicitly repair or reject such
outputs under this project's stronger equivalence contract.

Proof details and restrictions are maintained in `THEORY_LIMITS.md`.


## 2026-10-18 — Runnable counted macro grammars, including recursive RUN

A significant distinction from the semantic bytecode *payload* work:
the constructions in this section emit **ordinary, standalone executable
Brainfuck**. Every macro counter is allocated in an initially-zero
private scratch cell, consumed at runtime, and zeroed before termination.
Pointer and full tape state agree with the literal expansion.

### Costed one-cell macro RUNs

`experiments/one_cell_counted_macro.py` finds the cheapest segmentation
of one-cell A/O/C operations into literal operations or bounded
repetitions of a short operation sequence. The search is a
source-length-weighted suffix DP, so all BF instructions for the
counter, bracket pair, routing and final cleanup are charged.
For a block `B` operating only on cell 0 and repeat count
`1<=k<=255`:

```
> INIT(k) [ < B > - ] <
```

is a literal standard-BF expansion of `B^k`, using cell 1 as the
private counter. The body may contain output and clears and need not
preserve its entry value; every iteration has the same operational
effect as the next unrolled copy.

CI passed **1,365 exhaustive short-sequence cost checks** and
**102 full-tape differential tests**, including input-independent
mixed updates and repeated output.

Example runnable source-size savings:

| Repeated workload | Literal BF | RUN BF |
| --- | ---: | ---: |
| emit ASCII `ABC` 255 times | 1,850 | **80** |
| emit same zero byte 255 times | 255 | **9** |
| `ADD(1); OUT` repeated 255 times | 510 | **10** |

The `ABC` trace retains its cell state, output and all scratch cells;
the short output-arithmetic-progression grammar does **not** compress
that trace in the current restricted family. Conversely, `ADD(1); OUT`
can be synthesized as an even shorter six-character arithmetic-output
loop, confirming the need for a *portfolio* rather than a single rule.

The experimental DP scans bounded period/repeat candidates and is not
yet the near-linear production implementation. Its correctness proof
relies on a private zero cell and the one-cell frame.

### Recursive RUN grammars

`experiments/nested_executable_grammar.py` accepts a terminal with
balanced BF brackets, and no tape movement/input, and a nested grammar
`Run(child,count)`. At depth `d` it uses counter cell `d+1`; the
child executes anchored at data cell 0 and may itself use *deeper*
private counters. By induction each level preserves the parent counter
and restores all child scratch to zero. Nested loops in the terminal
are permitted. If the terminal fails to terminate, the direct and
macro variants exhibit the same first divergent iteration.

Full-state CI passed **115 cases**, including 65,025 executions of
an output instruction with two 255-valued counters, randomized nesting
depths and a two-level exact factor-cost selection.

| Runnable repeated body | Literal BF | Nested executable BF |
| --- | ---: | ---: |
| `.` repeated `255*255` times | 65,025 | **21** |
| `+.` repeated `255*255` times | 130,050 | **22** |
| `+.-.` repeated `17*17` times | 1,156 | **56** |

The first two ratios are thousands-fold in deliberately repetitive
synthetic programs. **They are not evidence of equivalent compression
opportunity in the pinned seven-artifact compiler suite.** In particular,
the adjacent balanced tandem profiler previously estimated only 75
bytes of optimistic saving there. Actual corpus headroom must be
re-measured under any expanded macro grammar before generalizing.

### Global unused-cell frame

`experiments/global_scratch_reroll.py` extends this beyond cell-0
fragments, conditional on a *static global tape-footprint proof*: all
loops must be pointer-balanced, the execution never crosses cell 0,
and a scratch cell S is provably never read or written by the original
program. When a syntactically repeated body B returns to anchor A, the
counter can be borrowed from S, even if original pointer routing passes
through S. The block may contain output, input and nested loops.

The exact wrapper cost includes every move A->S and S->A.
A bounded suffix DP chooses profitable contiguous macro occurrences.
Programs with moving/dynamic loops or prohibitive atom count are
left unchanged. This is a direct executable construction, not a
grammar-threaded VM or a general solution for arbitrary BF programs.


## 2026-10-18 — Nonadjacent direct-BF sharing: positive proofs, negative compiler-corpus result

We now have a runnable **one-copy nonadjacent macro** construction using a
descending phase dispatcher instead of a general BF interpreter. For
`B Q0 B Q1 B ... B`, B is stored only once in source. Dedicated phase
flags select the intervening Q blocks in their original order, and all
flags are zeroed before the suffix. The phase-state induction and proof
preconditions are in `THEORY_LIMITS.md`, Section 13.

The experiments proved and full-state tested:

| Proven constructor/discovery | Cases | Raw BF chars | Runnable BF chars |
| --- | ---: | ---: | ---: |
| Explicit globally-unused scratch | 69 | 60,852 | 22,295 |
| Automatic global static-footprint miner | 22 | 13,805 | 6,248 |
| Explicit local known-zero scratch after moving barriers | 55 | 39,895 | 19,299 |
| Automatic top-level relative-epoch miner | 22 | 11,530 | 6,592 |

`nonadjacent_epoch_macro.py` strengthens the scratch proof. The scratch
cells need not be untouched by the entire program: it is sufficient that
they are **known zero at the macro region's entry**, remain untouched by
the original macro/gaps, and are restored to zero before the suffix.
An abstract interpreter tracks exact or unknown cells modulo 256, treats
input as unknown, and resets its coordinate frame after terminating
moving loops while retaining the known-zero exit cell. This is the
missing bridge between root-level static scratch and moving-loop
programs. The direct BF transformations run without an auxiliary
input data file, and full-state differential verification succeeded.

However, the new `profile_epoch_macro_corpus.py` measured this bounded
**root lexical scope** pass on the actual seven pinned compiler artifacts:

```
original total  = 2,066,322 chars
candidate total = 2,066,322 chars
saving          =         0 chars
```

The successfully completed `macro-opportunity` workflow reported:

| Artifact | Root epochs | Epochs within 2500-atom budget | Savings |
| --- | ---: | ---: | ---: |
| partition | 10 | 10 | 0 |
| ABC153 streaming | 5 | 2 | 0 |
| char runtime store | 8 | 1 | 0 |
| direct join | 1 | 1 | 0 |
| string-to-int | 69 | 68 | 0 |
| int-to-string | 68 | 65 | 0 |
| direct int input | 67 | 65 | 0 |

The root search is limited to short block periods and the 8
highest-scoring occurrence groups per epoch, so zero measured saving
is **not a formal bound on all source sharing**. Nevertheless, no
profitable opportunity was exposed under this particular sufficient
condition and budget. Do not extrapolate 2x synthetic gains to compiler
outputs.

Research implication: stop treating more aggressive root-scoped phase
dispatch as the main 10x path. The remaining large opportunity is
nonadjacent/repeated semantic templates *inside nested lexical scopes*
and across differing logical tape positions. Recursive scope mining
with unknown initial cell values can test the former. A
grammar-threaded VM or compiler-level semantic backend is required
for the latter. Keep the ~82k grammar figure labeled as payload-only
until a self-contained decoder+VM+cleanup program is measured.


## 2026-10-18 — Nested lexical-scope macro investigation

The original root-only epoch-aware search measured zero savings on the
2,066,322-character seven-artifact compiler baseline. We therefore
extended the proof-gated search into BF loop bodies. Loop-body entry
tape values are UNKNOWN, even when the whole program starts from a
zero tape: only a local clear or other established invariant may certify
scratch cells. The underlying local-zero constructor also remains
conservative about input and moving-loop coordinates.

A separate offline opportunity scan over the available **1,942,406-char
fixed-point BF corpus** detected repeated balanced blocks inside nested
loop bodies. For example, in the largest 72 eligible loop bodies of the
ABC153 streaming artifact, 374 sets of exact nonadjacent block repeats
were found by a bounded syntactic scanner. This is *not* executable
compression: a phase dispatcher additionally needs enough proven-zero
private scratch cells.

An offline shadow implementation, with proof-gated scratch allocation
and a full-state 8-bit BF interpreter, passed 96 nested-program
differential cases; 94 were profitable. On the available fixed-point
seven-artifact corpus, however, the restricted top-72-scope search
saved **zero chars (1,942,406 -> 1,942,406)**. The sample exposes a
clear distinction between repeat candidates and actually usable
certified scratch. This is a bounded negative result, not a global
noncompressibility claim.

The research branch now carries
`experiments/profile_nested_scope_corpus.py`, run against the
**original 2,066,322-char pinned corpus** by
`.github/workflows/macro-opportunity.yml`. It separately reports
those authoritative source-size measurements.

Priority remains a *grammar-threaded standard-BF execution
architecture* or more efficient representation of parameters, not
unbounded expansions of this narrow one-hot phase-dispatch heuristic.


### Original compiler corpus result (confirmed by CI)

The `macro-opportunity` workflow on the pinned original corpus
completed successfully: **2,066,322 -> 2,066,322 BF chars**, zero
profitable nested-scope nonadjacent rewrites. The bounded miner examined
**455 lexical scopes** across the seven artifacts (72 scopes per
artifact where available). Together with the fixed-point corpus
negative result, this is evidence that the direct one-hot dispatcher
is not a promising main route to the 10x target under current proof
preconditions. It is *not* a global noncompressibility bound.

The initial nested-scope CI failure was traced to one invalid fixture
which moved left from tape cell zero, not to a compressor semantic
mismatch. After replacing that fixture with valid pointer-balanced
BF, the entire 22-case original nested verifier passed offline
alongside 96 additional independent full-memory shadow tests.


## 2026-10-18 — A genuine runnable threaded macro dictionary over W tape cells

Added \`experiments/threaded_window_macro_vm.py\` and
\`experiments/verify_threaded_window_macro_vm.py\`. This crosses a
different boundary from grammar payload profiling: the complete
macro dictionary and arbitrary nonadjacent call schedule are compiled
into ONE self-contained standard-BF program. The cost includes data
initialization, opcode dispatch, the single literal copy of every
dictionary macro, transfer of every logical tape cell, and full
scratch cleanup.

For K statically defined balanced macros and W logical data cells, a
reversed call record is \`[W data | K one-hot symbol flags | live]\`,
of width R=W+K+1. The executor consumes the live flag, executes the
selected dictionary macro at the record's data anchor, and carries all
W data cells to the preceding record. Dictionary macros can use all
eight BF commands, including comma/input, output, and statically
balanced nested loops, but cannot leave the W-cell window or contain
a moving-pointer loop. They do not read or write dispatch metadata.
This restores the final W real data bytes in cells [0,W), all other
cells zero, and pointer zero. Input/EOF semantics are inherited from
the pinned BF interpreter; no dead-store assumption on comma is used.

**Exact source accounting** for N calls:
  * record constructor: R + N*(R+2) BF characters;
  * full compiled output: constructor + 1 + dispatcher length + (R-1);
  * each macro definition appears once, inside the shared dispatcher.
The source-size portfolio emits the literal expansion instead when
the complete VM encoding would be longer.

Offline differential tests under the pinned interpreter's zero-EOF
convention passed **1,131 cases**, comparing output, input consumption,
final pointer and every allocated tape cell. This includes exhaustive
call streams of length 0..5 for three macro dictionaries at 1, 2 and 3
cells, randomized larger call sequences, multi-cell state transfer,
input and nested loops.

Representative source-length comparisons (literal vs *fully runnable*
standard BF, including payload, dictionary VM and cleanup):

| Window | Dictionary macros | Calls | Literal | Threaded VM |
| ---: | ---: | ---: | ---: | ---: |
| 2 | 3 | 1 | 300 | 893 |
| 2 | 3 | 3 | 860 | 909 |
| 2 | 3 | 16 | 4,120 | 1,013 |
| 2 | 3 | 64 | 16,825 | 1,397 |
| 2 | 3 | 128 | 34,850 | 1,909 |

The last row gives **18.26x source reduction** on an intentionally
dictionary-friendly synthetic instance. For a tiny dictionary of
short instructions, the VM is longer: literal fallback is necessary.
These measurements are **not** the pinned seven compiler artifacts,
nor an implementation of the full signed-relational/periodic grammar.

A separate local footprint scan of the available **1,942,406-char
fixed-point seven-artifact BF corpus** counts only **51,427 source
characters** in flat, pointer-balanced leaf loops whose peak pointer
distance is at most three cells (width <=4). Even a zero-cost
replacement for *all those leaf loops alone* would save at most
2.65% of this corpus. This is a bound only for modifying those
specific leaf-loop substrings, NOT for sharing larger macro blocks
or re-encoding movement globally. It reinforces the need for
cross-region reuse, parameterized grammar rules, and efficient
pointer/tape representation.

Next stages: automatically extract balanced tape-window macros from
compiler source; replace one-hot call records with a denser encoded
symbol stream; connect relational/periodic rules; extend beyond
bounded W and restore arbitrary final pointer. Do not label this as
the end-to-end 10x result.


## 2026-10-18 — Numeric opcode and RLE threaded BF dictionary

A complete-source size portfolio now compares executable bounded-window
dictionary grammars, rather than extrapolating from compressed payload bytes.
New files:
* \`experiments/threaded_grammar_portfolio.py\`
* \`experiments/verify_threaded_grammar_portfolio.py\`
* \`.github/workflows/threaded-grammar-portfolio.yml\`

Four *standalone, executable standard-BF* dictionary formats are compared
against untouched literal BF:

1. Existing one-hot macro call records of width \`W+K+1\`, where W is the
   number of logical tape cells and K is the number of dictionary macros.
2. **Numeric opcode** records of width **W+4**, independent of K (K<=128).
   Each record contains \`[W data,Q,T,R,live]\`. The dispatcher tests Q
   against successive symbols by destructive transfer and restoration
   through T,R. After a match, a sentinel value prevents double dispatch.
3. **One-hot counted RUN** records of width **W+K+2**, containing a
   modulo-256 repeat count; the selected dictionary body executes that
   many times directly via a BF loop while preserving all W data cells.
4. **Numeric counted RUN** records of width **W+5**, combining the two
   encodings and using a single numeric opcode test per run.

In each case, only one literal copy of each used macro appears in
the dispatcher, records are stored in reverse call order, the current
W-byte logical data window is transferred to the previous record on
completion, and *all temporary record fields are zeroed*. The final
physical cells [0,W) and pointer at zero match literal expansion.
The test uses 8-bit wrapping cells, zero-initial tape and the pinned
interpreter's zero-byte EOF. Macros may use all eight commands and
nested balanced loops but must stay inside W logical cells, and moving
loops are not accepted.

A source-length DP chooses the best division of identical adjacent
calls into count records (1..255), using the actual unary count
constructor cost and entire record width. Dictionary definitions are
deduplicated and unused definitions removed. Two candidate orderings
are tried: call frequency and RUN-record frequency. For a fixed
segmentation, descending frequency minimizes the numeric ID
constructor cost; the portfolio evaluates the complete BF source of
each resulting variant. These choices are not claimed to achieve the
globally shortest grammar.

**Before any GitHub commit**, an isolated local verifier passed
256 full-state differential cases and explicit constructor-length
identities for dictionary sizes 1,2,5,16,64,128. It exercises
all 8 BF commands within supported bounded balanced macros,
non-adjacent symbol call orders, repeated calls including counts 255
and 256, and dictionary deduplication.

Representative synthetic examples (full emitted BF chars):

* 2-cell, 3-macro, 128 arbitrary calls: earlier one-hot example
  34,850 -> 1,909, already proved in the prior section.
* 2-cell, 2 effective macros, 255 identical calls on a long macro:
  **14,025 -> 123** via a single counted RUN record after
  dictionary normalization; literal program and VM include their
  complete output/tape state.
* 1-cell dictionary with 12 distinct balanced macro definitions
  and 256 randomly distributed calls: original 25,767; original-ID
  one-hot 5,571; original-ID numeric 4,670; frequency-reordered
  numeric **4,520** (synthetic deterministic sample).

These numbers are limited to the macro-dictionary-friendly synthetic
test family; **nothing here proves 10x on the seven real compiler
artifacts**. A meaningful remaining bottleneck is *nested grammar
rules and relational parameter decoding*, since even a compact
one-level record per semantic token far exceeds the 206,632-source
character target at roughly 109k semantic tokens. Complete grammar
execution must reduce the number of runtime call records, not merely
their width.


## 2026-10-18 — Actual standard-BF hierarchical RUN record constructor

Added a **runnable** hierarchical grammar-constructor proof-of-concept:
`threaded_hierarchical_grammar.py`, `mine_hierarchical_call_runs.py`
and paired verifiers. These are for balanced terminal macros confined to
a known W-cell tape window, 8-bit wrap and zero-on-EOF. Source includes
the constructor, real macro executor, data propagation, and scratch cleanup.

A grammar comprises `Call(i)`, `Seq(...)`, `Run(child,k)` for
1<=k<=255, and acyclic named `Ref` nodes. Named definitions are currently
**inlined at compile time**. This therefore does NOT provide true DAG
nonterminal-body sharing across distinct references; that requires an
additional rule dispatcher/stack interpreter. Nevertheless `Run` is
*not* expanded: the BF constructor itself loops across moving records.

For grammar nesting depth D, physical record stride is W+4+D,
comprising W logical data cells, numeric terminal opcode Q, two opcode-test
scratch cells, D moving repeat counters, and one live flag. The constructor
emits records **in reverse execution order**. A single `Call` emits an
opcode/live record, destructively moves every active repeat counter
forward one record, and advances the construction cursor. The generated
standard BF `[...]` loop for a `Run` tests its counter in the *new*
record after each child invocation. This enables an arbitrarily long
generated call stream without unrolling the loop source. After generation
the existing shared terminal-macro dispatcher executes the records from
right to left and transfers every logical data byte toward cell 0.
All generated counters, records and intermediate values are zero on exit.

Offline full-tape differential checks passed **471 varied grammar cases**
plus an actual execution of **4,096 nested repeated calls**; all output,
input consumption, final pointer and memory bytes match literal expansion.
The CI separately confirms these numbers.

Representative **complete executable BF source lengths** with provided
hand-designed grammars:

| Window W | Macro calls | Literal source | Hierarchical BF |
| ---: | ---: | ---: | ---: |
| 1 | 768 | 2,304 | 464 |
| 2 | 768 | 3,840 | 542 |
| 3 | 768 | 7,936 | 634 |
| 1 | 195,075 | 585,225 | 434 |
| 2 | 195,075 | 975,375 | 512 |
| 3 | 195,075 | 2,015,775 | 604 |

The 195,075-call rows are **source-size measurements**; they were not
fully runtime-executed at that scale. They demonstrate that nested runtime
record construction decouples source length from the repetition count in
structured programs, not that real compiler BF has this grammar.

The second module `mine_hierarchical_call_runs.py` automatically finds
periodic segments of an arbitrary supplied terminal-call stream and uses
source-cost DP to select literal calls or non-overlapping bounded RUNs,
with period <= a user-chosen cap and count <=255. In a fixed depth-one
representation this is an exact DP for the specified decomposition grammar.
The final selector additionally compares the **complete depth-zero
no-RUN BF**, because the added moving-counter cell can make any tiny RUN
more expensive. This fixed-overhead correction was validated by 254
exhaustive short call-stream enumerations and 435 full-state differential
cases.

For example, with W=2 and supplied three-macro periodic call stream:
1,023 calls => literal 5,115 BF chars, flat numeric VM 8,374,
**automatically inferred hierarchical program 622 chars**.
Smaller streams correctly fall back to literal or flat encoding.

**Open obligations for the actual seven compiler artifacts:**
(a) recognize semantic terminal calls preserving a suitable bounded
window; (b) share named nonterminal rule bodies without compile-time
inlining (actual DAG grammar walker); (c) recover affine/relational
parameters at runtime; (d) support moving loops and large tape state,
arbitrary final pointer, and dynamic I/O; (e) verify source-size and
complete equivalence on each pinned benchmark. This proof-of-concept is
not a demonstrated 10x compression of the pinned 2,066,322-char suite.
