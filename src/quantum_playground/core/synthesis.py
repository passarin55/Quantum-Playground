"""Reversible-logic synthesis and peephole optimisation.

Three exact permutation synthesisers are provided and ``synthesize_permutation``
returns the cheapest by an NCV quantum-cost model:

``cycles``  the v6–v8 method: decompose into transpositions, realise each with
            a Gray-code ladder of mixed-polarity multi-controlled X gates.
``mmd``     Miller–Maslov–Dueck transformation-based synthesis (DAC 2003),
            bidirectional variant: walks the truth table in order and fixes
            each row with positive-control Toffoli gates from whichever side
            (input or output) is cheaper.
``bfs``     breadth-first optimal search, only for registers of <= 2 bits.

A gate is ``(target, controls, polarities)``; polarity 1 = control on |1>.
Every result is checked against the requested permutation before being
returned, so a synthesis bug can never silently produce a wrong oracle.
"""
from __future__ import annotations

from collections import deque
from functools import lru_cache
from typing import Iterable, Optional, Sequence

from .circuit import Circuit, Instruction

Gate = tuple[int, tuple[int, ...], tuple[int, ...]]


def ncv_cost(num_controls: int) -> int:
    """Approximate NCV quantum cost of an MCT gate (Maslov's table: 1,1,5,13,29,...)."""
    if num_controls <= 1:
        return 1
    return (1 << (num_controls + 1)) - 3


def network_cost(gates: Iterable[Gate], extra_controls: int = 0) -> int:
    return sum(ncv_cost(len(c) + extra_controls) for _, c, _ in gates)


def apply_network_classically(gates: Sequence[Gate], value: int) -> int:
    for t, cs, pol in gates:
        if all(((value >> c) & 1) == p for c, p in zip(cs, pol)):
            value ^= 1 << t
    return value


def _check(perm: Sequence[int], gates: Sequence[Gate]) -> None:
    for i, want in enumerate(perm):
        got = apply_network_classically(gates, i)
        if got != want:
            raise AssertionError(f"synthesis error: {i} -> {got}, expected {want}")


def _validate(perm: Sequence[int]) -> int:
    n = len(perm)
    if n & (n - 1) or n == 0:
        raise ValueError("permutation length must be a power of two")
    if sorted(perm) != list(range(n)):
        raise ValueError("not a permutation")
    return n.bit_length() - 1


# ----------------------------------------------------------------- cycles (v8)
def _gray_swap(first: int, second: int, width: int) -> list[Gate]:
    if first == second:
        return []
    path = [first]
    for bit in range(width):
        if ((first ^ second) >> bit) & 1:
            path.append(path[-1] ^ (1 << bit))
    pairs = list(zip(path, path[1:]))
    out: list[Gate] = []
    for a, b in pairs + pairs[-2::-1]:
        t = (a ^ b).bit_length() - 1
        cs = tuple(j for j in range(width) if j != t)
        pol = tuple((a >> j) & 1 for j in cs)
        out.append((t, cs, pol))
    return out


def synth_cycles(perm: Sequence[int]) -> list[Gate]:
    width = _validate(perm)
    gates: list[Gate] = []
    seen: set[int] = set()
    for start in range(len(perm)):
        if start in seen:
            continue
        cycle = [start]
        nxt = perm[start]
        while nxt != start:
            cycle.append(nxt)
            nxt = perm[nxt]
        seen.update(cycle)
        # transpositions (start, c1), (start, c2), ... realise start->c1->c2->...->start
        for v in cycle[1:]:
            gates.extend(_gray_swap(start, v, width))
    _check(perm, gates)
    return gates


# ----------------------------------------------------------------- MMD
def synth_mmd(perm: Sequence[int], bidirectional: bool = True) -> list[Gate]:
    width = _validate(perm)
    n = len(perm)
    f = list(perm)
    finv = [0] * n
    for i, v in enumerate(f):
        finv[v] = i
    out_gates: list[Gate] = []
    in_gates: list[Gate] = []

    def out_apply(g: Gate) -> None:
        # f <- g o f ; finv <- finv o g
        nonlocal f, finv
        f = [apply_network_classically([g], v) for v in f]
        finv = [finv[apply_network_classically([g], x)] for x in range(n)]

    def in_apply(g: Gate) -> None:
        # f <- f o g ; finv <- g o finv
        nonlocal f, finv
        f = [f[apply_network_classically([g], x)] for x in range(n)]
        finv = [apply_network_classically([g], v) for v in finv]

    def steps(i: int, a: int) -> list[Gate]:
        gates: list[Gate] = []
        for p in range(width):                       # set bits that i has and a lacks
            if (i >> p) & 1 and not (a >> p) & 1:
                cs = tuple(q for q in range(width) if (a >> q) & 1)
                gates.append((p, cs, (1,) * len(cs)))
                a |= 1 << p
        for p in range(width):                       # clear bits a has and i lacks
            if not (i >> p) & 1 and (a >> p) & 1:
                cs = tuple(q for q in range(width) if (i >> q) & 1)
                gates.append((p, cs, (1,) * len(cs)))
                a &= ~(1 << p)
        return gates

    for i in range(n):
        if f[i] == i:
            continue
        g_out = steps(i, f[i])
        g_in = steps(i, finv[i]) if bidirectional else None
        if g_in is not None and network_cost(g_in) < network_cost(g_out):
            for g in g_in:
                in_apply(g)
                in_gates.append(g)
        else:
            for g in g_out:
                out_apply(g)
                out_gates.append(g)
        assert f[i] == i
    gates = in_gates + list(reversed(out_gates))
    _check(perm, gates)
    return gates


# ----------------------------------------------------------------- BFS (<= 2 bits)
@lru_cache(maxsize=None)
def _bfs_table(width: int) -> dict[tuple[int, ...], tuple[Gate, ...]]:
    n = 1 << width
    library: list[Gate] = []
    for t in range(width):
        others = [q for q in range(width) if q != t]
        for mask in range(1 << len(others)):
            cs = tuple(q for k, q in enumerate(others) if (mask >> k) & 1)
            for pol_bits in range(1 << len(cs)):
                library.append((t, cs, tuple((pol_bits >> k) & 1 for k in range(len(cs)))))
    ident = tuple(range(n))
    best: dict[tuple[int, ...], tuple[Gate, ...]] = {ident: ()}
    cost = {ident: 0}
    queue = deque([ident])
    while queue:
        p = queue.popleft()
        for g in library:
            q = tuple(apply_network_classically([g], v) for v in p)
            c = cost[p] + ncv_cost(len(g[1]))
            if q not in cost or c < cost[q]:
                cost[q] = c
                best[q] = best[p] + (g,)
                queue.append(q)
    return best


def synth_bfs(perm: Sequence[int]) -> list[Gate]:
    width = _validate(perm)
    if width > 2:
        raise ValueError("BFS synthesis only for <= 2 bits")
    gates = list(_bfs_table(width)[tuple(perm)])
    _check(perm, gates)
    return gates


# ----------------------------------------------------------------- front door
SYNTHESIZERS = {"cycles": synth_cycles, "mmd": synth_mmd, "bfs": synth_bfs}


@lru_cache(maxsize=4096)
def _synth_cached(perm: tuple[int, ...], method: str, extra_controls: int) -> tuple[Gate, ...]:
    width = _validate(perm)
    if method != "auto":
        return tuple(SYNTHESIZERS[method](perm))
    candidates = [synth_mmd(perm), synth_cycles(perm)]
    if width <= 2:
        candidates.append(synth_bfs(perm))
    return tuple(min(candidates, key=lambda g: (network_cost(g, extra_controls), len(g))))


def synthesize_permutation(perm: Sequence[int], method: str = "auto", extra_controls: int = 0) -> list[Gate]:
    """Cheapest exact MCT network for ``perm`` (bit j of the index = register bit j)."""
    if method not in ("auto", *SYNTHESIZERS):
        raise ValueError(f"unknown synthesis method {method!r}")
    return list(_synth_cached(tuple(int(v) for v in perm), method, int(extra_controls)))


def emit_network(qc: Circuit, register: Sequence[int], gates: Sequence[Gate],
                 controls: Sequence[int] = (), ctrl_state: Optional[int] = None) -> None:
    """Append an MCT network to ``qc`` with optional extra (e.g. key) controls."""
    controls = list(controls)
    extra_state = ((1 << len(controls)) - 1) if ctrl_state is None else ctrl_state
    for t, cs, pol in gates:
        all_controls = controls + [register[c] for c in cs]
        state = extra_state
        for k, p in enumerate(pol):
            state |= p << (len(controls) + k)
        qc.mcx(all_controls, register[t], ctrl_state=state if all_controls else None)


def apply_permutation(qc: Circuit, register: Sequence[int], perm: Sequence[int],
                      controls: Sequence[int] = (), ctrl_state: Optional[int] = None,
                      method: str = "auto") -> int:
    """Synthesize and emit ``perm`` on ``register``; returns the number of gates."""
    gates = synthesize_permutation(perm, method, len(controls))
    emit_network(qc, register, gates, controls, ctrl_state)
    return len(gates)


def extend_permutation(mapping: Sequence[int], width: int) -> tuple[int, ...]:
    """Pad a permutation of 0..m-1 to 2^width entries with fixed points."""
    m = len(mapping)
    return tuple(mapping) + tuple(range(m, 1 << width))


# ----------------------------------------------------------------- peephole optimiser
_SELF_INVERSE = {"x", "y", "z", "h", "cx", "cy", "cz", "ch", "swap", "ccx", "ccz", "mcx", "cswap", "id"}
_INVERSE_PAIRS = {("s", "sdg"), ("sdg", "s"), ("t", "tdg"), ("tdg", "t"), ("sx", "sxdg"), ("sxdg", "sx")}
_ROTATIONS = {"rx", "ry", "rz", "p", "cp", "crx", "cry", "crz", "rxx", "ryy", "rzz", "mcp"}


def _cancels(a: Instruction, b: Instruction) -> bool:
    if a.qubits != b.qubits or a.ctrl_state != b.ctrl_state or a.condition or b.condition:
        return False
    if a.name == b.name and a.name in _SELF_INVERSE:
        return True
    if (a.name, b.name) in _INVERSE_PAIRS:
        return True
    if a.name == b.name and a.name in _ROTATIONS:
        return all(abs(x + y) < 1e-12 for x, y in zip(a.params, b.params))
    return False


def cancel_adjacent_inverses(circuit: Circuit, max_passes: int = 10) -> Circuit:
    """Remove pairs of mutually-inverse gates that are adjacent on all their qubits."""
    ins = list(circuit.instructions)
    for _ in range(max_passes):
        removed = False
        last_on: dict[int, int] = {}
        keep = [True] * len(ins)
        for idx, cur in enumerate(ins):
            if cur.name in ("barrier", "measure", "reset", "delay") or cur.condition is not None:
                for q in cur.qubits or range(circuit.num_qubits):
                    last_on[q] = -1
                continue
            prev = {last_on.get(q, -1) for q in cur.qubits}
            if len(prev) == 1:
                p = prev.pop()
                if p >= 0 and keep[p] and _cancels(ins[p], cur):
                    keep[p] = keep[idx] = False
                    removed = True
                    for q in cur.qubits:
                        last_on[q] = -1
                    continue
            for q in cur.qubits:
                last_on[q] = idx
        ins = [i for i, k in zip(ins, keep) if k]
        if not removed:
            break
    out = circuit.copy()
    out.instructions = ins
    return out
