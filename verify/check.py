"""Bounded offline linearizability checker for completed native DSU histories.

This checks the recorded history, NOT all SC/TSO executions of the program.
"""
from __future__ import annotations


def linearizable(history: list[dict], n: int, max_operations: int = 10) -> dict:
    if len(history) > max_operations:
        return {"status": "not_checked_history_too_large", "operations": len(history)}
    events = sorted(history, key=lambda r: (r["thread"], r["index"]))
    if not events:
        return {"status": "pass", "witness": []}
    predecessors = []
    for i, a in enumerate(events):
        predecessors.append(sum(1 << j for j, b in enumerate(events) if j != i and b["end_ns"] < a["start_ns"]))
    cache = set()
    full = (1 << len(events)) - 1

    def root(parents: tuple, x: int) -> int:
        while parents[x] != x:
            x = parents[x]
        return x

    def search(mask: int, parents: tuple[int, ...], witness: tuple[int, ...]):
        if mask == full:
            return witness
        key = mask, parents
        if key in cache:
            return None
        for i, e in enumerate(events):
            if mask >> i & 1 or (mask & predecessors[i]) != predecessors[i]:
                continue
            if not 0 <= e["x"] < n or not 0 <= e["y"] < n:
                continue
            rx = root(parents, e["x"])
            ry = root(parents, e["y"])
            if e["op"] == "find":
                if e["result"] != rx:
                    continue
                next_parents = parents
            else:
                if e["result"] != int(rx != ry):
                    continue
                if rx == ry:
                    next_parents = parents
                else:
                    mutable = list(parents)
                    mutable[max(rx, ry)] = min(rx, ry)
                    next_parents = tuple(mutable)
            found = search(mask | (1 << i), next_parents, witness + (i,))
            if found is not None:
                return found
        cache.add(key)
        return None

    ordering = search(0, tuple(range(n)), ())
    if ordering is None:
        return {"status": "fail", "operations": len(events), "reason": "no sequential witness respecting real-time order"}
    return {"status": "pass", "operations": len(events), "witness": [
        {"thread": events[i]["thread"], "index": events[i]["index"]} for i in ordering
    ]}
