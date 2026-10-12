# Reproducing the SAW-DSU experiments

## Evidence classes

- **Native histories (E1 pilot):** Execute small two-thread histories and check whether *those observed traces* admit a sequential history preserving invocation/response order. This is **not** exhaustive SC verification.
- **TSO educational litmus (E2):** Enumerates the classic two-store, two-load store-buffering program. The `(0,0)` outcome is allowed by TSO but forbidden by SC. This is **not** a DSU verification result.
- **External checkers (E2):** Probe for GenMC and Nidhugg and record command, exit status, stdout/stderr when present. Tool support for source language and model semantics must be confirmed before describing any result as verified. Missing checkers are marked unavailable, not passed.
- **Native measurement (E3–E6):** Reproducible generated workloads; reported timings depend on hardware, scheduling, and compilation. A successful benchmark is not a correctness proof.

## Output organization

Running `python3 Main.py` creates the next free `output/testN/` directory, never overwriting prior runs:

```text
output/testN/
  summary.json
  run.log
  configs/run.json
  manifests/environment.json
  verify/e1_*.json
  verify/tso_store_buffering_litmus.json
  verify/external_*.json
  results/raw/e1_e2_verification.csv
  results/raw/e3.csv, e4.csv, e5.csv, e6.csv
  results/derived/all_summary.csv
  results/derived/T1_model_assumptions.csv
  results/derived/T2_verification.csv
  results/derived/T3_performance.csv
  results/derived/T4_work.csv
  results/derived/T5_pause.csv
  results/derived/T6_stability.csv
  figures/F1_*.svg ... F6_*.svg
```

All large workloads are generated from integer seeds at run time, not stored in the repository. Every run includes the immutable input config and SHA-256 of that configuration. Raw measurements are never deleted or overwritten by derived analysis.

## Scope and known limitations

The C++ algorithm uses deterministic lower-root-ID linking; the `uint64_t` word carries a 32-bit parent ID and a 32-bit update version. Versions must not wrap in tested scenarios. The base P1 algorithm does not compress paths and can have linear-depth chains. A3 is an experimental path-splitting variant.

A root's parent changes only once without path compression. As a consequence, the non-versioned baseline can be safe for the same simplified link discipline; there is **no established counterexample** demonstrating that P1 versioning improves correctness. A1/A2 are experiments, not automatically failing controls. Claims concerning wait-freedom, lock-freedom, asymptotic amortized bounds, model completeness, and a TSO-specific theorem remain unproved. Cooperative delay injection does not enforce a particular thread interleaving and cannot validate liveness.

A failure on a native test demonstrates a concrete problem. No counterexample in a finite native test suite demonstrates only the absence of a *found* failure. The history checker enumerates legal serializations only for at most ten completed operations; it ignores outstanding operations and does not explore all memory-model executions.

## Full runs

Adjust `configs/full.example.json` to the available CPU and disk budget and invoke:

```bash
python3 Main.py --config configs/full.example.json
```

This performs larger *native* benchmark matrices, **not** a full weak-memory proof. A large experiment may require hours. Install optional third-party analysis libraries only if you wish to augment the dependency-free CSV/SVG output.
