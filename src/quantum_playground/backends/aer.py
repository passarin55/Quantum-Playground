"""Qiskit Aer backend (optional dependency), ideal or with an IBM fake-device noise model."""
from __future__ import annotations

from typing import Optional, Sequence

from ..core.circuit import Circuit
from .base import Backend, CompletedJob, DeviceInfo, Job
from .qiskit_bridge import pub_to_result, to_qiskit


class AerBackend(Backend):
    provider = "aer"
    max_qubits = 32

    def __init__(self, noise_device: Optional[str] = None, method: str = "automatic", seed: Optional[int] = None):
        self.noise_device = noise_device
        self.method = method
        self.seed = seed
        self.name = f"aer:{noise_device}" if noise_device else "aer"
        self._sim = None
        self._device = None

    @property
    def simulator(self):
        if self._sim is None:
            from qiskit_aer import AerSimulator
            if self.noise_device:
                from .ibm import fake_backend
                self._device = fake_backend(self.noise_device)
                self._sim = AerSimulator.from_backend(self._device, method=self.method)
            else:
                self._sim = AerSimulator(method=self.method)
        return self._sim

    def run(self, circuits: Sequence[Circuit], shots: int = 1024, *, memory: bool = False,
            confirm: bool = False, **options) -> Job:
        from qiskit.transpiler import generate_preset_pass_manager
        from qiskit_aer.primitives import SamplerV2
        sim = self.simulator
        pm = generate_preset_pass_manager(backend=sim, optimization_level=1, seed_transpiler=11)
        isas = [pm.run(to_qiskit(c)) for c in circuits]
        seed = options.get("seed", self.seed)
        sampler = SamplerV2.from_backend(sim, seed=seed) if hasattr(SamplerV2, "from_backend") else SamplerV2(seed=seed)
        res = sampler.run(isas, shots=int(shots)).result()
        out = [pub_to_result(pub, [(r.name, r.start, r.size) for r in c.cregs], {"backend": self.name})
               for pub, c in zip(res, circuits)]
        return CompletedJob(self.name, self.provider, out)

    def info(self) -> DeviceInfo:
        desc = ("Qiskit Aer with the calibrated noise model of " + self.noise_device) if self.noise_device \
            else "Qiskit Aer ideal simulator"
        return DeviceInfo(self.name, self.provider, self.max_qubits, True, description=desc)
