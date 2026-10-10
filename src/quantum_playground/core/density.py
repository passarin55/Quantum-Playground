"""Density-matrix simulator with gate, relaxation and readout noise.

The density matrix of n qubits is stored as a 2n-axis tensor that the
statevector kernels can act on directly: ket qubit q lives at virtual qubit
``q + n`` and bra qubit q at virtual qubit ``q``.  U rho U^dagger is therefore
"apply U to the ket half, conj(U) to the bra half".

Mid-circuit measurements branch exactly (probability weights), and the final
outcome distribution is computed exactly before shots are drawn, so sampling
noise is the only stochastic element.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

from . import gates as G
from .circuit import Circuit, Instruction
from .noise import (NoiseModel, amplitude_damping_kraus, depolarizing2_kraus, depolarizing_kraus,
                    phase_damping_kraus, thermal_relaxation_params)
from .results import CircuitResult, counts_from_samples
from .statevector import apply_gate, apply_matrix, _condition_ok, _terminal_measurements

MAX_DENSITY_QUBITS = 11


class DensityMatrix:
    def __init__(self, num_qubits: int, data: Optional[np.ndarray] = None):
        if num_qubits > MAX_DENSITY_QUBITS:
            raise ValueError(f"Density-matrix simulation limited to {MAX_DENSITY_QUBITS} qubits")
        self.n = int(num_qubits)
        dim = 1 << self.n
        if data is None:
            data = np.zeros((dim, dim), dtype=complex)
            data[0, 0] = 1
        self.tensor = np.asarray(data, dtype=complex).reshape((2,) * (2 * self.n))

    @property
    def matrix(self) -> np.ndarray:
        dim = 1 << self.n
        return self.tensor.reshape(dim, dim)

    def copy(self) -> "DensityMatrix":
        return DensityMatrix(self.n, self.tensor.copy())

    # ------------------------------------------------------------ evolution
    def apply_gate(self, name: str, qubits: Sequence[int], params=(), ctrl_state=None) -> None:
        apply_gate(self.tensor, name, qubits, params, ctrl_state, conjugate=False, qubit_offset=self.n)
        apply_gate(self.tensor, name, qubits, params, ctrl_state, conjugate=True, qubit_offset=0)

    def apply_kraus(self, kraus: list[np.ndarray], qubits: Sequence[int]) -> None:
        if len(kraus) == 1 and np.allclose(kraus[0], np.eye(kraus[0].shape[0])):
            return
        acc = np.zeros_like(self.tensor)
        for k in kraus:
            t = self.tensor.copy()
            apply_matrix(t, k, (), [q + self.n for q in qubits], None, "general")
            apply_matrix(t, k.conj(), (), list(qubits), None, "general")
            acc += t
        self.tensor = acc

    # ------------------------------------------------------------ queries
    def probabilities(self) -> np.ndarray:
        return np.real(np.diag(self.matrix)).clip(min=0)

    def purity(self) -> float:
        m = self.matrix
        return float(np.real(np.trace(m @ m)))

    def trace(self) -> float:
        return float(np.real(np.trace(self.matrix)))

    def prob_one(self, q: int) -> float:
        idx: list = [slice(None)] * (2 * self.n)
        ket_axis = 2 * self.n - 1 - (q + self.n)
        bra_axis = 2 * self.n - 1 - q
        idx[ket_axis] = 1
        idx[bra_axis] = 1
        sub = self.tensor[tuple(idx)]
        dim = 1 << (self.n - 1)
        return float(np.real(np.trace(sub.reshape(dim, dim)))) if self.n > 1 else float(np.real(sub))

    def project(self, q: int, outcome: int) -> float:
        """Project qubit q onto ``outcome`` in place; returns the probability."""
        p = self.prob_one(q) if outcome == 1 else 1 - self.prob_one(q)
        ket_axis = 2 * self.n - 1 - (q + self.n)
        bra_axis = 2 * self.n - 1 - q
        for axis in (ket_axis, bra_axis):
            idx: list = [slice(None)] * (2 * self.n)
            idx[axis] = 1 - outcome
            self.tensor[tuple(idx)] = 0
        if p > 1e-15:
            self.tensor /= p
        return p

    def reduced_bloch(self, q: int) -> tuple[float, float, float]:
        m = self.matrix
        dim = 1 << self.n
        rho = np.zeros((2, 2), dtype=complex)
        for i in range(dim):
            for j in range(dim):
                if (i ^ j) & ~(1 << q) & (dim - 1):
                    continue
                rho[(i >> q) & 1, (j >> q) & 1] += m[i, j]
        return (float(2 * rho[0, 1].real), float(-2 * rho[0, 1].imag), float((rho[0, 0] - rho[1, 1]).real))


def _gate_noise(rho: DensityMatrix, ins: Instruction, noise: NoiseModel) -> None:
    k = len(ins.qubits)
    if k == 1 and noise.p1 > 0:
        rho.apply_kraus(depolarizing_kraus(noise.p1), ins.qubits)
    elif k == 2 and noise.p2 > 0:
        rho.apply_kraus(depolarizing2_kraus(noise.p2), ins.qubits)
    elif k > 2 and noise.p2 > 0:
        for q in ins.qubits:
            rho.apply_kraus(depolarizing_kraus(noise.p2), (q,))
    if noise.idle_noise and (noise.t1 or noise.t2):
        t = noise.gate_time_1q if k == 1 else noise.gate_time_2q * max(1, k - 1)
        _relax(rho, ins.qubits, t, noise)


def _relax(rho: DensityMatrix, qubits: Sequence[int], t: float, noise: NoiseModel) -> None:
    gamma, lam = thermal_relaxation_params(t, noise.t1, noise.t2)
    for q in qubits:
        if gamma > 0:
            rho.apply_kraus(amplitude_damping_kraus(gamma), (q,))
        if lam > 0:
            rho.apply_kraus(phase_damping_kraus(lam), (q,))


def evolve_density(circuit: Circuit, noise: Optional[NoiseModel] = None):
    """Return list of (weight, DensityMatrix, cbits) branches and terminal measurements."""
    noise = noise or NoiseModel("ideal")
    n = circuit.num_qubits
    terminal_pos = _terminal_measurements(circuit)
    terminal: list[tuple[int, int]] = []
    branches = [(1.0, DensityMatrix(n), 0)]
    for pos, ins in enumerate(circuit.instructions):
        if ins.name == "barrier":
            continue
        if pos in terminal_pos:
            terminal.append((ins.qubits[0], ins.clbits[0]))
            continue
        new = []
        for w, rho, cb in branches:
            if not _condition_ok(cb, ins.condition):
                new.append((w, rho, cb))
                continue
            if ins.name == "delay":
                _relax(rho, ins.qubits, ins.params[0], noise)
                new.append((w, rho, cb))
            elif ins.name in ("measure", "reset"):
                q = ins.qubits[0]
                p1 = rho.prob_one(q)
                for outcome, p in ((0, 1 - p1), (1, p1)):
                    if p <= 1e-14:
                        continue
                    r2 = rho.copy()
                    r2.project(q, outcome)
                    cb2 = cb
                    if ins.name == "measure":
                        c = ins.clbits[0]
                        cb2 = (cb & ~(1 << c)) | (outcome << c)
                    elif outcome == 1:
                        r2.apply_gate("x", (q,))
                    new.append((w * p, r2, cb2))
            else:
                rho.apply_gate(ins.name, ins.qubits, ins.params, ins.ctrl_state)
                _gate_noise(rho, ins, noise)
                new.append((w, rho, cb))
        branches = new
    return branches, terminal


def density_distribution(circuit: Circuit, noise: Optional[NoiseModel] = None) -> dict[str, float]:
    noise = noise or NoiseModel("ideal")
    branches, terminal = evolve_density(circuit, noise)
    width = circuit.num_clbits
    p01, p10 = noise.readout
    out: dict[str, float] = {}
    for w, rho, cb in branches:
        base = cb
        for _, c in terminal:
            base &= ~(1 << c)
        probs = rho.probabilities()
        tot = probs.sum()
        if tot <= 0:
            continue
        probs = probs / tot
        for i in np.nonzero(probs > 1e-14)[0]:
            v = base
            for q, c in terminal:
                v |= ((int(i) >> q) & 1) << c
            key = format(v, f"0{width}b") if width else ""
            out[key] = out.get(key, 0.0) + w * float(probs[i])
    if (p01 or p10) and width:
        measured = sorted(set(circuit.measured_qubits()))
        for c in measured:
            nxt: dict[str, float] = {}
            for key, p in out.items():
                bit = key[width - 1 - c]
                flip_p = p01 if bit == "0" else p10
                flipped = key[: width - 1 - c] + ("1" if bit == "0" else "0") + key[width - c:]
                nxt[key] = nxt.get(key, 0.0) + p * (1 - flip_p)
                if flip_p:
                    nxt[flipped] = nxt.get(flipped, 0.0) + p * flip_p
            out = nxt
    total = sum(out.values()) or 1.0
    return {k: v / total for k, v in sorted(out.items())}


def simulate_density(circuit: Circuit, shots: int = 1024, noise: Optional[NoiseModel] = None,
                     seed: Optional[int] = None, memory: bool = False) -> CircuitResult:
    dist = density_distribution(circuit, noise)
    rng = np.random.default_rng(seed)
    keys = list(dist)
    width = circuit.num_clbits
    if not keys:
        keys, probs = [""], np.array([1.0])
    else:
        probs = np.array([dist[k] for k in keys])
        probs = probs / probs.sum()
    idx = rng.choice(len(keys), size=shots, p=probs)
    vals = np.array([int(keys[i], 2) if keys[i] else 0 for i in idx], dtype=np.int64)
    counts = counts_from_samples(vals, width) if width else {"": shots}
    mem = [format(int(v), f"0{width}b") for v in vals] if memory else None
    return CircuitResult(counts=counts, shots=shots, num_clbits=width,
                         registers=[(r.name, r.start, r.size) for r in circuit.cregs], memory=mem,
                         metadata={"simulator": "qplay-density", "noise": (noise or NoiseModel()).name})
