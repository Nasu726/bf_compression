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
