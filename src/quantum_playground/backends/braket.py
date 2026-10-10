"""Amazon Braket backend via OpenQASM 3 (optional ``amazon-braket-sdk``).

``braket:local`` runs the Braket local state-vector simulator (no AWS account);
``braket:<device ARN>`` submits to a managed device using the standard AWS
credential chain.  Circuits are exported with the Braket gate dialect and
multi-controlled gates as ``ctrl(k) @`` / ``negctrl @`` modifiers; for QPUs we
first lower them with Qiskit to 1q + CX + CCX so the device compiler accepts
them.  Dynamic circuits (mid-circuit feed-forward) are rejected.
"""
from __future__ import annotations

from typing import Optional, Sequence

from ..core.circuit import Circuit
from ..core.qasm import to_qasm3
from ..core.results import CircuitResult
from .base import Backend, CompletedJob, DeviceInfo, Job, JobStatus

_BRAKET_BASIS = ["x", "y", "z", "h", "s", "sdg", "t", "tdg", "rx", "ry", "rz", "cx", "cz", "swap", "ccx"]


def _lower_for_qpu(circuit: Circuit) -> Circuit:
    from qiskit import transpile
    from .qiskit_bridge import from_qiskit, to_qiskit
    qc = transpile(to_qiskit(circuit), basis_gates=_BRAKET_BASIS + ["measure"], optimization_level=1)
    out = from_qiskit(qc)
    out.metadata = dict(circuit.metadata)
    return out


def _to_result(circuit: Circuit, task_result) -> CircuitResult:
    measured = list(task_result.measured_qubits)
    layout = circuit.measured_qubits()  # clbit -> qubit
    width = circuit.num_clbits
    memory = []
    for row in task_result.measurements:
        bits = ["0"] * width
        for c, q in layout.items():
            bits[width - 1 - c] = str(int(row[measured.index(q)]))
        memory.append("".join(bits))
    counts: dict[str, int] = {}
    for m in memory:
        counts[m] = counts.get(m, 0) + 1
    return CircuitResult(dict(sorted(counts.items())), len(memory), width,
                         [(r.name, r.start, r.size) for r in circuit.cregs], memory,
                         {"backend": "braket", "task_id": getattr(task_result, "task_metadata", None) and
                          task_result.task_metadata.id})


class BraketJob(Job):
    provider = "braket"

    def __init__(self, tasks, circuits: Sequence[Circuit], backend_name: str):
        self._tasks = list(tasks)
        self._circuits = list(circuits)
        self.backend_name = backend_name
        self.job_id = ",".join(str(getattr(t, "id", f"local-{i}")) for i, t in enumerate(self._tasks))

    def status(self) -> JobStatus:
        states = [JobStatus.parse(t.state()) for t in self._tasks]
        if all(s == JobStatus.DONE for s in states):
            return JobStatus.DONE
        for s in (JobStatus.ERROR, JobStatus.CANCELLED, JobStatus.RUNNING, JobStatus.QUEUED):
            if s in states:
                return s
        return JobStatus.UNKNOWN

    def results(self, timeout: Optional[float] = None) -> list[CircuitResult]:
        return [_to_result(c, t.result()) for c, t in zip(self._circuits, self._tasks)]


class BraketBackend(Backend):
    provider = "braket"
    supports_dynamic = False

    def __init__(self, device: str = "local", lower: bool = True):
        self.device_id = device
        # Lowering to 1q + CX + CCX avoids large ctrl(k)@ modifier gates, which some
        # Braket simulator versions mishandle for >= 12 qubits; QPUs always need it.
        self.lower = lower or device != "local"
        self.is_remote = device != "local"
        self.is_simulator = not self.is_remote or "simulator" in device
        self.name = f"braket:{device if device == 'local' else device.split('/')[-1]}"
        self.max_qubits = 25 if device == "local" else 128
        self._device = None

    @property
    def device(self):
        if self._device is None:
            if self.device_id == "local":
                from braket.devices import LocalSimulator
                self._device = LocalSimulator()
            else:
                from braket.aws import AwsDevice
                self._device = AwsDevice(self.device_id)
        return self._device

    def program(self, circuit: Circuit) -> str:
        c = _lower_for_qpu(circuit) if self.lower else circuit
        return to_qasm3(c, dialect="braket")

    def run(self, circuits: Sequence[Circuit], shots: int = 1024, *, memory: bool = False,
            confirm: bool = False, **options) -> Job:
        from braket.ir.openqasm import Program
        if self.is_remote and not confirm:
            raise PermissionError("Braket device submission requires confirm=True (charges may apply)")
        rep = self.preflight(circuits)
        if rep.blocked:
            raise RuntimeError("; ".join(rep.reasons))
        tasks = [self.device.run(Program(source=self.program(c)), shots=int(shots)) for c in circuits]
        job = BraketJob(tasks, circuits, self.name)
        if not self.is_remote:
            return CompletedJob(self.name, self.provider, job.results())
        return job

    def info(self) -> DeviceInfo:
        return DeviceInfo(self.name, self.provider, self.max_qubits, self.is_simulator,
                          description="Amazon Braket " + ("local simulator" if self.device_id == "local"
                                                          else f"device {self.device_id}"))
