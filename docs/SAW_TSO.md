# SAW-TSO algorithm engineering notes

## State and contract

- `A[i]` is a single `std::atomic<uint64_t>`; low 32 bits hold parent ID, high 32 bits hold an update count.
- `parent[i] == i` represents a root. Non-root edges must satisfy `parent[i] < i`.
- `find(x)` returns a currently observed root, and `unite(x,y)` attempts to merge two previously separate components.
- P1 loads parent words with `memory_order_acquire` and links a higher-ID root to a lower-ID observed root using `compare_exchange_strong` with acquire-release success / acquire failure.
- The actual program uses C++ memory-model atomics; x86 hardware is not a substitute for a formal TSO run.
- Arbitrary stalls are allowed at the model level. A finite native sleep is only a test stimulus.

## Proof obligations and status

| Property | Status |
| --- | --- |
| Parent IDs remain in bounds | Checked by runtime invariant; general proof not included |
| Strictly decreasing parent edges; no cycles | Direct monotonicity argument; native invariant checked |
| `unite` successful CAS links an observed root | Implemented; formal linearizability proof incomplete |
| Failed `unite` result linearizes | Small native history checker only; proof incomplete |
| Lock-free progress under infinite schedules | Not formally proved |
| SC/TSO weak-memory bounded correctness | External checker integration dependent on installed tools; no universal claim |
| Versioning required for safety | Not established for root-only monotone linking |
| Asymptotic inverse-Ackermann efficiency | Not claimed; deep paths may cost O(n) |

## Strong versus weak evidence

The monotone decreasing parent relation rules out cycles in every state where the CAS-only root-update discipline is followed. This invariant alone does **not** prove all concurrent operations are linearizable. A theorem must additionally explain when each return can be ordered in a legal sequential history, including concurrent union races.

P1 has no path compression. A3 may use single-word CAS to shorten edges; this retains decreasing parent IDs when it commits but expands the verification obligation. Any published claim about A3 must be qualified separately.

B1 (serialized reference) and B2 (coarse mutex) serve as engineering baselines. B3/A1 are parent-only CAS implementations, B4 is the SC-atomic control, and A2 is a relaxed-atomic variation. Do not label an ablation incorrect without an observed counterexample or proof.
