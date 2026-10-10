"""Backend abstraction shared by local simulators and cloud QPUs."""
from __future__ import annotations

import abc
import enum
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Optional, Sequence

from ..core.circuit import Circuit
from ..core.results import CircuitResult


class JobStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    DONE = "DONE"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"

    @property
    def final(self) -> bool:
        return self in (JobStatus.DONE, JobStatus.ERROR, JobStatus.CANCELLED)

    @staticmethod
    def parse(raw) -> "JobStatus":
        s = str(getattr(raw, "name", raw)).upper()
        if "DONE" in s or "COMPLETED" in s:
            return JobStatus.DONE
        if "ERROR" in s or "FAIL" in s:
            return JobStatus.ERROR
        if "CANCEL" in s:
            return JobStatus.CANCELLED
        if "RUN" in s:
            return JobStatus.RUNNING
        if "QUEUE" in s or "INITIALIZ" in s or "VALIDAT" in s or "CREATED" in s:
            return JobStatus.QUEUED
        return JobStatus.UNKNOWN


@dataclass
class DeviceInfo:
    name: str
    provider: str
    num_qubits: int
    simulator: bool
    operational: bool = True
    pending_jobs: Optional[int] = None
    description: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PreflightReport:
    backend: str
    circuits: list[dict]
    warnings: list[str] = field(default_factory=list)
    blocked: bool = False
    reasons: list[str] = field(default_factory=list)
    settings: dict = field(default_factory=dict)

    @property
    def total_two_qubit(self) -> int:
        return sum(c.get("two_qubit", 0) + c.get("multi_qubit", 0) for c in self.circuits)

    @property
    def max_depth(self) -> int:
        return max((c.get("depth", 0) for c in self.circuits), default=0)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["total_two_qubit"] = self.total_two_qubit
        d["max_depth"] = self.max_depth
        return d


class SubmissionBlocked(RuntimeError):
    def __init__(self, report: PreflightReport):
        super().__init__("; ".join(report.reasons) or "submission blocked by preflight")
        self.report = report


class Job(abc.ABC):
    job_id: str
    backend_name: str
    provider: str

    @abc.abstractmethod
    def status(self) -> JobStatus: ...

    @abc.abstractmethod
    def results(self, timeout: Optional[float] = None) -> list[CircuitResult]: ...

    def wait(self, timeout: float = 600, poll: float = 2.0) -> JobStatus:
        start = time.time()
        while True:
            st = self.status()
            if st.final or time.time() - start > timeout:
                return st
            time.sleep(poll)

    def info(self) -> dict:
        return {"job_id": self.job_id, "backend": self.backend_name, "provider": self.provider}


class CompletedJob(Job):
    """A job whose results are already in memory (local simulators)."""

    def __init__(self, backend_name: str, provider: str, results: list[CircuitResult],
                 job_id: Optional[str] = None):
        self.job_id = job_id or f"local-{uuid.uuid4().hex[:12]}"
        self.backend_name, self.provider = backend_name, provider
        self._results = results

    def status(self) -> JobStatus:
        return JobStatus.DONE

    def results(self, timeout: Optional[float] = None) -> list[CircuitResult]:
        return self._results


class Backend(abc.ABC):
    name: str = "backend"
    provider: str = "local"
    is_simulator: bool = True
    is_remote: bool = False
    supports_dynamic: bool = True
    max_qubits: int = 26

    @abc.abstractmethod
    def run(self, circuits: Sequence[Circuit], shots: int = 1024, *, memory: bool = False,
            confirm: bool = False, **options) -> Job: ...

    def preflight(self, circuits: Sequence[Circuit], **options) -> PreflightReport:
        rep = PreflightReport(self.name, [c.gate_profile() for c in circuits])
        for c in circuits:
            if c.num_qubits > self.max_qubits:
                rep.blocked = True
                rep.reasons.append(f"{c.name}: {c.num_qubits} qubits exceeds {self.name} limit {self.max_qubits}")
            if not self.supports_dynamic and c.has_dynamic_features():
                rep.blocked = True
                rep.reasons.append(f"{c.name}: mid-circuit measurement/feed-forward not supported on {self.name}")
        return rep

    def measured_layout(self, circuit: Circuit) -> dict[int, int]:
        """clbit -> (physical) qubit; identity layout for simulators."""
        return circuit.measured_qubits()

    def retrieve_job(self, job_id: str) -> Job:
        raise NotImplementedError(f"{self.name} cannot retrieve jobs by id")

    def info(self) -> DeviceInfo:
        return DeviceInfo(self.name, self.provider, self.max_qubits, self.is_simulator)
