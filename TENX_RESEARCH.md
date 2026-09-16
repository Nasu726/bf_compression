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

The next experiment must quantify the tradeoff before implementation: how much source routing would disappear if persistent 99-cell Quad values became 8-cell packed values, versus how much BF source is added by packing/unpacking around arithmetic operations.
