"""Backend registry.

Backend specs (strings) accepted everywhere (CLI, web studio, Python API):

=====================  =======================================================
``local``              exact statevector simulator (numpy, up to 26 qubits)
``local-noisy[:P]``    density-matrix simulator, noise preset P (default heron_like)
``aer``                Qiskit Aer ideal simulator
``aer:fake_fez``       Qiskit Aer with an IBM fake-device noise model
``ibm:fake_fez``       IBM Runtime *local testing mode* (exact IBM code path, offline)
``ibm``                IBM Quantum, least busy real device
``ibm:ibm_fez``        IBM Quantum, a named device
``braket:local``       Amazon Braket local simulator
``braket:<ARN>``       Amazon Braket managed device
=====================  =======================================================
"""
from __future__ import annotations

from typing import Optional

from ..config import package_available
from ..core.noise import NOISE_PRESETS, NoiseModel
from .base import Backend, CompletedJob, DeviceInfo, Job, JobStatus, PreflightReport, SubmissionBlocked
from .local import DensityBackend, StatevectorBackend


def get_backend(spec: str = "local", *, ibm_options: Optional[dict] = None, seed: Optional[int] = None,
                min_qubits: int = 1) -> Backend:
    spec = (spec or "local").strip()
    kind, _, arg = spec.partition(":")
    kind = kind.lower()
    if kind == "local":
        return StatevectorBackend(seed=seed)
    if kind in ("local-noisy", "noisy", "density"):
        return DensityBackend(NoiseModel.preset(arg or "heron_like"), seed=seed)
    if kind == "aer":
        if not package_available("qiskit_aer"):
            raise RuntimeError("Qiskit Aer not installed: pip install 'quantum-playground-studio[aer]'")
        from .aer import AerBackend
        return AerBackend(arg or None, seed=seed)
    if kind == "ibm":
        if not package_available("qiskit_ibm_runtime"):
            raise RuntimeError("qiskit-ibm-runtime not installed: pip install 'quantum-playground-studio[ibm]'")
        from .ibm import IBMOptions, IBMQuantumBackend
        return IBMQuantumBackend(arg or None, options=IBMOptions.from_dict(ibm_options), min_qubits=min_qubits)
    if kind == "braket":
        if not package_available("braket"):
            raise RuntimeError("amazon-braket-sdk not installed: pip install 'quantum-playground-studio[braket]'")
        from .braket import BraketBackend
        return BraketBackend(arg or "local")
    raise ValueError(f"Unknown backend spec {spec!r}")


def available_backends() -> list[dict]:
    """Catalogue for UIs: what can be selected and whether its SDK is installed."""
    have_aer = package_available("qiskit_aer")
    have_ibm = package_available("qiskit_ibm_runtime")
    have_braket = package_available("braket")
    out = [
        {"spec": "local", "label": "Local statevector (exact)", "available": True, "remote": False},
    ]
    for p in NOISE_PRESETS:
        if p != "ideal":
            out.append({"spec": f"local-noisy:{p}", "label": f"Local density matrix — {p}", "available": True,
                        "remote": False})
    out += [
        {"spec": "aer", "label": "Qiskit Aer (ideal)", "available": have_aer, "remote": False},
        {"spec": "aer:fake_fez", "label": "Qiskit Aer + ibm_fez noise model", "available": have_aer and have_ibm,
         "remote": False},
        {"spec": "ibm:fake_fez", "label": "IBM Runtime local testing — fake_fez (156q Heron)",
         "available": have_ibm and have_aer, "remote": False},
        {"spec": "ibm:fake_marrakesh", "label": "IBM Runtime local testing — fake_marrakesh",
         "available": have_ibm and have_aer, "remote": False},
        {"spec": "ibm", "label": "IBM Quantum — least busy QPU", "available": have_ibm, "remote": True},
        {"spec": "ibm:ibm_fez", "label": "IBM Quantum — ibm_fez", "available": have_ibm, "remote": True},
        {"spec": "ibm:ibm_marrakesh", "label": "IBM Quantum — ibm_marrakesh", "available": have_ibm, "remote": True},
        {"spec": "ibm:ibm_torino", "label": "IBM Quantum — ibm_torino", "available": have_ibm, "remote": True},
        {"spec": "braket:local", "label": "Amazon Braket local simulator", "available": have_braket and package_available("qiskit"),
         "remote": False},
    ]
    return out


__all__ = ["Backend", "CompletedJob", "DeviceInfo", "Job", "JobStatus", "PreflightReport", "SubmissionBlocked",
           "DensityBackend", "StatevectorBackend", "get_backend", "available_backends"]
