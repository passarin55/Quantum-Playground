"""Tensored readout-error mitigation (M3-style local assignment model).

For each measured qubit q we estimate a 2x2 assignment matrix
``A_q[measured, prepared]`` from two calibration circuits (all |0> and all
|1>).  Noisy probabilities are corrected by applying ``A_q^{-1}`` along every
bit axis, then projected onto the closest valid probability distribution
(Smolin–Gambetta–Smith, PRL 108, 070502).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np

from .circuit import Circuit
from .results import CircuitResult


def calibration_circuits(qubits: Sequence[int], num_qubits: int) -> list[Circuit]:
    out = []
    for prep in (0, 1):
        qc = Circuit(num_qubits, name=f"readout_cal_{prep}")
        reg = qc.add_creg("cal", len(qubits))
        if prep:
            qc.x(list(qubits))
        qc.measure(list(qubits), reg)
        qc.metadata["calibration"] = {"prepared": prep, "qubits": list(qubits)}
        out.append(qc)
    return out


def nearest_probability(quasi: np.ndarray) -> np.ndarray:
    """Closest probability vector in L2 (Smolin-Gambetta-Smith)."""
    q = np.asarray(quasi, dtype=float)
    order = np.argsort(q)
    vals = q[order].copy()
    acc = 0.0
    n = len(vals)
    i = 0
    while i < n and vals[i] + acc / (n - i) < 0:
        acc += vals[i]
        vals[i] = 0.0
        i += 1
    if i < n:
        vals[i:] += acc / (n - i)
    out = np.zeros_like(q)
    out[order] = vals
    s = out.sum()
    return out / s if s > 0 else out


@dataclass
class ReadoutMitigator:
    assignment: dict[int, np.ndarray] = field(default_factory=dict)  # qubit -> A[meas, prep]

    @classmethod
    def from_results(cls, qubits: Sequence[int], cal0: CircuitResult, cal1: CircuitResult) -> "ReadoutMitigator":
        mats = {}
        for j, q in enumerate(qubits):
            p1_given0 = _bit_freq(cal0, j)
            p1_given1 = _bit_freq(cal1, j)
            mats[int(q)] = np.array([[1 - p1_given0, 1 - p1_given1], [p1_given0, p1_given1]])
        return cls(mats)

    def error_rates(self) -> dict[int, tuple[float, float]]:
        return {q: (float(a[1, 0]), float(a[0, 1])) for q, a in self.assignment.items()}

    def apply(self, counts: Mapping[str, int], clbit_qubits: Sequence[int]) -> dict[str, float]:
        """Mitigate counts whose clbit j was measured from qubit ``clbit_qubits[j]``.

        Returns a corrected probability distribution over the same bitstrings.
        """
        m = len(clbit_qubits)
        if m > 16:
            raise ValueError("Tensored mitigation limited to 16 measured bits")
        total = sum(counts.values())
        vec = np.zeros(1 << m)
        for k, c in counts.items():
            vec[int(k.replace(" ", ""), 2)] += c / total
        t = vec.reshape((2,) * m)
        for j, q in enumerate(clbit_qubits):
            a = self.assignment.get(int(q))
            if a is None:
                continue
            inv = np.linalg.inv(a)
            axis = m - 1 - j
            t = np.moveaxis(np.tensordot(inv, t, axes=([1], [axis])), 0, axis)
        fixed = nearest_probability(t.reshape(-1))
        return {format(i, f"0{m}b"): float(p) for i, p in enumerate(fixed) if p > 1e-12}

    def to_dict(self) -> dict:
        return {str(q): a.tolist() for q, a in self.assignment.items()}

    @classmethod
    def from_dict(cls, d: dict) -> "ReadoutMitigator":
        return cls({int(q): np.array(a) for q, a in d.items()})


def _bit_freq(res: CircuitResult, j: int) -> float:
    total = sum(res.counts.values())
    ones = sum(c for k, c in res.counts.items() if k.replace(" ", "")[-1 - j] == "1")
    return ones / total if total else 0.0
