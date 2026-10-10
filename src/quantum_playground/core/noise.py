"""Noise models and Kraus channels for the density-matrix simulator."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Optional

import numpy as np

from .gates import PAULI

_P = [PAULI["I"], PAULI["X"], PAULI["Y"], PAULI["Z"]]


def depolarizing_kraus(p: float) -> list[np.ndarray]:
    """Single-qubit depolarizing: rho -> (1-p) rho + p/3 (X rho X + Y rho Y + Z rho Z)."""
    p = float(p)
    if p <= 0:
        return [np.eye(2, dtype=complex)]
    return [math.sqrt(1 - p) * _P[0]] + [math.sqrt(p / 3) * P for P in _P[1:]]


def depolarizing2_kraus(p: float) -> list[np.ndarray]:
    """Two-qubit depolarizing channel over the 15 non-identity Pauli pairs."""
    p = float(p)
    out = []
    for a in range(4):
        for b in range(4):
            k = np.kron(_P[b], _P[a])  # qubit 0 = least significant
            w = (1 - p) if (a == 0 and b == 0) else p / 15
            if w > 0:
                out.append(math.sqrt(w) * k)
    return out


def amplitude_damping_kraus(gamma: float) -> list[np.ndarray]:
    g = float(gamma)
    return [np.array([[1, 0], [0, math.sqrt(1 - g)]], dtype=complex),
            np.array([[0, math.sqrt(g)], [0, 0]], dtype=complex)]


def phase_damping_kraus(lam: float) -> list[np.ndarray]:
    lam = float(lam)
    return [np.array([[1, 0], [0, math.sqrt(1 - lam)]], dtype=complex),
            np.array([[0, 0], [0, math.sqrt(lam)]], dtype=complex)]


def thermal_relaxation_params(t: float, t1: Optional[float], t2: Optional[float]) -> tuple[float, float]:
    """(gamma, lambda) for amplitude + pure-phase damping over duration t."""
    gamma = 0.0 if not t1 else 1 - math.exp(-t / t1)
    lam = 0.0
    if t2:
        inv_tphi = 1 / t2 - (1 / (2 * t1) if t1 else 0.0)
        if inv_tphi > 0:
            lam = 1 - math.exp(-2 * t * inv_tphi)
    return gamma, lam


@dataclass
class NoiseModel:
    """A compact, physically-motivated noise model.

    p1 / p2:        depolarizing probability after 1-qubit / 2-qubit gates.
                    Gates on k>2 qubits get independent p2 depolarizing on
                    each qubit (an approximation; documented in the report).
    readout:        (P(read 1 | 0), P(read 0 | 1)).
    t1 / t2:        relaxation times in seconds, applied to ``delay``
                    instructions and to gate durations if ``idle_noise``.
    """

    name: str = "custom"
    p1: float = 0.0
    p2: float = 0.0
    readout: tuple[float, float] = (0.0, 0.0)
    t1: Optional[float] = None
    t2: Optional[float] = None
    gate_time_1q: float = 36e-9
    gate_time_2q: float = 68e-9
    idle_noise: bool = False
    description: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["readout"] = list(self.readout)
        return d

    @staticmethod
    def from_dict(d: dict) -> "NoiseModel":
        d = dict(d)
        if "readout" in d:
            d["readout"] = tuple(d["readout"])
        return NoiseModel(**d)

    @property
    def is_ideal(self) -> bool:
        return (self.p1 == 0 and self.p2 == 0 and not any(self.readout)
                and not self.t1 and not self.t2)

    @staticmethod
    def preset(name: str) -> "NoiseModel":
        try:
            return NOISE_PRESETS[name]()
        except KeyError:
            raise ValueError(f"Unknown noise preset {name!r}; choose from {sorted(NOISE_PRESETS)}") from None


NOISE_PRESETS = {
    "ideal": lambda: NoiseModel("ideal", description="No noise"),
    "heron_like": lambda: NoiseModel(
        "heron_like", p1=3e-4, p2=4e-3, readout=(0.012, 0.02), t1=180e-6, t2=120e-6,
        description="Order-of-magnitude IBM Heron r2-class numbers (not a calibration snapshot)"),
    "eagle_like": lambda: NoiseModel(
        "eagle_like", p1=8e-4, p2=1.2e-2, readout=(0.02, 0.035), t1=250e-6, t2=150e-6,
        gate_time_2q=500e-9, description="Order-of-magnitude IBM Eagle-class numbers"),
    "trapped_ion_like": lambda: NoiseModel(
        "trapped_ion_like", p1=5e-5, p2=2e-3, readout=(0.003, 0.003), t1=None, t2=1.0,
        gate_time_1q=10e-6, gate_time_2q=300e-6, description="Trapped-ion-like: slow, high fidelity"),
    "noisy": lambda: NoiseModel("noisy", p1=5e-3, p2=5e-2, readout=(0.05, 0.08), t1=40e-6, t2=30e-6,
                                description="Deliberately bad device for teaching"),
}
