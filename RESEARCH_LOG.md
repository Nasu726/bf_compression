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
