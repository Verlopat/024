# SAW-DSU — deterministic concurrent disjoint-set union

Reproducible C++20/Python experiment suite studying a monotone, single-word-CAS DSU under contention, adversarial cooperative pauses, and selected weak-memory assumptions.

## Quick start (Ubuntu Linux)

Check local tools:

```bash
python3 --version
g++ --version
cmake --version
git --version
```

Install the compiler and CMake if missing:

```bash
sudo apt update
sudo apt install -y build-essential cmake python3
```

Run everything with **one command**:

```bash
git clone https://github.com/Verlopat/024.git
cd 024
python3 Main.py
```

No `pip install` is needed for the default smoke workflow. Python standard library and a C++20 compiler are the only hard requirements. `Main.py` builds the native program, runs C++ sanity assertions, generates native histories, attempts optional external checker integrations, runs benchmark suites E3–E6, aggregates results, and generates CSV and SVG artifacts.

Every invocation automatically creates a fresh `output/test1/`, `output/test2/`, `output/test3/`, etc. Outputs are not overwritten. The console prints the path and a JSON summary of failed/successful native tests.

## Main components

| Component | Location | Function |
| --- | --- | --- |
| B1, B2, B3, B4, P1, A1, A2, A3 | `src/dsu.cpp` | C++20 concurrent DSU methods with CAS metrics and optional path splitting |
| Native linearizability checker | `verify/check.py` | Exhaustive search for a serialization of a **specific small observed history** |
| Store-buffering semantics example | `verify/tso_litmus.py` | Compare SC and TSO outcomes for an independent two-thread litmus program |
| External verifier adapter | `verify/external.py`, `verify/harness.cpp` | Attempt installed GenMC/Nidhugg and record transparent status |
| Experiment orchestration | `Main.py` | Workloads W1–W8, native pilot experiments E1–E6 and reproducibility manifests |
| Unit tests | `tests/` | History checking, litmus test, config and analysis checks |
| Local configurations | `configs/` | Default smoke run and adjustable extended native experiments |

### Method IDs

- `B1`: globally serialized baseline for reference measurements.
- `B2`: coarse-grained mutex DSU.
- `B3`: naive parent-only CAS linking with deterministic ID order.
- `B4`: CAS linking with sequentially consistent atomics.
- `P1`: versioned packed-word root CAS with acquire/release synchronization.
- `A1`: P1-style CAS without a version counter.
- `A2`: relaxed-order atomic variation.
- `A3`: P1 with optional CAS-based one-step path splitting.

The method IDs identify *experimental variants*, not established correctness rankings. In particular, monotone parent-only CAS can already avoid ABA in the base no-compression algorithm. Versioning's theoretical benefit is an open question for this restricted design.

### Workload IDs

`W1` uniform mixed, `W2` star contention, `W3` neighboring/chain attempts, `W4` two-cluster connections, `W5` pause-oriented hotspot, `W6` small history generation, `W7` read-heavy preconstructed chain, and `W8` write-heavy mixed operations. Workloads are reproducible across methods given the same seed and configuration, although thread scheduling is not deterministic.

## Other commands

```bash
python3 -m unittest discover -s tests -v
cmake -S . -B build -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build -j2
ctest --test-dir build --output-on-failure
python3 Main.py --config configs/full.example.json
```

**Important:** The default configuration is a bounded, low-resource **pilot**. Results called native-history checks are not exhaustive state-space verification; GenMC/Nidhugg checks require compatible installed binaries and tool-specific review. The isolated TSO litmus does not establish DSU correctness. A final research claim also requires formal safety and progress proofs, counterexample analysis, full-scale benchmark repetition, and independent weak-memory verification. See [reproducibility and evidence scope](docs/REPRODUCIBILITY.md) and [algorithm notes](docs/SAW_TSO.md).

## Metrics and results

Measurements include completed operations, throughput, median/p95/p99 sampled operation latency, parent-word loads per operation, link/split CAS attempts, CAS retries, traversal depth, native observed-history serializability verdicts, and tool-run status. The local summaries include trial counts, median/mean/SD, coefficient of variation for throughput, and exploratory paired bootstrap intervals.

Six figure IDs (`F1`–`F6`) and six table IDs (`T1`–`T6`) are generated in the new output folder. Missing model-checker evidence remains explicitly unavailable. No figure substitutes for a formal verification result.

## Repository layout

```text
024/
├── Main.py
├── CMakeLists.txt
├── requirements.txt
├── .env.example
├── .gitignore
├── configs/
│   ├── smoke.json
│   └── full.example.json
├── src/
│   └── dsu.cpp
├── tests/
│   ├── test_verify.py
│   └── test_end_to_end.py
├── verify/
│   ├── check.py
│   ├── external.py
│   ├── tso_litmus.py
│   └── harness.cpp
├── docs/
│   ├── SAW_TSO.md
│   └── REPRODUCIBILITY.md
└── output/   (created locally; ignored by Git)
```

The code is designed for experimentation, not for use as a production concurrency primitive without independent review.
