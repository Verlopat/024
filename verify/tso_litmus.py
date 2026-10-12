"""Tiny TSO store-buffer litmus interpreter (not an algorithm model checker).

Two threads execute store own location and load other location. Under SC,
(0,0) is forbidden; TSO FIFO store buffers permit it.
"""
from functools import lru_cache


def outcomes(tso: bool) -> list[tuple[int, int]]:
    # Each program: (store own index = 1, load the other index).
    @lru_cache(None)
    def walk(memory, buffers, pcs, reads):
        if pcs == (2, 2) and all(not q for q in buffers):
            return frozenset({reads})
        found = set()
        for tid in (0, 1):
            if pcs[tid] < 2:
                next_pc = list(pcs)
                next_pc[tid] += 1
                if pcs[tid] == 0:
                    if tso:
                        next_buffers = [list(b) for b in buffers]
                        next_buffers[tid].append((tid, 1))
                        found.update(walk(memory, tuple(map(tuple, next_buffers)), tuple(next_pc), reads))
                    else:
                        mm = list(memory)
                        mm[tid] = 1
                        found.update(walk(tuple(mm), buffers, tuple(next_pc), reads))
                else:
                    value = next((v for a, v in reversed(buffers[tid]) if a == 1 - tid), memory[1 - tid])
                    rr = list(reads)
                    rr[tid] = value
                    found.update(walk(memory, buffers, tuple(next_pc), tuple(rr)))
            if tso and buffers[tid]:
                next_buffers = [list(b) for b in buffers]
                address, value = next_buffers[tid].pop(0)
                mm = list(memory)
                mm[address] = value
                found.update(walk(tuple(mm), tuple(map(tuple, next_buffers)), pcs, reads))
        return frozenset(found)

    return sorted(walk((0, 0), ((), ()), (0, 0), (-1, -1)))


def report():
    sc, tso = outcomes(False), outcomes(True)
    return {
        "kind": "store_buffering_litmus_only",
        "sc_outcomes": sc,
        "tso_outcomes": tso,
        "tso_only": sorted(set(tso) - set(sc)),
        "scope": "operational illustration; does not establish DSU correctness under TSO",
    }
