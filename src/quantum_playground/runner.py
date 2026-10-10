"""Execution orchestration: experiment -> backend -> (mitigation) -> analysis -> job store.

One code path serves the CLI, the web studio and the Python API:

>>> from quantum_playground.runner import Runner
>>> out = Runner().run("chsh", {}, backend="local")
>>> print(out.report_text)

Cloud submissions return immediately with a job id; ``Runner.refresh(job_id)``
polls the provider and, once the job is done, runs the stored analysis.
"""
from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from typing import Any, Optional

from .backends import CompletedJob, JobStatus, PreflightReport, SubmissionBlocked, get_backend
from .backends.jobstore import JobStore
from .core.circuit import Circuit
from .core.mitigation import ReadoutMitigator, calibration_circuits
from .core.results import CircuitResult
from .experiments import get_experiment
from .experiments.base import Report


@dataclass
class RunOutcome:
    job_id: str
    backend: str
    experiment: str
    status: str
    report: Optional[dict] = None
    preflight: Optional[dict] = None
    circuits: list[dict] = field(default_factory=list)
    message: str = ""
    results: Optional[list[dict]] = None

    @property
    def report_text(self) -> str:
        if not self.report:
            return f"[{self.status}] {self.message}"
        r = self.report
        rep = Report(r["title"], r.get("summary", []), r.get("metrics", {}), [], [], r.get("verdict"),
                     r.get("notes", []))
        from .experiments.base import Chart, Table
        rep.tables = [Table(**t) for t in r.get("tables", [])]
        rep.charts = [Chart(**c) for c in r.get("charts", [])]
        return rep.to_text()

    def to_dict(self) -> dict:
        return {"job_id": self.job_id, "backend": self.backend, "experiment": self.experiment,
                "status": self.status, "report": self.report, "preflight": self.preflight,
                "circuits": self.circuits, "message": self.message, "results": self.results}


class Runner:
    def __init__(self, store: Optional[JobStore] = None):
        self.store = store or JobStore()
        self._live_jobs: dict[str, Any] = {}

    # ------------------------------------------------------------------ planning
    def plan(self, experiment: str, params: Optional[dict] = None):
        exp = get_experiment(experiment)
        p = exp.resolve(params)
        plan = exp.build(p)
        return exp, p, plan

    def circuits(self, experiment: str, params: Optional[dict] = None) -> list[Circuit]:
        return self.plan(experiment, params)[2].circuits

    def preflight(self, experiment: str, params: Optional[dict] = None, backend: str = "local",
                  shots: Optional[int] = None, ibm_options: Optional[dict] = None) -> PreflightReport:
        exp, p, plan = self.plan(experiment, params)
        be = get_backend(backend, ibm_options=ibm_options, min_qubits=max(c.num_qubits for c in plan.circuits))
        shots = plan.shots or shots or exp.default_shots
        return be.preflight(plan.circuits, shots=shots)

    # ------------------------------------------------------------------ execution
    def run(self, experiment: str, params: Optional[dict] = None, backend: str = "local",
            shots: Optional[int] = None, *, confirm: bool = False, mitigate_readout: bool = False,
            ibm_options: Optional[dict] = None, seed: Optional[int] = None) -> RunOutcome:
        exp, p, plan = self.plan(experiment, params)
        shots = int(plan.shots or shots or exp.default_shots)
        circuits = list(plan.circuits)
        be = get_backend(backend, ibm_options=ibm_options, seed=seed,
                         min_qubits=max(c.num_qubits for c in circuits))
        mitigate = bool(mitigate_readout) and not plan.memory
        context = {"experiment_context": plan.context, "n_circuits": len(circuits), "memory": plan.memory}
        run_kwargs: dict = {"memory": plan.memory, "confirm": confirm}
        preflight = None
        is_ibm = be.provider == "ibm"

        if is_ibm:
            preflight = be.preflight(circuits, shots=shots)
            if preflight.blocked:
                raise SubmissionBlocked(preflight)
            isas = list(be._last_isas)
            layouts = [r["measured_physical"] for r in preflight.circuits]
        else:
            preflight = be.preflight(circuits)
            if preflight.blocked:
                raise SubmissionBlocked(preflight)
            isas = None
            layouts = [c.measured_qubits() for c in circuits]

        all_circuits = circuits
        if mitigate:
            phys = sorted({q for lay in layouts for q in lay.values()})
            if is_ibm:
                cals = calibration_circuits(list(range(len(phys))), len(phys))
                cal_isas, _ = be.transpile(cals, physical_layouts=[phys, phys])
                isas = isas + cal_isas
            else:
                width = max(c.num_qubits for c in circuits)
                cals = calibration_circuits(phys, width)
            all_circuits = circuits + cals
            context["mitigation"] = {"physical_qubits": phys,
                                     "layouts": [{str(k): v for k, v in lay.items()} for lay in layouts]}
        if is_ibm:
            run_kwargs.update(isa_circuits=isas, preflight=preflight)
        job = be.run(all_circuits, shots=shots, **run_kwargs)
        registers = [[(r.name, r.start, r.size) for r in c.cregs] for c in all_circuits]
        self.store.add(job.job_id, be.provider, be.name, experiment=exp.id, params=p, context=context,
                       registers=registers, shots=shots, status="QUEUED",
                       preflight=preflight.to_dict() if preflight else None,
                       extra={"remote": be.is_remote, "circuit_names": [c.name for c in all_circuits]})
        self._live_jobs[job.job_id] = job
        outcome = RunOutcome(job.job_id, be.name, exp.id, "QUEUED",
                             preflight=preflight.to_dict() if preflight else None,
                             circuits=[c.gate_profile() for c in circuits])
        if isinstance(job, CompletedJob) or not be.is_remote:
            return self._finalize(job.job_id, job.results())
        outcome.message = ("Submitted to the cloud. Refresh with `qplay jobs refresh "
                           f"{job.job_id}` or from the Jobs tab; results are analysed automatically.")
        return outcome

    # ------------------------------------------------------------------ polling
    def refresh(self, job_id: str) -> RunOutcome:
        rec = self.store.get(job_id)
        if rec is None:
            raise KeyError(f"Unknown job {job_id}")
        if rec["status"] == "DONE" and rec.get("report"):
            return self._outcome(rec)
        job = self._live_jobs.get(job_id)
        try:
            if job is None:
                be = get_backend(rec["backend"])
                if not hasattr(be, "retrieve_job"):
                    raise RuntimeError("backend cannot retrieve jobs")
                job = be.retrieve_job(job_id, registers=rec.get("registers")) if rec["provider"] == "ibm" \
                    else be.retrieve_job(job_id)
                self._live_jobs[job_id] = job
            status = job.status()
        except Exception as exc:
            self.store.update(job_id, error=f"refresh failed: {exc}")
            out = self._outcome(self.store.get(job_id))
            out.message = f"Could not query job: {exc}"
            return out
        if status == JobStatus.DONE:
            return self._finalize(job_id, job.results())
        err = None
        if status == JobStatus.ERROR and hasattr(job, "error_message"):
            err = job.error_message()
        self.store.update(job_id, status=status.value, error=err)
        return self._outcome(self.store.get(job_id))

    # ------------------------------------------------------------------ analysis
    def _finalize(self, job_id: str, results: list[CircuitResult]) -> RunOutcome:
        rec = self.store.get(job_id)
        exp = get_experiment(rec["experiment"])
        ctx = rec["context"] or {}
        n = int(ctx.get("n_circuits", len(results)))
        exp_results, cal_results = results[:n], results[n:]
        try:
            raw_report = exp.analyze(rec["params"], ctx.get("experiment_context", {}), exp_results)
            report = raw_report
            extra = dict(rec.get("extra") or {})
            if ctx.get("mitigation") and len(cal_results) == 2:
                mit_info = ctx["mitigation"]
                phys = mit_info["physical_qubits"]
                local_ids = list(range(len(phys))) if rec["provider"] == "ibm" else phys
                mitigator = ReadoutMitigator.from_results(local_ids, cal_results[0], cal_results[1])
                mitigator = ReadoutMitigator({q: mitigator.assignment[l] for q, l in zip(phys, local_ids)})
                mitigated = []
                for res, lay in zip(exp_results, mit_info["layouts"]):
                    qubits = [lay.get(str(c), lay.get(c)) for c in range(res.num_clbits)]
                    if None in qubits:
                        mitigated.append(res)
                        continue
                    probs = mitigator.apply(res.counts, qubits)
                    counts = {k: int(round(v * res.shots)) for k, v in probs.items() if round(v * res.shots) > 0}
                    mitigated.append(CircuitResult(counts, res.shots, res.num_clbits, res.registers, None,
                                                   {**res.metadata, "mitigated": True}))
                report = exp.analyze(rec["params"], ctx.get("experiment_context", {}), mitigated)
                report.notes.append(
                    "Tensored readout-error mitigation applied (2 calibration circuits). "
                    "Per-qubit (P(1|0), P(0|1)): " + ", ".join(
                        f"q{q}: ({a:.3f}, {b:.3f})" for q, (a, b) in mitigator.error_rates().items()))
                extra["raw_report"] = raw_report.to_dict()
                extra["assignment"] = mitigator.to_dict()
            stored_results = [self._compact(r, ctx.get("memory", False)) for r in results]
            self.store.update(job_id, status="DONE", report=report.to_dict(), results=stored_results,
                              extra=extra, error=None)
        except Exception as exc:
            self.store.update(job_id, status="DONE", error=f"analysis failed: {exc}\n{traceback.format_exc()}",
                              results=[self._compact(r, False) for r in results])
        return self._outcome(self.store.get(job_id))

    @staticmethod
    def _compact(r: CircuitResult, keep_memory: bool) -> dict:
        d = r.to_dict()
        if not keep_memory:
            d["memory"] = None
        return d

    def reanalyze(self, job_id: str) -> RunOutcome:
        rec = self.store.get(job_id)
        if not rec or not rec.get("results"):
            raise ValueError("job has no stored results")
        return self._finalize(job_id, [CircuitResult.from_dict(r) for r in rec["results"]])

    def _outcome(self, rec: dict) -> RunOutcome:
        return RunOutcome(rec["job_id"], rec["backend"], rec.get("experiment") or "", rec["status"],
                          report=rec.get("report"), preflight=rec.get("preflight"),
                          message=rec.get("error") or "")
