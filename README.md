# Brainfuck Global Compression Lab

Research workspace for semantics-preserving standard-Brainfuck source-size compression.

Primary objective: minimize emitted BF bytes. Runtime speed is diagnostic only. A rewrite is accepted only when the emitted standard-BF source is strictly shorter.

## Research tracks

- modular leaf-loop resynthesis and GCD/unit classification
- shared-scratch nested vector factorization
- backward demanded-information / exact suffix-kernel analysis
- finite-set and 2-adic reachable-state specialization
- constant-output island resynthesis
- static/periodic tape-layout and lifetime coalescing
- semantic rerolling / executable grammar compression

Current state, verified findings, negative results, constraints, and next tasks are in `HANDOFF.md`.

## Reproduce the current corpus profile

Requires Python 3.11+ and no third-party packages.

```bash
python experiments/precompute_tables.py
python experiments/profile_bf.py corpus/*.bf --json > results/profile_corpus_v1.json
```

The generated `results/nested_tables.pkl` is intentionally not committed; regenerate it with `precompute_tables.py`.

## Branching

Keep `main` as the reproducible research baseline. Use one branch per hypothesis, for example:

- `exp/region-epochs`
- `exp/reachable-state`
- `exp/semantic-rerolling`
- `exp/periodic-layout`
- `exp/kernel-windows`

Merge experiments only after saving results and correctness notes.
