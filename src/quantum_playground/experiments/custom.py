"""Run any user circuit (from the web composer, a JSON file or OpenQASM) through the full pipeline."""
from __future__ import annotations

import json

from ..core.circuit import Circuit
from ..core.results import hellinger_fidelity
from ..core.statevector import MAX_QUBITS, exact_distribution
from .base import Experiment, Param, Plan, Report, Table, Tutor, counts_chart, register


def circuit_from_text(text: str) -> Circuit:
    text = text.strip()
    if text.startswith("{"):
        return Circuit.from_dict(json.loads(text))
    if text.upper().startswith("OPENQASM"):
        try:
            import qiskit.qasm2
            import qiskit.qasm3
        except ImportError as exc:  # pragma: no cover
            raise ValueError("Importing OpenQASM requires qiskit") from exc
        from ..backends.qiskit_bridge import from_qiskit
        qc = qiskit.qasm3.loads(text) if text.upper().startswith("OPENQASM 3") else qiskit.qasm2.loads(text)
        return from_qiskit(qc)
    raise ValueError("Provide a qplay circuit JSON document or OpenQASM 2/3 source")


@register
class CustomCircuit(Experiment):
    id = "custom"
    tutor = Tutor(
        concept="Your own circuit, run through the same pipeline as every built-in experiment. Build it in the web "
                "composer or hand it OpenQASM, and the studio simulates, runs and scores it against the ideal.",
        how_it_works="The circuit (as qplay JSON or OpenQASM 2/3) is simulated exactly, run on your chosen backend, and "
                     "compared to the noise-free distribution via Hellinger fidelity. If you didn't add measurements, "
                     "the studio measures everything at the end.",
        intuition="This is the sandbox: the concepts from the other experiments are yours to combine. The live amplitude "
                  "and Bloch views in the Circuit Lab let you watch a state evolve gate by gate.",
        misconception="Fidelity with the ideal needs a simulable reference, so very large circuits skip that check. On "
                      "hardware, low fidelity usually means depth/noise, not a wrong circuit.",
        what_to_look_for="Hellinger fidelity near 1 on a good run; the outcome table compares measured counts to ideal "
                         "probabilities.",
        try_this=["Build a Bell or GHZ state in the composer and run it on ibm:fake_fez.",
                  "Paste an OpenQASM 3 circuit exported from Qiskit and run it unchanged.",
                  "Add mid-circuit measurements and feed-forward to explore dynamic circuits."],
        real_world_use="This is how you prototype a real algorithm: design on the exact simulator, rehearse on a device "
                       "model, then submit to hardware — the standard quantum development loop.",
        going_deeper="Every built-in experiment's 'Preview circuits' shows a circuit you can rebuild and modify here.",
        references=[{"title": "OpenQASM", "url": "https://openqasm.com/"}],
        prerequisites=["bell_states"],
    )
    title = "Custom circuit"
    category = "Circuit Lab"
    summary = "Execute a circuit from the composer (JSON) or OpenQASM on any backend, compared with the ideal."
    params = [Param("circuit", "str", "", "qplay circuit JSON or OpenQASM 2/3 source")]
    default_shots = 2000

    def build(self, p):
        if not p["circuit"]:
            qc = Circuit(2, name="bell")
            qc.h(0).cx(0, 1)
        else:
            qc = circuit_from_text(p["circuit"])
        if not any(i.name == "measure" for i in qc.instructions):
            qc.measure_all()
        return Plan([qc], {"name": qc.name})

    def analyze(self, p, ctx, results):
        res = results[0]
        qc = self.build(p).circuits[0]
        ideal = exact_distribution(qc) if qc.num_qubits <= min(MAX_QUBITS, 22) else None
        fid = hellinger_fidelity(res.counts, ideal) if ideal else None
        top = sorted(res.counts.items(), key=lambda kv: -kv[1])[:16]
        return Report(f"Custom circuit '{ctx.get('name', 'circuit')}'",
                      [f"{qc.num_qubits} qubits, {qc.size()} operations, depth {qc.depth()}"]
                      + ([f"Hellinger fidelity with the ideal distribution: {fid:.4f}"] if fid is not None else []),
                      {"hellinger_fidelity": fid, "distinct_outcomes": len(res.counts)},
                      [Table("Most frequent outcomes", ["bits", "count", "ideal p"],
                             [[k, v, round((ideal or {}).get(k, 0.0), 4)] for k, v in top])],
                      [counts_chart("Outcomes", res.counts, top=32, ideal=ideal)],
                      "pass" if fid is None or fid > 0.9 else "warn")
