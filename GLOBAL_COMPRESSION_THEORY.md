# Global Brainfuck Source-Minimization Model

## Objective

The optimization target is not runtime speed and not preservation of the
compiler's internal ABI.  For an emitted standard-Brainfuck program `P`, seek a
standard-Brainfuck program `Q` with the same observable semantics and minimum
literal source length.

The observables are the project's BF ABI: input/output behaviour and all other
semantics that the chosen execution model makes observable.  Intermediate tape
addresses, compiler record layouts, temporary values, and the shape of the
original loops are not part of the objective and may be discarded completely.

This distinction matters for the 10x track.  A transformation that keeps the
original tape representation is only solving a constrained subproblem.

## Layer 1: global cell relayout is weighted Minimum Linear Arrangement

Consider a relative-coordinate region whose logical cells are known.  Collapse
each maximal textual pointer run to a transition between its source logical cell
`u` and destination logical cell `v`.  If the same transition occurs multiple
times in the source, let `w_uv` be its multiplicity.

After assigning logical cells injectively to physical tape coordinates `p(v)`,
regenerating the pointer runs costs

`sum_{uv} w_uv * |p(u) - p(v)|`.

Therefore free global cell relayout is exactly weighted **Minimum Linear
Arrangement (MinLA)** on the source-transition multigraph.

Consequences:

1. the old one-byte-per-movement-run oracle is the relaxation in which every
   transition edge is allowed to have length one simultaneously;
2. conflicting adjacency requirements can make that oracle unattainable;
3. exact global layout is NP-hard in general because weighted MinLA is already a
   special case of the source-minimization problem;
4. small regions can nevertheless be solved exactly with subset DP.

For a permutation with prefix sets `S_1, ..., S_{n-1}`, every edge contributes
one unit for every prefix cut it crosses, hence

`layout_cost = sum_k cut(S_k, V - S_k)`.

This yields the exact `O(n 2^n)` recurrence used by
`experiments/profile_epoch_minla_bound.py`.

### Rigorous large-region lower bound

For one vertex, distinct neighbours can occupy at most two slots at each
integer distance `1, 2, ...`.  Sort incident edge weights from largest to
smallest and assign them independently to distances

`1, 1, 2, 2, 3, 3, ...`.

This is a lower bound on that vertex's incident layout cost.  Summing over all
vertices and dividing by two gives a rigorous lower bound on weighted MinLA.
It is weaker than the exact DP but cheap enough for large regions.

The profiler deliberately allows independent coordinates across moving/dynamic
barriers.  That makes its aggregate value an optimistic **relaxed lower bound**,
not a semantics-preserving post-pass result.  This is intentional: if even the
relaxed bound is too large, direct tape relayout cannot reach the target.

## Layer 2: lifetime coalescing turns layout into allocation + arrangement

A still more global optimizer should not require every logical temporary to own
a distinct tape cell for the whole program.

Construct a conservative interference relation between virtual values.  Values
whose live ranges do not overlap, and whose zero/value preconditions are
compatible at the reuse boundary, may share one physical cell.  After such
coalescing, the transition graph is built on physical-cell equivalence classes
rather than original compiler cells.

The joint problem is therefore:

1. choose a legal quotient of virtual cells under the interference constraints;
2. arrange the quotient vertices on the one-dimensional tape;
3. minimize regenerated pointer source plus any reset/copy code introduced by
   coalescing.

This subsumes register allocation and MinLA.  Solving it exactly for arbitrary
large BF is unrealistic, but exact block optimization and branch-and-bound are
reasonable for hot bounded regions.

## Layer 3: discard the original BF control structure

Cell relayout still preserves too much of the compiler's lowering.  The next
relaxation converts BF to a semantic structured IR:

- byte-cell arithmetic;
- affine balanced loops;
- scans / moving loops;
- I/O operations;
- known-value and modular facts;
- explicit live virtual values.

Equivalent IR regions may then be resynthesized from scratch.  The source
optimizer is free to choose a different radix, loop direction, scratch layout,
algorithm, or control decomposition when the resulting standard BF is shorter.
HexLane is one example of such resynthesis, but it is not a privileged ABI.

## Layer 4: compressed executable bytecode / VM

For extreme source minimization, even a resynthesized direct BF program may be
the wrong representation.  Standard BF is universal, so a standard-BF program
can implement a small interpreter for a custom bytecode stored on its tape.
This gives the general construction

`Q = payload-builder + bytecode-interpreter`,

where the payload describes the semantics of `P` in a compressed instruction
language.

The important point is that the bytecode is **not extra input**.  The BF source
must construct/decompress its own payload before execution, so the cost of the
payload builder is part of `|Q|`.

A practical research path is:

1. translate BF/semantic IR to a compact run/loop bytecode;
2. grammar- or LZ-compress that bytecode globally, including non-adjacent
   repeated templates;
3. design a BF decompressor that expands the compressed grammar to tape;
4. execute it with a compact BF VM;
5. compare literal source size of the complete self-contained result.

Runtime may become enormous; that is acceptable for this research objective if
literal standard-BF source becomes shorter.

This direction is qualitatively different from adjacent rerolling.  A VM gives
non-adjacent repeated semantic templates a real call mechanism: the template is
implemented once in the interpreter, while the payload contains only an opcode
and arguments.

## Information-headroom measurement

`experiments/profile_information_headroom.py` measures ordinary zlib/bzip2/LZMA
compression of both the BF text and a small semantic run-length bytecode.  These
binary sizes are **not executable BF sizes** and must never be reported as such.
They answer a narrower theoretical question: how much global redundancy remains
in the already-optimized compiler output?

If ordinary compressors still need hundreds of kilobytes, a 0.2 MB
self-interpreting program is doubtful.  If they need only tens of kilobytes,
then 0.2 MB leaves substantial room for a payload builder + interpreter, and the
research priority should move toward executable grammar compression.

## Research decision rule

For the 10x objective, use the following order of evidence:

1. **lower bounds** — rule out constrained classes that cannot reach the target;
2. **relaxed/oracle optima** — estimate headroom without pretending they are
   executable transformations;
3. **complete self-contained BF constructions** — only these count as achieved
   compression;
4. runtime and implementation convenience are secondary unless they force the
   source to become longer.

The project should therefore prefer a theoretically stronger global
representation change over a local 1--5% rewrite whenever the former has a
credible path to a substantially smaller complete standard-BF source.
