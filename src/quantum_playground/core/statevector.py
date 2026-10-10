"""Vectorised statevector simulator with mid-circuit measurement support.

Highlights
----------
* Gates are applied through strided *views* of the state tensor; no 2^n x 2^n
  matrices are ever built.  Permutation gates (X/CX/CCX/MCX/SWAP/CSWAP) and
  diagonal gates (Z/S/T/RZ/P/CZ/CP/MCP/RZZ) take dedicated fast paths.
* Mid-circuit measurements, resets and classically-conditioned gates
  (dynamic circuits, as supported by IBM Heron devices) are simulated by
  *shot-batched branching*: a branch is a (state, shots, classical register)
  triple that splits binomially on every measurement.  Branch count is bounded
  by the shot count, so teleportation-style circuits stay cheap.
* Terminal measurements are sampled in one vectorised draw per branch.
* ``exact_distribution`` performs the same branching with probabilities instead
  of shots, giving the noiseless reference distribution used in reports.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

from . import gates as G
from .circuit import Circuit, Instruction
from .results import CircuitResult, counts_from_samples

_SKIP = ("barrier", "delay")
MAX_QUBITS = 26


# =============================================================================
# low-level kernels
# =============================================================================
def _axis(n: int, q: int) -> int:
    return n - 1 - q


def _base_index(n: int, controls: Sequence[int], ctrl_state: Optional[int]) -> list:
    idx: list = [slice(None)] * n
    for i, c in enumerate(controls):
        want = 1 if ctrl_state is None else (ctrl_state >> i) & 1
        idx[_axis(n, c)] = want
    return idx


def _with(idx: list, n: int, targets: Sequence[int], value: int) -> tuple:
    out = list(idx)
    for j, t in enumerate(targets):
        out[_axis(n, t)] = (value >> j) & 1
    return tuple(out)


def apply_instruction(tensor: np.ndarray, ins: Instruction) -> None:
    """Apply a unitary instruction in place to an n-axis state tensor."""
    apply_gate(tensor, ins.name, ins.qubits, ins.params, ins.ctrl_state)


def apply_gate(tensor: np.ndarray, name: str, qubits: Sequence[int], params: Sequence[float] = (),
               ctrl_state: Optional[int] = None, conjugate: bool = False,
               qubit_offset: int = 0) -> None:
    """Apply gate ``name`` in place.

    conjugate:    apply the complex conjugate matrix (used for the bra side of a
                  density matrix).
    qubit_offset: added to every qubit index (density matrices store the ket
                  qubits at offset n).
    """
    if name == "id":
        return
    spec = G.spec(name)
    nc = G.num_controls(name, len(qubits))
    qs = [q + qubit_offset for q in qubits]
    controls, targets = qs[:nc], qs[nc:]
    if spec.classical and spec.num_targets == 1:            # x, cx, ccx, mcx
        kind = "perm1"
    elif name in ("swap", "cswap"):
        kind = "swap"
    elif spec.diagonal:
        kind = "diag"
    else:
        kind = "general"
    u = None if kind in ("perm1", "swap") else G.base_matrix(name, params)
    if u is not None and conjugate:
        u = u.conj()
    apply_matrix(tensor, u, controls, targets, ctrl_state, kind)


def apply_matrix(tensor: np.ndarray, u: Optional[np.ndarray], controls: Sequence[int],
                 targets: Sequence[int], ctrl_state: Optional[int] = None, kind: str = "general") -> None:
    """Apply a (controlled) matrix to ``targets`` of an n-axis tensor, in place.

    ``u`` need not be unitary (Kraus operators use this kernel too).
    kind: "perm1" (X on one target), "swap", "diag" or "general".
    """
    n = tensor.ndim
    base = _base_index(n, controls, ctrl_state)
    if kind == "perm1":
        i0, i1 = _with(base, n, targets, 0), _with(base, n, targets, 1)
        tmp = tensor[i0].copy()
        tensor[i0] = tensor[i1]
        tensor[i1] = tmp
        return
    if kind == "swap":
        i01, i10 = _with(base, n, targets, 0b01), _with(base, n, targets, 0b10)
        tmp = tensor[i01].copy()
        tensor[i01] = tensor[i10]
        tensor[i10] = tmp
        return
    assert u is not None
    dim = 1 << len(targets)
    if kind == "diag":
        d = np.diag(u)
        for k in range(dim):
            if d[k] != 1:
                tensor[_with(base, n, targets, k)] *= d[k]
        return
    idxs = [_with(base, n, targets, k) for k in range(dim)]
    olds = [tensor[i].copy() for i in idxs]
    for j in range(dim):
        acc = None
        for k in range(dim):
            coef = u[j, k]
            if coef == 0:
                continue
            term = coef * olds[k]
            acc = term if acc is None else acc + term
        tensor[idxs[j]] = 0 if acc is None else acc


def _prob_one(tensor: np.ndarray, q: int) -> float:
    n = tensor.ndim
    idx: list = [slice(None)] * n
    idx[_axis(n, q)] = 1
    sub = tensor[tuple(idx)]
    return float(np.vdot(sub, sub).real)


def _collapse(tensor: np.ndarray, q: int, outcome: int, prob: float) -> np.ndarray:
    n = tensor.ndim
    out = tensor.copy()
    idx: list = [slice(None)] * n
    idx[_axis(n, q)] = 1 - outcome
    out[tuple(idx)] = 0
    if prob > 0:
        out /= math.sqrt(prob)
    return out


def _flip(tensor: np.ndarray, q: int) -> None:
    apply_gate(tensor, "x", (q,))


# =============================================================================
# Statevector object (used by the studio and analysis code)
# =============================================================================
class Statevector:
    def __init__(self, num_qubits: int, data: Optional[np.ndarray] = None):
        if num_qubits > MAX_QUBITS:
            raise ValueError(f"Statevector limited to {MAX_QUBITS} qubits")
        self.num_qubits = int(num_qubits)
        if data is None:
            data = np.zeros(1 << num_qubits, dtype=complex)
            data[0] = 1.0
        self.data = np.asarray(data, dtype=complex).reshape(-1)
        if self.data.size != (1 << num_qubits):
            raise ValueError("state dimension mismatch")

    @classmethod
    def from_circuit(cls, circuit: Circuit) -> "Statevector":
        sv = cls(circuit.num_qubits)
        sv.evolve(circuit)
        return sv

    @property
    def tensor(self) -> np.ndarray:
        return self.data.reshape((2,) * self.num_qubits) if self.num_qubits else self.data

    def evolve(self, circuit: Circuit, ignore_measurements: bool = True) -> "Statevector":
        t = self.tensor
        for ins in circuit.instructions:
            if ins.name in _SKIP:
                continue
            if ins.name in ("measure", "reset") or ins.condition is not None:
                if ignore_measurements and ins.name == "measure":
                    continue
                raise ValueError("Statevector.evolve: use simulate() for non-unitary circuits")
            apply_instruction(t, ins)
        return self

    def copy(self) -> "Statevector":
        return Statevector(self.num_qubits, self.data.copy())

    def probabilities(self) -> np.ndarray:
        return np.abs(self.data) ** 2

    def probabilities_dict(self, threshold: float = 1e-12) -> dict[str, float]:
        p = self.probabilities()
        return {format(i, f"0{self.num_qubits}b"): float(v) for i, v in enumerate(p) if v > threshold}

    def marginal_probabilities(self, qubits: Sequence[int]) -> np.ndarray:
        p = self.probabilities().reshape((2,) * self.num_qubits)
        keep = [_axis(self.num_qubits, q) for q in qubits]
        other = tuple(a for a in range(self.num_qubits) if a not in keep)
        m = p.sum(axis=other) if other else p
        # order axes so qubits[0] is the least significant bit
        cur = sorted(keep)
        order = [cur.index(_axis(self.num_qubits, q)) for q in reversed(list(qubits))]
        m = np.transpose(m, order) if len(order) > 1 else m
        return np.asarray(m).reshape(-1)

    def reduced_density_matrix(self, qubit: int) -> np.ndarray:
        t = self.tensor
        a = _axis(self.num_qubits, qubit)
        moved = np.moveaxis(t, a, 0).reshape(2, -1)
        return moved @ moved.conj().T

    def bloch_vector(self, qubit: int) -> tuple[float, float, float]:
        rho = self.reduced_density_matrix(qubit)
        x = 2 * rho[0, 1].real
        y = -2 * rho[0, 1].imag
        z = (rho[0, 0] - rho[1, 1]).real
        return float(x), float(y), float(z)

    def purity(self, qubit: int) -> float:
        rho = self.reduced_density_matrix(qubit)
        return float(np.real(np.trace(rho @ rho)))

    def entanglement_entropy(self, qubit: int) -> float:
        w = np.linalg.eigvalsh(self.reduced_density_matrix(qubit))
        return float(-sum(x * math.log2(x) for x in w if x > 1e-12))

    def expectation_pauli(self, pauli: str) -> float:
        """<psi|P|psi> for a Pauli string in Qiskit order (left-most = highest qubit)."""
        pauli = pauli.upper()
        if len(pauli) != self.num_qubits:
            raise ValueError("Pauli string length must equal number of qubits")
        t = self.tensor.copy()
        for q, ch in enumerate(reversed(pauli)):
            if ch == "I":
                continue
            apply_gate(t, ch.lower(), (q,))
        return float(np.vdot(self.data, t.reshape(-1)).real)

    def fidelity(self, other: "Statevector") -> float:
        return float(abs(np.vdot(self.data, other.data)) ** 2)

    def amplitudes_dict(self, threshold: float = 1e-10) -> dict[str, complex]:
        return {format(i, f"0{self.num_qubits}b"): complex(a) for i, a in enumerate(self.data)
                if abs(a) > threshold}


# =============================================================================
# shot / branch simulation
# =============================================================================
@dataclass
class _Branch:
    tensor: np.ndarray
    weight: float      # probability (exact mode) or shot count (sampling mode)
    cbits: int


def _terminal_measurements(circuit: Circuit) -> set[int]:
    """Indices of measure instructions that can be deferred to the end."""
    touched_q: set[int] = set()
    used_c: set[int] = set()
    terminal: set[int] = set()
    for pos in range(len(circuit.instructions) - 1, -1, -1):
        ins = circuit.instructions[pos]
        if ins.name in _SKIP:
            continue
        if ins.name == "measure":
            q, c = ins.qubits[0], ins.clbits[0]
            if q not in touched_q and c not in used_c and ins.condition is None:
                terminal.add(pos)
            touched_q.add(q)
            used_c.add(c)
            continue
        touched_q.update(ins.qubits)
        if ins.condition is not None:
            used_c.update(ins.condition[0])
    return terminal


def _condition_ok(cbits: int, cond) -> bool:
    if cond is None:
        return True
    bits, value = cond
    for i, c in enumerate(bits):
        if ((cbits >> c) & 1) != ((value >> i) & 1):
            return False
    return True


def _run_branches(circuit: Circuit, shots: Optional[int], rng: np.random.Generator,
                  initial: Optional[np.ndarray] = None):
    n = circuit.num_qubits
    if n > MAX_QUBITS:
        raise ValueError(f"Local statevector simulation limited to {MAX_QUBITS} qubits (got {n}).")
    if initial is None:
        psi = np.zeros((2,) * n, dtype=complex) if n else np.zeros(1, dtype=complex)
        psi.reshape(-1)[0] = 1.0
    else:
        psi = initial.reshape((2,) * n).astype(complex)
    exact = shots is None
    branches = [_Branch(psi, 1.0 if exact else float(shots), 0)]
    terminal_pos = _terminal_measurements(circuit)
    terminal: list[tuple[int, int]] = []
    for pos, ins in enumerate(circuit.instructions):
        if ins.name in _SKIP:
            continue
        if pos in terminal_pos:
            terminal.append((ins.qubits[0], ins.clbits[0]))
            continue
        new_branches: list[_Branch] = []
        for br in branches:
            if not _condition_ok(br.cbits, ins.condition):
                new_branches.append(br)
                continue
            if ins.name in ("measure", "reset"):
                q = ins.qubits[0]
                p1 = min(1.0, max(0.0, _prob_one(br.tensor, q)))
                if exact:
                    splits = [(0, br.weight * (1 - p1), 1 - p1), (1, br.weight * p1, p1)]
                else:
                    k1 = int(rng.binomial(int(br.weight), p1)) if 0 < p1 < 1 else (int(br.weight) if p1 >= 1 else 0)
                    splits = [(0, float(int(br.weight) - k1), 1 - p1), (1, float(k1), p1)]
                for outcome, w, p in splits:
                    if w <= (1e-14 if exact else 0) or p <= 1e-15:
                        continue
                    t = _collapse(br.tensor, q, outcome, p)
                    cb = br.cbits
                    if ins.name == "measure":
                        c = ins.clbits[0]
                        cb = (cb & ~(1 << c)) | (outcome << c)
                    elif outcome == 1:
                        _flip(t, q)
                    new_branches.append(_Branch(t, w, cb))
            else:
                apply_instruction(br.tensor, ins)
                new_branches.append(br)
        branches = new_branches
    return branches, terminal


def simulate(circuit: Circuit, shots: int = 1024, seed: Optional[int] = None,
             memory: bool = False, readout_error: Optional[Sequence[float]] = None) -> CircuitResult:
    """Sample ``shots`` executions of ``circuit``.

    readout_error: optional (p(1|0), p(0|1)) symmetric-per-qubit flip probabilities.
    """
    if shots < 1:
        raise ValueError("shots must be >= 1")
    rng = np.random.default_rng(seed)
    branches, terminal = _run_branches(circuit, shots, rng)
    width = circuit.num_clbits
    samples_all = []
    for br in branches:
        k = int(br.weight)
        if k == 0:
            continue
        base = br.cbits
        for _, c in terminal:
            base &= ~(1 << c)
        vals = np.full(k, base, dtype=np.int64)
        if terminal:
            p = np.abs(br.tensor.reshape(-1)) ** 2
            p = p / p.sum()
            idx = rng.choice(p.size, size=k, p=p)
            for q, c in terminal:
                vals |= ((idx >> q) & 1).astype(np.int64) << c
        samples_all.append(vals)
    samples = np.concatenate(samples_all) if samples_all else np.zeros(0, dtype=np.int64)
    if readout_error is not None and width:
        p01, p10 = readout_error
        measured = sorted(set(circuit.measured_qubits()))
        for c in measured:
            bit = (samples >> c) & 1
            r = rng.random(samples.size)
            flip = np.where(bit == 0, r < p01, r < p10)
            samples ^= (flip.astype(np.int64) << c)
    rng.shuffle(samples)
    counts = counts_from_samples(samples, width) if width else {"": int(shots)}
    mem = [format(int(v), f"0{width}b") for v in samples] if memory else None
    return CircuitResult(counts=counts, shots=int(shots), num_clbits=width,
                         registers=[(r.name, r.start, r.size) for r in circuit.cregs],
                         memory=mem, metadata={"simulator": "qplay-statevector", "seed": seed})


def exact_distribution(circuit: Circuit) -> dict[str, float]:
    """Noise-free probability of every classical outcome (no sampling noise)."""
    rng = np.random.default_rng(0)
    branches, terminal = _run_branches(circuit, None, rng)
    width = circuit.num_clbits
    out: dict[str, float] = {}
    for br in branches:
        base = br.cbits
        for _, c in terminal:
            base &= ~(1 << c)
        if not terminal:
            key = format(base, f"0{width}b") if width else ""
            out[key] = out.get(key, 0.0) + br.weight
            continue
        p = np.abs(br.tensor.reshape(-1)) ** 2
        nz = np.nonzero(p > 1e-14)[0]
        for i in nz:
            v = base
            for q, c in terminal:
                v |= ((int(i) >> q) & 1) << c
            key = format(v, f"0{width}b")
            out[key] = out.get(key, 0.0) + br.weight * float(p[i])
    total = sum(out.values()) or 1.0
    return {k: v / total for k, v in sorted(out.items())}


def unitary_matrix(circuit: Circuit) -> np.ndarray:
    """Dense unitary of a measurement-free circuit (column j = U|j>)."""
    n = circuit.num_qubits
    if n > 12:
        raise ValueError("unitary_matrix limited to 12 qubits")
    dim = 1 << n
    out = np.zeros((dim, dim), dtype=complex)
    for j in range(dim):
        v = np.zeros(dim, dtype=complex)
        v[j] = 1
        sv = Statevector(n, v)
        sv.evolve(circuit)
        out[:, j] = sv.data
    return out
