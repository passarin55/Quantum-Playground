"""Built-in simulators (numpy only)."""
from __future__ import annotations

from typing import Optional, Sequence

from ..core.circuit import Circuit
from ..core.density import MAX_DENSITY_QUBITS, simulate_density
from ..core.noise import NoiseModel
from ..core.statevector import MAX_QUBITS, simulate
from .base import Backend, CompletedJob, DeviceInfo, Job


class StatevectorBackend(Backend):
    """Exact, noise-free statevector simulation (up to 26 qubits)."""

    provider = "local"
    max_qubits = MAX_QUBITS

    def __init__(self, seed: Optional[int] = None):
        self.name = "local"
        self.seed = seed

    def run(self, circuits: Sequence[Circuit], shots: int = 1024, *, memory: bool = False,
            confirm: bool = False, **options) -> Job:
        seed = options.get("seed", self.seed)
        results = []
        for i, c in enumerate(circuits):
            s = None if seed is None else seed + i
            results.append(simulate(c, shots=shots, seed=s, memory=memory))
        return CompletedJob(self.name, self.provider, results)

    def info(self) -> DeviceInfo:
        return DeviceInfo(self.name, self.provider, self.max_qubits, True,
                          description="Exact statevector simulator with dynamic-circuit support (numpy)")


class DensityBackend(Backend):
    """Density-matrix simulation with a NoiseModel (up to 11 qubits)."""

    provider = "local"
    max_qubits = MAX_DENSITY_QUBITS

    def __init__(self, noise: Optional[NoiseModel] = None, seed: Optional[int] = None):
        self.noise = noise or NoiseModel.preset("heron_like")
        self.name = f"local-noisy:{self.noise.name}"
        self.seed = seed

    def run(self, circuits: Sequence[Circuit], shots: int = 1024, *, memory: bool = False,
            confirm: bool = False, **options) -> Job:
        seed = options.get("seed", self.seed)
        results = [simulate_density(c, shots, self.noise, None if seed is None else seed + i, memory)
                   for i, c in enumerate(circuits)]
        return CompletedJob(self.name, self.provider, results)

    def info(self) -> DeviceInfo:
        return DeviceInfo(self.name, self.provider, self.max_qubits, True,
                          description=f"Density-matrix simulator, noise preset {self.noise.name}: "
                                      f"{self.noise.description}", extra={"noise": self.noise.to_dict()})
