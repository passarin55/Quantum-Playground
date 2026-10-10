"""IBM Quantum Platform backend (Qiskit Runtime SamplerV2).

Features
--------
* Credential resolution via ``quantum_playground.config`` (session, env, .env,
  saved Qiskit account).  Tokens are never persisted by this module.
* ``ibm:<name>`` real device, ``ibm:least_busy`` automatic choice, and
  ``ibm:fake_<name>`` *local testing mode*: the same code path (transpile to
  the device's ISA, SamplerV2, result parsing) executed on Aer with the fake
  device's calibrated noise model — no account, no network, no cost.
* Multi-seed transpilation (keeps the seed with the fewest native two-qubit
  gates, then depth) — carried over from v8 and generalised to all circuits.
* Preflight safety caps on native two-qubit gates, depth and shots×circuits;
  a real-QPU submission additionally requires ``confirm=True``.
* Error-suppression switches: dynamical decoupling, gate / measurement
  twirling.  Execution modes: ``job`` (default, Open plan friendly) or ``batch``.
* Per-circuit layout tracking so readout-error calibration circuits are pinned
  to exactly the physical qubits the experiment measured.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

from ..config import IBMCredentials, default_ibm_backend, ibm_credentials
from ..core.circuit import Circuit
from ..core.results import CircuitResult
from .base import Backend, DeviceInfo, Job, JobStatus, PreflightReport, SubmissionBlocked
from .qiskit_bridge import isa_metrics, measured_physical_qubits, pub_to_result, to_qiskit

_CONTROL_FLOW = {"if_else", "for_loop", "while_loop", "switch_case", "box"}


@dataclass
class IBMOptions:
    optimization_level: int = 2
    seeds: tuple[int, ...] = (11, 23, 37)
    max_two_qubit: int = 3000            # per circuit, native two-qubit gates
    max_depth: int = 20000
    max_total_shots: int = 2_000_000     # shots x circuits
    dynamical_decoupling: bool = False
    dd_sequence: str = "XpXm"
    twirling: bool = False
    measure_twirling: bool = False
    execution_mode: str = "job"          # job | batch
    override_caps: bool = False

    @staticmethod
    def from_dict(d: Optional[dict]) -> "IBMOptions":
        d = dict(d or {})
        if "seeds" in d and isinstance(d["seeds"], int):
            d["seeds"] = (11, 23, 37, 41, 53)[: max(1, min(5, d["seeds"]))]
        if "seeds" in d:
            d["seeds"] = tuple(int(s) for s in d["seeds"])
        known = {k: v for k, v in d.items() if k in IBMOptions.__dataclass_fields__}
        return IBMOptions(**known)


def _service(creds: IBMCredentials):
    from qiskit_ibm_runtime import QiskitRuntimeService
    kwargs = {}
    if creds.token:
        kwargs = {"channel": creds.channel, "token": creds.token}
    if creds.instance:
        kwargs["instance"] = creds.instance
    return QiskitRuntimeService(**kwargs)


_SERVICE_CACHE: dict[tuple, object] = {}


def get_service(creds: Optional[IBMCredentials] = None):
    creds = creds or ibm_credentials()
    key = (creds.token, creds.instance, creds.channel)
    if key not in _SERVICE_CACHE:
        _SERVICE_CACHE[key] = _service(creds)
    return _SERVICE_CACHE[key]


def fake_backend(name: str):
    from qiskit_ibm_runtime.fake_provider import FakeProviderForBackendV2
    prov = FakeProviderForBackendV2()
    name = name if name.startswith("fake_") else "fake_" + name
    try:
        return prov.backend(name)
    except Exception as exc:
        names = sorted(b.name for b in prov.backends())
        raise ValueError(f"Unknown fake backend {name!r}. Available: {', '.join(names)}") from exc


def list_fake_backends() -> list[str]:
    from qiskit_ibm_runtime.fake_provider import FakeProviderForBackendV2
    return sorted(b.name for b in FakeProviderForBackendV2().backends())


class IBMJob(Job):
    provider = "ibm"

    def __init__(self, runtime_job, backend_name: str, registers: Optional[list] = None, local: bool = False):
        self._job = runtime_job
        self.job_id = runtime_job.job_id()
        self.backend_name = backend_name
        self.registers = registers  # per circuit list of (name, start, size)
        self.local = local

    def status(self) -> JobStatus:
        return JobStatus.parse(self._job.status())

    def results(self, timeout: Optional[float] = None) -> list[CircuitResult]:
        res = self._job.result(timeout=timeout) if timeout is not None and not self.local else self._job.result()
        out = []
        for i, pub in enumerate(res):
            regs = self.registers[i] if self.registers and i < len(self.registers) else None
            meta = {"backend": self.backend_name, "job_id": self.job_id}
            try:
                meta["execution"] = {k: str(v) for k, v in dict(pub.metadata).items()}
            except Exception:
                pass
            out.append(pub_to_result(pub, regs, meta))
        return out

    def error_message(self) -> Optional[str]:
        try:
            return self._job.error_message()
        except Exception:
            return None

    def info(self) -> dict:
        d = super().info()
        d["local_testing"] = self.local
        return d


class IBMQuantumBackend(Backend):
    provider = "ibm"
    supports_dynamic = True

    def __init__(self, backend_name: Optional[str] = None, credentials: Optional[IBMCredentials] = None,
                 options: Optional[IBMOptions] = None, min_qubits: int = 1):
        self.requested = backend_name or default_ibm_backend() or "least_busy"
        self.credentials = credentials
        self.options = options or IBMOptions()
        self.min_qubits = min_qubits
        self.local_testing = self.requested.startswith("fake_")
        self.is_simulator = self.local_testing
        self.is_remote = not self.local_testing
        self._backend = None
        self._isa_cache: dict[int, object] = {}
        self.name = f"ibm:{self.requested}"

    # ------------------------------------------------------------ resolution
    @property
    def service(self):
        if self.local_testing:
            raise RuntimeError("Local testing mode has no runtime service")
        return get_service(self.credentials)

    @property
    def backend(self):
        if self._backend is None:
            if self.local_testing:
                self._backend = fake_backend(self.requested)
            elif self.requested in ("least_busy", "auto"):
                self._backend = self.service.least_busy(operational=True, simulator=False,
                                                        min_num_qubits=self.min_qubits)
            else:
                self._backend = self.service.backend(self.requested)
            self.name = f"ibm:{self._backend.name}"
        return self._backend

    @property
    def max_qubits(self) -> int:  # type: ignore[override]
        return int(self.backend.num_qubits)

    # ------------------------------------------------------------ transpilation
    def transpile(self, circuits: Sequence[Circuit], physical_layouts: Optional[Sequence[Optional[list]]] = None):
        """Return (isa_circuits, per-circuit metric dicts)."""
        from qiskit.transpiler import generate_preset_pass_manager
        isas, reports = [], []
        lvl = self.options.optimization_level
        for idx, c in enumerate(circuits):
            qc = to_qiskit(c)
            layout = physical_layouts[idx] if physical_layouts else None
            best = None
            alternatives = []
            for seed in self.options.seeds:
                pm = generate_preset_pass_manager(backend=self.backend, optimization_level=lvl,
                                                  seed_transpiler=seed, initial_layout=layout)
                isa = pm.run(qc)
                m = isa_metrics(isa)
                twoq = m["two_qubit"] + m["multi_qubit"]
                alternatives.append({"seed": seed, "two_qubit": twoq, "depth": m["depth"]})
                score = (twoq, m["depth"], m["size"])
                if best is None or score < best[0]:
                    best = (score, seed, isa, m)
                if layout is not None:
                    break
            _, seed, isa, m = best
            m.update({"name": c.name, "best_seed": seed, "seed_alternatives": alternatives,
                      "logical": c.gate_profile(),
                      "measured_physical": measured_physical_qubits(isa)})
            m["control_flow"] = sum(v for k, v in m["ops"].items() if k in _CONTROL_FLOW)
            m["error_estimate"] = self._error_product(isa)
            isas.append(isa)
            reports.append(m)
        return isas, reports

    def _error_product(self, isa) -> Optional[float]:
        """Product of (1 - error) over calibrated ops — an *illustration*, not a fidelity."""
        try:
            target = self.backend.target
        except Exception:
            return None
        logp, n = 0.0, 0
        for item in isa.data:
            op = item.operation
            if op.name in ("barrier", "delay") or op.name in _CONTROL_FLOW:
                continue
            phys = tuple(isa.find_bit(q).index for q in item.qubits)
            try:
                props = target[op.name][phys]
                err = getattr(props, "error", None)
            except Exception:
                err = None
            if isinstance(err, (int, float)) and 0 <= err < 1:
                logp += math.log(max(1e-300, 1 - err))
                n += 1
        return math.exp(logp) if n else None

    def preflight(self, circuits: Sequence[Circuit], shots: int = 1024, physical_layouts=None, **_) -> PreflightReport:
        isas, reports = self.transpile(circuits, physical_layouts)
        self._last_isas = isas
        rep = PreflightReport(self.name, reports, settings={
            "optimization_level": self.options.optimization_level, "seeds": list(self.options.seeds),
            "caps": {"max_two_qubit": self.options.max_two_qubit, "max_depth": self.options.max_depth,
                     "max_total_shots": self.options.max_total_shots},
            "local_testing": self.local_testing, "num_qubits": self.max_qubits})
        for r in reports:
            twoq = r["two_qubit"] + r["multi_qubit"]
            if twoq > self.options.max_two_qubit:
                rep.reasons.append(f"{r['name']}: {twoq} native two-qubit gates > cap {self.options.max_two_qubit}")
            if r["depth"] > self.options.max_depth:
                rep.reasons.append(f"{r['name']}: depth {r['depth']} > cap {self.options.max_depth}")
            est = r.get("error_estimate")
            if est is not None and est < 0.05:
                rep.warnings.append(f"{r['name']}: calibration error product {est:.2e} — expect near-random output")
        if shots * len(circuits) > self.options.max_total_shots:
            rep.reasons.append(f"shots x circuits = {shots * len(circuits)} > cap {self.options.max_total_shots}")
        if rep.reasons and not self.options.override_caps:
            rep.blocked = True
        elif rep.reasons:
            rep.warnings.extend(f"cap overridden: {r}" for r in rep.reasons)
        return rep

    def measured_layout(self, circuit: Circuit) -> dict[int, int]:
        isas, reports = self.transpile([circuit])
        return reports[0]["measured_physical"]

    # ------------------------------------------------------------ execution
    def _sampler(self):
        from qiskit_ibm_runtime import Batch, SamplerV2
        mode = self.backend
        if self.options.execution_mode == "batch" and not self.local_testing:
            mode = Batch(backend=self.backend)
        sampler = SamplerV2(mode=mode)
        if not self.local_testing:
            if self.options.dynamical_decoupling:
                sampler.options.dynamical_decoupling.enable = True
                sampler.options.dynamical_decoupling.sequence_type = self.options.dd_sequence
            if self.options.twirling or self.options.measure_twirling:
                sampler.options.twirling.enable_gates = bool(self.options.twirling)
                sampler.options.twirling.enable_measure = bool(self.options.measure_twirling)
        return sampler

    def run(self, circuits: Sequence[Circuit], shots: int = 1024, *, memory: bool = False,
            confirm: bool = False, isa_circuits=None, preflight: Optional[PreflightReport] = None,
            **options) -> IBMJob:
        if self.is_remote and not confirm:
            raise PermissionError("Real-QPU submission requires confirm=True (CLI: --yes). "
                                  "Run a preflight / dry run first to inspect native gate counts.")
        if isa_circuits is None:
            preflight = self.preflight(circuits, shots)
            isa_circuits = self._last_isas
        if preflight is not None and preflight.blocked:
            raise SubmissionBlocked(preflight)
        sampler = self._sampler()
        job = sampler.run(list(isa_circuits), shots=int(shots))
        regs = [[(r.name, r.start, r.size) for r in c.cregs] for c in circuits]
        return IBMJob(job, self.backend.name, regs, local=self.local_testing)

    def retrieve_job(self, job_id: str, registers: Optional[list] = None) -> IBMJob:
        job = self.service.job(job_id)
        try:
            name = job.backend().name
        except Exception:
            name = self.requested
        return IBMJob(job, name, registers)

    # ------------------------------------------------------------ account queries
    def devices(self) -> list[DeviceInfo]:
        if self.local_testing:
            return [self.info()]
        out = []
        for b in self.service.backends(simulator=False):
            try:
                st = b.status()
                op, pend = bool(st.operational), int(st.pending_jobs)
            except Exception:
                op, pend = True, None
            out.append(DeviceInfo(b.name, "ibm", int(b.num_qubits), False, op, pend,
                                  extra={"processor": str(getattr(b, "processor_type", "") or "")}))
        return sorted(out, key=lambda d: (not d.operational, d.pending_jobs or 0))

    def usage(self) -> dict:
        return dict(self.service.usage())

    def info(self) -> DeviceInfo:
        b = self.backend
        try:
            st = b.status()
            op, pend = bool(st.operational), int(st.pending_jobs)
        except Exception:
            op, pend = True, None
        basis = sorted(getattr(b, "operation_names", []) or [])
        return DeviceInfo(f"ibm:{b.name}", "ibm", int(b.num_qubits), self.local_testing, op, pend,
                          description=("Local testing mode: fake device noise model on Aer"
                                       if self.local_testing else "IBM Quantum QPU"),
                          extra={"basis_gates": basis})


def save_account(token: str, instance: Optional[str] = None, channel: str = "ibm_quantum_platform",
                 overwrite: bool = True) -> None:
    """Persist credentials with Qiskit's own account store (~/.qiskit), never in this repo."""
    from qiskit_ibm_runtime import QiskitRuntimeService
    kwargs = {"channel": channel, "token": token, "overwrite": overwrite, "set_as_default": True}
    if instance:
        kwargs["instance"] = instance
    QiskitRuntimeService.save_account(**kwargs)
