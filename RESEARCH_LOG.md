# Brainfuck Compression Research Log

## 2026-09-16 — Relative-base region/epoch profiling

### Question

The existing compiler optimizer abandons known-zero/dataflow work when any loop moves the pointer. How much useful code remains if a moving or dynamic loop is treated only as a local cell-identity barrier instead of a whole-program stop condition?

### Definition

A **relative-base epoch** is a maximal interval inside one lexical scope in which every nested loop is recursively pointer-balanced. A moving or recursively dynamic child loop ends the current epoch. Its body is analyzed recursively with a fresh, unknown base pointer, so absolute cell identity is not required.

The profiler is `experiments/profile_regions.py`; committed output is `results/profile_regions_v1.json`.

Structural invariant checked by the profiler:

- epoch source intervals are disjoint;
- every byte is covered except the two brackets of each moving/dynamic barrier loop, so `covered + 2 * barrier_loops == bf_bytes`.

This invariant is a parser/segmentation check. It also means the raw overall coverage number is structurally generous; epoch length and whether an epoch contains balanced loops are more informative than coverage alone.

### Corpus result

Across `dbfi.bf`, `fibonacci.bf`, `rot13.bf`, and `wc.bf` (1,092 BF bytes total):

- 143 relative-base epochs;
- 924 bytes (84.62%) lie inside some epoch;
- 791 bytes (72.44%) lie in epochs of length at least 4;
- 665 bytes (60.90%) lie in epochs of length at least 8;
- 507 bytes (46.43%) lie in epochs of length at least 16;
- 331 bytes (30.31%) lie in epochs of length at least 32;
- 23 epochs contain at least one recursively balanced loop;
- those balanced-loop-containing epochs account for 578 bytes (52.93%) of the corpus;
- longest epoch: 100 bytes (`fibonacci.bf`).

Per-program relative-base coverage:

- `dbfi.bf`: 79.67%, 188 bytes in epochs >= 8, longest 69;
- `fibonacci.bf`: 96.51%, 159 bytes in epochs >= 8, longest 100;
- `rot13.bf`: 90.53%, 139 bytes in epochs >= 8, longest 44;
- `wc.bf`: 81.11%, 179 bytes in epochs >= 8, longest 21.

### Interpretation

The previous whole-program all-balanced gate is far too coarse for this corpus. Even in programs dominated by moving/dynamic loops, there are substantial relative-address regions large enough for dataflow, loop composition, dead-information analysis, and local resynthesis.

The 84.62% figure must **not** be described as an expected compression ratio or even as strong opportunity coverage: recursively descending into barrier bodies necessarily recovers almost every non-bracket byte. The stronger evidence is that 60.90% of source bytes belong to epochs at least 8 bytes long and 52.93% belong to epochs containing balanced loops, where cross-loop semantic passes can actually have room to act.

### Negative/neutral observation

Inspection of the longest hand-written epochs did not immediately expose a simple literal shortening beyond the already-known local forms. Examples such as the `fibonacci.bf` multiply/output/multiply sequence already use near-minimal small-factor constant synthesis. This is consistent with the earlier result that coefficient rescaling alone finds no profitable leaf loops in the hand-written corpus.

### Next hypothesis

Implement an epoch-local backward demanded-information prototype. Start with facts that do not require reasoning across moving-loop barriers:

1. recognize balanced affine/clear loops as semantic atoms;
2. propagate demanded cell offsets backward inside one epoch;
3. model `.` as an observable read; treat `,` conservatively until EOF semantics are fixed;
4. detect target updates that are definitely overwritten or otherwise unobserved before the epoch boundary;
5. only then attempt a shorter loop representative or deletion;
6. keep boundary demand conservative until a barrier interface summary is proved.

A second independent follow-up is semantic tandem-repeat profiling after pointer-offset normalization, but dead/demand analysis is the higher-priority continuation because the region experiment shows many epochs already contain multiple balanced operations.

## 2026-09-16 — Input/EOF semantics blocks naive dead-store elimination

A first backward-demand scratch prototype treated `,` as an unconditional overwrite. On the current corpus this immediately reported the leading `-` in `rot13.bf`'s `-,+` as dead.

That rewrite is not generally valid. Under the common Brainfuck convention where EOF leaves the current cell unchanged, the sequence deliberately works as an EOF normalizer: from a zero cell, `-` creates 255, EOF leaves 255 in place, and the following `+` maps it back to zero. It also works when EOF itself writes 255. Deleting the leading `-` changes termination behavior under the no-change convention.

This is a useful counterexample because it comes from the committed real corpus rather than a synthetic adversarial case. Input cannot be modeled as a kill operation until the project ABI states EOF behavior precisely. Issue #3 tracks the specification gap.

Until that is resolved, demanded-information analysis should treat `,` as an observable operation that may depend on the previous current-cell value. Safe work can continue on no-input epochs and on transformations whose proof does not require an overwrite assumption.

## 2026-09-16 — Relative-base known-zero propagation gives a real compiler win

### Semantic fact

For any Brainfuck loop `[B]`, if execution reaches the instruction immediately after its closing `]`, the cell currently under the data pointer is zero. This does **not** require `B` to be pointer-balanced.

Reason: the closing `]` repeats the loop exactly when the current cell is nonzero. Therefore a normally terminating exit from the loop has just observed zero at the pointer position reached by the final iteration. If the loop was skipped at `[`, its control cell was already zero and the pointer did not move.

For a pointer-balanced loop this recovers the familiar fact that the original control cell is zero after termination. For a moving/dynamic loop the absolute identity of the exit cell may be unknown, but it can still serve as relative offset 0 of a fresh epoch with the invariant `cell[0] = 0`.

This gives a safe boundary summary:

- discard absolute-address facts at an unrecognized moving/dynamic loop;
- retain the postcondition that the new relative current cell is zero;
- continue ordinary known-zero analysis in the new relative epoch.

Input remains conservative; this result does not depend on any EOF convention.

### Prototype

`experiments/region_zero_opt.py` implements this as a research pass. Unlike the existing compiler optimizer, it does not require every loop in the whole program to be balanced. Balanced regions retain normal zero propagation; moving/dynamic loops only reset the address frame.

`experiments/verify_region_zero.py` differentially checks small adversarial examples under EOF=0, EOF=255, and EOF-leaves-cell-unchanged. In particular `-,+` is preserved.

### Real compiler-generated corpus

The primary test artifact is generated from `Nasu726/Python_to_BF_Translator` main commit `0851b624364013041faa001db55cf9b90447cdef` via `bfcontestpartition.build_partition_program()`.

Crucially, this artifact has **already been optimized by the compiler's existing `bfopt` pass**. It is therefore not a comparison against raw unoptimized compiler output.

Result:

- existing optimized BF: **363,109 bytes**;
- after relative-region known-zero pass: **348,310 bytes**;
- saving: **14,799 bytes = 4.0756%**.

The four compact hand-written programs remain unchanged: `dbfi`, `fibonacci`, `rot13`, and `wc` each save 0 bytes. The gain is therefore currently specific to the repetitive compiler-generated style rather than evidence for general hand-written BF compression.

Reproducible summary: `results/compiler_partition_region_zero_v1.json`.

### Why the gain occurs

The pass removed 715 loops whose control cell was proved zero. Their zero facts originated as follows:

- 627 loops after a terminating pointer-balanced loop (`balanced_exit`);
- 83 after an explicit clear (`clear`);
- 2 from initial zero tape state (`initial_zero`);
- 3 directly from a moving/dynamic-loop exit (`moving_exit`).

Literal source occupied by those 715 removed loops is only 2,173 bytes:

- 1,881 bytes from `balanced_exit` removals;
- 277 from `clear`;
- 6 from `initial_zero`;
- 9 from `moving_exit`.

Yet total saving is 14,799 bytes. Thus **12,626 additional bytes** disappear because deleting semantic no-ops also makes surrounding pointer/value routing unnecessary or allows it to coalesce/cancel. This secondary effect accounts for about 85.3% of the measured saving.

The important conclusion is therefore *not* that the new moving-loop-exit-zero theorem directly deletes many loops: it directly accounts for only three removals in this artifact. The dominant result is that replacing the global all-balanced gate with local relative epochs allows ordinary balanced-loop/clear zero facts to remain usable inside a program that contains moving loops at all. The old global gate was suppressing a large amount of otherwise routine optimization.

### Differential validation

The 363,109-byte and 348,310-byte programs were executed on four partition workloads. For every case, the following observables matched exactly:

- output;
- number of input bytes consumed;
- final data pointer;
- all 30,000 tape cells.

Measured BF command counts also decreased:

- `[1,2,3,4]`: 446,294 -> 413,996;
- `[5,-2,10,1234,-77]`: 832,292 -> 771,990;
- `[100]`: 345,488 -> 328,295;
- `range(12)`: 918,692 -> 823,981.

Differential testing supplements the semantic argument; it is not treated as a proof for all programs.

### Consequence for research priority

This changes the near-term priority. Before adding more exotic synthesis, implement the relative-region known-zero mechanism as the Level-1 semantic baseline and characterize it across several independent compiler-generated artifacts. A simple proof-carrying dataflow pass has already found a 4.1% win after the compiler's existing optimizer.

The next extensions should preserve the same local-barrier discipline:

1. exact/finite reachable-state facts inside an epoch;
2. backward demanded-information on no-input epochs;
3. target pruning for balanced affine loops when downstream demand proves cells dead;
4. semantic rerolling and layout work only after this baseline is measured on multiple compiler workloads.

## 2026-09-16 — Level-1 compiler suite, ablation, and validation

The relative-region known-zero prototype was expanded from one partition artifact to seven independently generated compiler workloads. Every input program had already passed through `Python_to_BF_Translator`'s existing `optimize_bf`, so the measurements are incremental improvements over the current compiler optimizer rather than raw-source cleanup.

### Seven-artifact result

Across 2,066,322 bytes of existing-optimized BF:

- relative-region known-zero output: **1,944,111 bytes**;
- saving: **122,211 bytes**;
- weighted saving: **5.9144%**;
- per-artifact range: **2.76% to 8.33%**.

The workloads are partition, ABC153-style streaming list processing, runtime character store/join, direct join of input characters, string-to-int, int-to-string, and direct integer input/output. The detailed machine-readable record is `results/compiler_region_zero_suite_v1.json`.

All seven reach a fixed point after one productive pass: applying the same pass a second time saves zero additional bytes. This argues for a single recursive traversal rather than an outer fixed-point loop for the Level-1 implementation.

### Ablation: shallow relative regions versus recursion

`experiments/profile_region_zero_ablation.py` compares the full recursive pass with a depth-0 variant that continues dataflow across local relative-base epochs but does not optimize loop bodies recursively.

Aggregated over the seven artifacts:

- shallow relative-region analysis saves **53,891 bytes** = **44.10%** of the full 122,211-byte gain;
- recursive loop-body analysis adds **68,320 bytes** = **55.90%** of the gain.

The split varies sharply by workload. Partition is 98.56% recursion-derived, direct join is 100% recursion-derived, while the runtime character-store case gets 87.54% of its gain from the shallow level. Therefore neither component can be treated as incidental.

The shallow figure must not be described as the direct contribution of the moving-loop-exit-zero theorem. It also includes ordinary top-level facts that become available once the whole-program all-balanced gate is removed. The theorem itself directly removed very few loops in the original partition measurement.

A particularly clean counterexample to the old optimizer architecture is `direct_join_input`: all 826 original loops are pointer-balanced and there are no moving/dynamic barriers, yet the recursive pass still saves **2,131 bytes (5.58%)**. The existing known-zero elimination is only applied at top level and does not recurse into loop bodies. Thus there are two independent design defects in the old baseline: whole-program abandonment in the presence of moving loops, and lack of recursive body dataflow even when every loop is balanced.

### Expanded differential validation

Representative full-state differential execution now covers all seven compiler-generated artifacts. For each checked input, baseline and region-zero output agree on:

- output;
- input bytes consumed;
- final data pointer;
- the complete simulated memory state.

Partition retains its four independent workloads; ABC153 streaming and each string/conversion workload have representative inputs. This is stronger regression evidence than output-only testing, while still remaining empirical evidence rather than a universal proof.

### Negative follow-up: exact-value clear shortening

`experiments/known_clear_opt.py` tested a small finite-state extension. If the exact current 8-bit value before `[-]` is known to be 1, 2, 254, or 255, direct `+`/`-` arithmetic can be shorter than the three-byte clear loop. Adversarial differential tests under all three supported EOF conventions pass.

However, after the region-zero pass the seven compiler artifacts contain **zero profitable occurrences** of this form:

- rewritten exact-value clears: 0;
- incremental saving: **0 bytes**.

This direction is therefore recorded as a negative result and should not be promoted into the Level-1 production baseline merely because the local transformation is valid. It also suggests that the next finite-state experiment should profile opportunity before implementing a broader exact-value resynthesis pass.

### Updated research priority

The Level-1 architecture should be a **recursive relative-region dataflow pass**, not merely a moving-loop barrier patch. The next work should preserve that traversal and first measure where additional semantic information is actually consumed. In particular:

1. profile exact/finite entry states at nontrivial balanced loops and straight-line arithmetic before building resynthesis machinery;
2. pursue backward demanded-information on no-input epochs, where EOF ambiguity is absent;
3. use demand to prune affine-loop targets or dead routing only when the boundary proof is explicit;
4. keep hand-written and compiler-generated BF as separate benchmark classes, since the four compact hand-written programs still gain 0 bytes from Level 1.

## 2026-09-17 — Opportunity-first finite-state follow-up

Before implementing broader exact-state resynthesis, the seven-artifact compiler suite was profiled to establish whether enough opportunity exists to justify it.

`experiments/profile_exact_loop_summary.py` tracks exact 8-bit entry values through the same relative-region discipline and recognizes flat pointer-balanced arithmetic loops. For a loop whose control delta is `c` and exact nonzero entry value is `x`, termination after `k` iterations requires

`c * k = -x (mod 256)`.

`experiments/verify_exact_loop_summary.py` exhaustively compares the congruence solver with direct 8-bit iteration for every `c = 1..255` and `x = 1..255`; the verifier passes.

The real-suite opportunity is nevertheless negligible:

- profitable exact-entry affine summaries: **18**;
- estimated total saving: **36 bytes**;
- approximately **0.00185%** of the 1,944,111-byte Level-1 output.

Together with the exact-value-clear experiment's 0-byte result, this is strong evidence against spending the next implementation budget on general exact-entry finite-state resynthesis for the current compiler output. The valid algebra is retained as research machinery, but no production transform was added for a 36-byte opportunity.

## 2026-09-17 — Conservative backward demand: dead affine targets

A narrower backward-demand proof has substantially more opportunity than the exact-entry follow-up.

### Proof pattern

For a flat pointer-balanced arithmetic producer loop, consider a non-control target offset. The producer's updates to that target can be deleted when, in the same relative pointer frame:

1. a later unconditional `[-]` clears that target;
2. no `.` observes the target before that clear;
3. no `,` touches the target before that clear, because EOF-no-change may depend on the old value;
4. no unrecognized/non-clear loop is crossed;
5. only pointer moves, straight `+/-`, or clears of other cells occur in between.

Deleting those target updates does not change the producer's control-cell evolution or pointer path. If the producer terminates, the later clear forces both executions back to the same target value zero before any permitted observation. If the producer diverges, target pruning does not alter its control evolution, so divergence is preserved.

`experiments/profile_dead_affine_targets.py` found, after Level 1:

- **82** proved-dead affine target updates;
- in **82** producer loops;
- conservative estimated local saving: **538 bytes**.

`experiments/dead_affine_target_opt.py` implemented exactly this proof pattern. The actual first-cycle saving was also **538 bytes**, matching the profiler exactly:

- Level-1 output: 1,944,111 bytes;
- Level 1 + one dead-target pass: **1,943,573 bytes**;
- incremental saving: 538 bytes = about **0.0277%** of Level-1 output.

The first-cycle per-artifact savings are 16, 225, 78, 3, 3, 138, and 75 bytes for partition, ABC153 streaming, runtime character store/join, direct join, string-to-int, int-to-string, and direct integer input respectively. Machine-readable details are in `results/compiler_dead_affine_followup_v1.json`.

### Verification lesson: do not compare arbitrary step-limit states

An initial nested synthetic test used a deliberately nonterminating enclosing loop. Original and optimized programs both remained nonterminating, but the generic differential harness compared their tape states after the same fixed number of executed BF commands. Because shortening the source changes how far each program has progressed at that arbitrary command budget, the intermediate tapes differed and the test failed.

That is not semantic inequivalence. Requiring equal state after an equal *instruction count* is stronger than standard BF program equivalence and is inappropriate for a size-changing optimizer. The test was replaced by a terminating nested case while the transform's proof continues to require preservation of termination/nontermination.

Synthetic tests now cover output observation, conservative EOF/input handling, multiple killed targets, recursive lexical scopes, and fresh relative frames after moving loops. The one-cycle transform also passed representative full-state differential execution on all seven compiler artifacts.

## 2026-09-17 — Forward known-zero and backward demand form a stronger fixed point

A critical follow-up showed that Level 1 and dead-target pruning cannot be treated as independent one-shot passes.

Dead-target pruning can collapse a producer into a clear-like loop. That creates new known-zero information for the next forward Level-1 pass, which can remove more routing/loops and occasionally expose another dead affine producer. `experiments/profile_combined_fixedpoint.py` therefore alternates

`relative-region known-zero -> dead affine target pruning`

until the canonical BF stops shrinking.

Across the seven compiler-generated artifacts:

- existing compiler-optimized baseline: **2,066,322 bytes**;
- Level 1 alone: **1,944,111 bytes**;
- after one combined cycle: **1,943,573 bytes**;
- semantic fixed point: **1,942,406 bytes**;
- total saving versus existing compiler output: **123,916 bytes = 5.9969%**;
- incremental saving beyond Level 1: **1,705 bytes = 0.0877%** of Level-1 output;
- additional saving beyond the first combined cycle: **1,167 bytes**.

The extra feedback savings are concentrated in two more productive cycles:

- cycle 2 adds **728 bytes** of aggregate saving;
- cycle 3 adds **439 bytes**;
- every artifact converges after at most **three productive cycles**, followed by a no-change canonical cycle.

Fixed-point artifact sizes are:

- partition: 348,273 bytes (14,836 saved; 4.0858%);
- ABC153 streaming: 273,163 (24,680; 8.2862%);
- runtime character store/join: 394,054 (36,092; 8.3906%);
- direct join: 36,061 (2,139; 5.5995%);
- string-to-int: 318,266 (23,370; 6.8406%);
- int-to-string: 389,538 (11,469; 2.8600%);
- direct integer input: 183,051 (11,330; 5.8288%).

`optimize_region_zero_dead_affine_fixedpoint` is a bounded research implementation. Each productive cycle must strictly reduce literal size; a same-size textual change or failure to converge within the explicit cycle bound raises instead of silently returning an unproved approximation.

The fixed-point outputs were independently executed on the same representative workloads as Level 1. All seven match the original existing-optimized compiler outputs on output bytes, input consumption, final pointer, and complete simulated memory. Detailed cycle data are committed in `results/compiler_combined_fixedpoint_v1.json`.

### Architecture implication

The repeated full-program implementation is **not** the intended production architecture. Profiling seven artifacts through several whole-program cycles is materially more expensive than one linear traversal, and the integration target remains large compiler output (including >512 KiB) under a practical time budget. The fixed-point experiment establishes a semantic/dataflow interaction, not a recommendation to rescan indefinitely.

A production design should fuse forward known-zero information and backward demand where possible, or use a changed-region/worklist mechanism so a local dead-write rewrite only revisits affected dependency regions. The observed maximum of three productive cycles is useful empirical evidence, not a universal constant bound.

### Next opportunity-first step

Before implementing a general suffix kernel or broader liveness system, measure the residual simplest case on the **fixed-point output**: straight-line `+/-` updates whose value is guaranteed to be destroyed by a later `[-]` before any observation or non-clear loop. The current dead-affine proof already permits crossing such arithmetic but does not delete it. If this residual opportunity is small, the next higher-upside branch should be semantic rerolling / normalized tandem-repeat profiling rather than increasingly elaborate local finite-state machinery.
