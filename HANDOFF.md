# Brainfuck Global Compression Lab — Handoff

Updated: 2026-09-16

## Mission

Research and prototype a semantics-preserving **standard Brainfuck → shorter standard Brainfuck** compressor.

Primary objective is emitted BF byte count. Runtime speed is diagnostic only. A rewrite that makes the final BF longer is rejected even if it runs faster.

Target ABI used by the current compiler project:
- zero-initialized tape;
- 8-bit wrapping cells;
- byte I/O;
- never move left of cell 0;
- enough tape exists to the right;
- standalone `><+-.,[]` output only.

The compressor must derive every proof/precondition from BF itself; no compiler metadata is required.

Practical integration target: >512 KiB compiler BF should complete under ~10 s at the default production compression level on a documented reference machine.

## Current strongest findings

### 1. Flat balanced leaf-loop classification

A pointer-balanced leaf loop containing only `><+-` is summarized by one control delta `c` and target deltas `a_i` modulo 256.

For odd `c`, choose any odd generator `d` and transform targets by

`b_i = a_i * c^{-1} * d (mod 256)`.

This preserves full semantics while changing iteration count. Example:

`[+++>++++++<]` → `[+>++<]` (13 → 7 bytes).

The 1-control/1-target finite model over all 65,536 `(c,a)` pairs has exactly 22,101 semantic classes.

### 2. Shared-scratch nested vector factorization

For transfer coefficient vector `k`, choose an inner iteration count `f` and decompose each coefficient

`k_i = f*b_i + r_i (mod 256)`.

A single known-zero scratch counter is shared by all targets. With precomputed tables, exact one-inner-counter synthesis for a contiguous one-sided target block is online `O(k)` (fixed modulus 256).

Synthetic exhaustive 2-target experiment over all 65,536 coefficient pairs:
- ordinary direct -1 transfer mean: 135.000 bytes;
- best flat odd-generator rescaling mean: 59.551 bytes;
- best(flat, shared-scratch nested) mean: 33.019 bytes;
- 60,539 / 65,536 = 92.38% improved over already-optimal flat rescaling;
- worst best-of(flat,nested): 41 bytes.

Concrete exact example for coefficients `(127,128)`:

`[->>>++[++<+<+>>]<+<<]`

is 22 bytes versus 262 bytes for ordinary direct flat spelling.

These statistics are opportunity-space results, **not expected real-program compression ratios**.

### 3. Backward suffix-kernel reasoning

For a current total transfer vector `k` and exact linear suffix map `S`, replacement `k'` is safe iff

`S(k-k') = 0`.

So source minimization is search for a cheap representative in `k + ker(S)` over `Z/256Z`.

Cheap global approximation: 2-adic demanded information. Exact bounded windows can maintain suffix matrices and use kernel relations. General minimum-Lee-weight coset representative is hard, so use exact small windows / structured cases / heuristics rather than global exact minimization.

### 4. Reachable-state specialization

Forward abstract interpretation should track exact/small finite sets and `2^r` congruence information. Rewrites need only preserve behavior on proved reachable entry states.

Important consequence for no-I/O leaf loops whose target values are dead after the loop: preserve only the termination predicate on reachable control values. Examples:
- all reachable values terminate → `[-]`;
- only zero reachable → delete loop;
- every reachable nonzero value diverges → `[]`;
- mixed reachable set may permit a much cheaper gcd threshold than the original loop.

Boolean/small-set offline superoptimization is promising. Example restricted `{0,1}` NOT transformation discovered at 7 bytes: `-[>+<+]` for the stated pre/postcondition.

### 5. Constant-output islands

Recognize input-independent islands and re-synthesize only their fixed outputs + live final tape state.

Two-anchor DP with shared zero scratch compressed the real `pablojorge/brainfuck` `primes.bf` prefix emitting `"Primes up to: "` from 540 BF bytes to a verified 152-byte replacement including final anchor cleanup and pointer restoration.

Anchor-count experiments show 2 anchors often saturate short strings, while 3–4 help longer natural text. Keep anchor count compression-level / time-budget dependent.

### 6. Static and periodic tape allocation

For statically addressed regions, logical cells may be globally renamed. Pointer byte cost becomes a weighted Minimum Linear Arrangement / one-address-register offset-assignment problem.

Lifetime coalescing can merge logical cells whose values do not overlap.

For periodic moving-loop layouts, model addresses as `q*s + r` and compact the periodic frame while preserving lifetime/interference. On a reconstructed `bfstreamseq` helper, a stride-9 layout was differentially validated against a stride-2 lifetime-coalesced layout for all 256 one-byte inputs and several multi-byte cases; reconstructed helper size fell roughly 293 → 143 bytes. This is promising compiler-output work, not yet a full artifact benchmark.

### 7. Executable rerolling

A pointer-balanced block `P` repeated `k` times can be replaced by a real BF counter loop when a safe scratch counter exists. Counter update need not be `-1`; modulo-256 orbit selection makes many iteration counts cheap. Nested counters cover large repeat counts.

Future direction: trace-normalize independent semantic operations first, then detect runs/tandem repeats, then reroll.

## Real-corpus profiling: important negative result

Current profiler results are in `results/profile_corpus_v1.json` for:
- `dbfi.bf`
- `fibonacci.bf`
- `rot13.bf`
- `wc.bf`

On these hand-written/general BF programs after BF-command filtering:
- flat generator rescaling found **0 profitable leaf loops**;
- simple one-side transfer + hypothetical zero-scratch nested synthesis also found **0 profitable instances**;
- many leaf loops are moving or scan loops;
- many outer loops are moving/dynamic even when inner bodies remain statically analyzable.

Example `dbfi.bf`:
- 423 BF bytes;
- 58 loops;
- 38 leaf loops;
- 11 balanced arithmetic leaf loops;
- 25 moving arithmetic leaf loops;
- 18 pure scan leaf loops;
- 32 recursively-static-moving loops;
- 11 recursively-dynamic loops.

Interpretation: coefficient tricks are strong on synthetic/high-coefficient opportunities but are **not the main expected win on compact hand-written BF**. Prioritize:
1. optimize analyzable subregions inside/around moving loops instead of global all-or-nothing balance gates;
2. scan/periodic layout analysis;
3. cross-loop composition/dead information;
4. constant islands;
5. rerolling / semantic normalization.

Keep general BF and compiler-generated BF benchmark results separate.

## Existing compiler optimizer limitation

`Python_to_BF_Translator/pybf/bfopt.py` globally checks whether all loops are balanced before known-zero dataflow. If any unbalanced/moving loop exists, it falls back to canonicalization-only for that program.

A new compressor should instead use region/epoch segmentation:
- optimize balanced/static subregions recursively;
- treat moving/unrecognized loops as barriers only for facts that depend on absolute cell identity;
- continue relative analysis before/after barriers;
- later reconnect recognized periodic scans when proven safe.

## Compression levels proposed

- Level 0: existing/local canonicalization only.
- Level 1: effectively linear — leaf-loop classification, known/small-set facts, dead-target elimination, demanded bits, precomputed scalar/vector synthesis, small constant islands.
- Level 2: balanced default — Level 1 + runs/rerolling, sparse layout/coalescing, stronger constant-island DP.
- Level 3: strong — exact `Theta(log n)` suffix windows, kernel/SNF reasoning, shifted windows, stronger nested vector synthesis.
- Level 4: research/max — larger exact/superopt windows, executable grammar search, wider periodic layout search under explicit budget.

Invariant: higher levels retain lower-level best-so-far; output size must be monotone non-increasing with level.

Suggested future CLI:
- `--compress-level {0,1,2,3,4}`
- `--compress-time-budget SECONDS`
- `--compress-memory-budget MiB`

## Performance status

Earlier synthetic Python microbenchmark for bracket/leaf analysis + coefficient aggregation + up to 128 flat generator candidates:
- ~1 MiB: ~2.18 s
- ~2 MiB: ~4.19 s

This is not a reference-machine benchmark, but indicates Tier-1 algebraic analysis is compatible with the >512 KiB / ~10 s target. Reserve the expensive budget for layout, exact windows, and rerolling.

## Next recommended work

1. Add region/epoch profiler that does not abandon analysis when moving loops exist.
2. Measure maximal analyzable-region coverage on the current corpus.
3. Add cross-loop dead-target / demanded-information prototype.
4. Add raw and semantic tandem-repeat statistics.
5. Generate a real >512 KiB BF artifact from `Python_to_BF_Translator` and profile it separately from hand-written corpus.
6. Then implement a Level-1 prototype and measure: bytes before/after, per-pass savings, wall time, peak memory.
7. Do not integrate into the compiler until prototype correctness and performance are established.

## Correctness discipline

- Algebraic proof / explicit precondition is primary.
- Differential testing supplements proof; it does not replace it.
- Preserve termination/nontermination, I/O, pointer position, live tape state, and left-boundary safety under the project ABI.
- Never assume a scratch cell merely because it appears unused nearby; prove zero/dead/overwritten status from BF semantics.
- Always compare emitted literal BF length against the original candidate region and reject non-shortening rewrites.
