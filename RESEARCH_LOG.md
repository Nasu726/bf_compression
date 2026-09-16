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
3. model `.` as an observable read and `,` as an observable input + overwrite;
4. detect target updates that are definitely overwritten or otherwise unobserved before the epoch boundary;
5. only then attempt a shorter loop representative or deletion;
6. keep boundary demand conservative until a barrier interface summary is proved.

A second independent follow-up is semantic tandem-repeat profiling after pointer-offset normalization, but dead/demand analysis is the higher-priority continuation because the region experiment shows many epochs already contain multiple balanced operations.
