"""Device-physics experiments: repetition-code error correction and T1 / Ramsey coherence."""
from __future__ import annotations

import math

import numpy as np

from ..core.circuit import Circuit
from .base import Chart, Experiment, Param, Plan, Report, Table, Tutor, register
from .library import fit_damped_cosine, fit_exponential


@register
class RepetitionCode(Experiment):
    id = "repetition_code"
    tutor = Tutor(
        concept="Quantum error correction protects fragile quantum information by spreading one 'logical' qubit across "
                "many physical ones, so errors can be detected and fixed without ever reading (and destroying) the data. "
                "The repetition code is the simplest example.",
        how_it_works="Encode one qubit into d copies with CNOTs. Errors are injected, then ANCILLA qubits measure "
                     "PARITIES between neighbours (syndromes) — these reveal WHERE an error occurred without revealing the "
                     "encoded value. Majority voting (or syndrome decoding) corrects it. An unencoded qubit runs alongside "
                     "for comparison.",
        intuition="You never measure the data directly — that would collapse it. You measure relationships (does qubit 1 "
                  "agree with qubit 2?), which pinpoint errors while leaving the superposition intact. Below a noise "
                  "threshold, more qubits = exponentially fewer logical errors.",
        misconception="The repetition code only catches ONE type of error (bit-flip OR phase-flip, not both), so it's not "
                      "a full quantum code — real codes like the surface code handle both. It's the on-ramp, not the "
                      "destination.",
        what_to_look_for="Logical error rate BELOW the physical rate (that's error suppression working), matching the "
                         "combinatorial theory. The syndrome histogram shows which error patterns occurred.",
        try_this=["Increase distance d and watch the logical error rate fall (for p below threshold).",
                  "Switch flip to 'phase' (with the basis change) to protect against phase errors instead.",
                  "Push p past ~0.5 and watch correction fail — above threshold, more qubits HURT."],
        real_world_use="Fault-tolerant quantum computing — the thing that makes Shor-scale algorithms possible — is "
                       "built from codes like this. The surface code is the leading candidate; 2023–2024 saw the first "
                       "below-threshold demonstrations.",
        going_deeper="The Steane [[7,1,3]] and surface codes correct both error types; see the QEC roadmap experiments.",
        references=[{"title": "Quantum error correction", "url": "https://en.wikipedia.org/wiki/Quantum_error_correction"}],
        prerequisites=["ghz"],
    )
    title = "Repetition code: syndrome extraction and majority decoding"
    category = "Error correction"
    summary = "Encode one logical qubit in d physical qubits, inject errors, measure syndromes, decode."
    description = ("Errors are injected as coherent rotations RX(θ) (bit-flip code) or RZ(θ) (phase-flip code) "
                   "with sin²(θ/2) = p on every data qubit; syndrome measurement discretises them into "
                   "probabilistic Pauli errors. Majority voting fails only when more than (d−1)/2 qubits flip, "
                   "so P_L ≈ Σ_{k>d/2} C(d,k) p^k (1−p)^(d−k) ≪ p for small p. An unencoded qubit with the same "
                   "error is run alongside for comparison.")
    params = [Param("distance", "int", 3, "Code distance d (odd)", 3, 9),
              Param("p", "float", 0.1, "Injected error probability per data qubit", 0, 0.5),
              Param("flip", "choice", "bit", "Error/code type", choices=["bit", "phase"]),
              Param("logical", "int", 1, "Logical state to protect (0 or 1)", 0, 1)]
    hardware_notes = "2d−1 qubits; ancillas measured mid-circuit (data measured at the end)."

    def build(self, p):
        d = p["distance"]
        if d % 2 == 0:
            raise ValueError("distance must be odd")
        theta = 2 * math.asin(math.sqrt(p["p"]))
        qc = Circuit(name=f"rep{d}_{p['flip']}")
        data = qc.add_qreg("data", d)
        anc = qc.add_qreg("anc", d - 1)
        syn = qc.add_creg("syn", d - 1)
        out = qc.add_creg("out", d)
        if p["logical"]:
            qc.x(data[0])
        for i in range(1, d):
            qc.cx(data[0], data[i])
        if p["flip"] == "phase":
            qc.h(data)
        qc.barrier()
        if theta:
            (qc.rx if p["flip"] == "bit" else qc.rz)(theta, data)
        qc.barrier()
        if p["flip"] == "phase":
            qc.h(data)
        for i in range(d - 1):
            qc.cx(data[i], anc[i])
            qc.cx(data[i + 1], anc[i])
        qc.measure(anc, syn)
        qc.measure(data, out)
        bare = Circuit(1, name="unencoded")
        bc = bare.add_creg("out", 1)
        if p["logical"]:
            bare.x(0)
        if p["flip"] == "phase":
            bare.h(0)
        if theta:
            (bare.rx if p["flip"] == "bit" else bare.rz)(theta, 0)
        if p["flip"] == "phase":
            bare.h(0)
        bare.measure(0, bc[0])
        return Plan([qc, bare], {"theta": theta})

    def analyze(self, p, ctx, results):
        d, pp, L = p["distance"], p["p"], p["logical"]
        enc, bare = results
        fails = 0
        syn_hist: dict[str, int] = {}
        consistent = 0
        for key, c in enc.counts.items():
            out = key[: d]          # 'out' register is the higher clbits
            syn = key[d:]
            ones = out.count("1")
            decoded = 1 if ones > d // 2 else 0
            if decoded != L:
                fails += c
            syn_hist[syn] = syn_hist.get(syn, 0) + c
            data_bits = [int(b) for b in reversed(out)]
            implied = "".join(str(data_bits[i] ^ data_bits[i + 1]) for i in range(d - 1))[::-1]
            if implied == syn:
                consistent += c
        pl = fails / enc.shots
        pb = 1 - bare.register("out").get(str(L), 0) / bare.shots
        theory = sum(math.comb(d, k) * pp ** k * (1 - pp) ** (d - k) for k in range(d // 2 + 1, d + 1))
        return Report(
            f"Distance-{d} {p['flip']}-flip repetition code",
            [f"Logical error rate {pl:.4f} vs unencoded {pb:.4f} (theory: logical {theory:.4f}, physical {pp:.4f})",
             f"Syndrome agrees with final data parity in {consistent / enc.shots:.2%} of shots "
             "(disagreement = errors during/after syndrome extraction)"],
            {"logical_error": pl, "unencoded_error": pb, "theory_logical": theory, "physical_p": pp,
             "suppression": (pb / pl) if pl else float("inf")},
            [Table("Syndrome histogram", ["syndrome", "fraction"],
                   [[k, round(v / enc.shots, 4)] for k, v in sorted(syn_hist.items(), key=lambda kv: -kv[1])[:16]])],
            [Chart("Error rates", ["unencoded", "logical (measured)", "logical (theory)"],
                   {"rate": [pb, pl, theory]})],
            "pass" if pl < pb or pp == 0 else "warn")


@register
class Coherence(Experiment):
    id = "coherence"
    tutor = Tutor(
        concept="Every real qubit forgets. T1 and T2 measure how long it keeps its energy and its phase before noise "
                "erases the quantum information. These two numbers set the clock on everything a device can compute.",
        how_it_works="T1 (relaxation): excite the qubit with X, wait a varying time, measure — the chance of still "
                     "reading 1 decays as e^(−t/T1). T2* (Ramsey): put the qubit on the equator, let it precess with a "
                     "small detuning, wait, and bring it back — the interference fringes decay as e^(−t/T2*). We fit both curves.",
        intuition="T1 is energy leaking to the environment (|1⟩→|0⟩). T2 is the phase getting scrambled — the two "
                  "'hands' of the quantum clock drifting apart. T2 ≤ 2·T1 always, because losing energy also loses phase.",
        misconception="The ideal `local` simulator has NO decoherence, so the curves are flat and the fit is "
                      "meaningless there. You must run this on a noise model (local-noisy:*, aer:fake_*) or real hardware "
                      "to see decay — that's the whole point.",
        what_to_look_for="A clean exponential decay for T1 and decaying Ramsey fringes for T2*, with fitted times in "
                         "microseconds. On local the report warns that nothing decayed.",
        try_this=["Run on local-noisy:heron_like vs local-noisy:noisy and compare the fitted T1/T2.",
                  "Run on ibm:fake_fez to see a calibrated device's real coherence times.",
                  "Change the Ramsey detuning and watch the fringe frequency change."],
        real_world_use="T1/T2 are the headline specs vendors report and improve release to release; they bound circuit "
                       "depth, gate counts, and ultimately which algorithms a device can run before information decays.",
        going_deeper="Dynamical decoupling and error mitigation fight T2 decay; error correction fights both — see the "
                     "repetition code.",
        references=[{"title": "Relaxation (T1) and dephasing (T2)", "url": "https://en.wikipedia.org/wiki/Relaxation_(NMR)"}],
        prerequisites=["qrng"],
    )
    title = "Qubit coherence: T1 relaxation and Ramsey T2*"
    category = "Device physics"
    summary = "Delay sweeps with exponential / damped-cosine fits — run on a noisy simulator or real hardware."
    description = ("T1: X, wait t, measure → P(1) = A·e^(−t/T1) + B. Ramsey: H (a π/2 pulse), wait t, virtual "
                   "detuning rotation RZ(2π f t), H, measure → damped oscillation with envelope e^(−t/T2*). "
                   "The ideal `local` simulator has no decoherence (flat curves); use `local-noisy:heron_like`, "
                   "`aer:fake_fez` or a real device.")
    params = [Param("delays_us", "str", "0,15,30,60,100,150,220,300", "Delay points in microseconds"),
              Param("detuning_mhz", "float", 0.02, "Ramsey virtual detuning (MHz)", 0, 5)]
    hardware_notes = "2 × points single-qubit circuits."
    default_shots = 1000

    def build(self, p):
        delays = [float(x) for x in p["delays_us"].split(",") if x.strip()]
        if len(delays) < 3:
            raise ValueError("need at least 3 delay points")
        circuits = []
        for t in delays:
            qc = Circuit(1, name=f"t1_{t:g}us")
            c = qc.add_creg("c", 1)
            qc.x(0)
            if t > 0:
                qc.delay(t * 1e-6, 0)
            qc.measure(0, c[0])
            circuits.append(qc)
        f = p["detuning_mhz"] * 1e6
        for t in delays:
            qc = Circuit(1, name=f"ramsey_{t:g}us")
            c = qc.add_creg("c", 1)
            qc.h(0)
            if t > 0:
                qc.delay(t * 1e-6, 0)
            qc.rz(2 * math.pi * f * t * 1e-6, 0)
            qc.h(0)
            qc.measure(0, c[0])
            circuits.append(qc)
        return Plan(circuits, {"delays_us": delays})

    def analyze(self, p, ctx, results):
        t = np.array(ctx["delays_us"])
        k = len(t)
        p1 = np.array([r.counts.get("1", 0) / r.shots for r in results[:k]])
        p0 = np.array([r.counts.get("0", 0) / r.shots for r in results[k:]])
        T1, A1, B1 = fit_exponential(t, p1)
        f_mhz = p["detuning_mhz"]
        T2, A2, ph, B2 = fit_damped_cosine(t, p0 - 0.5, f_mhz)  # t in µs, f in MHz
        flat = float(np.ptp(p1)) < 0.05
        summary = [f"T1 ≈ {T1:.1f} µs (A={A1:.3f}, B={B1:.3f})", f"T2* ≈ {T2:.1f} µs (Ramsey, f = {f_mhz} MHz)"]
        if flat:
            summary.append("No measurable decay: this backend has no relaxation for the chosen delays "
                           "(the ideal simulator never decays).")
        return Report("Coherence (T1 / Ramsey)", summary,
                      {"T1_us": T1, "T2star_us": T2, "decay_observed": not flat},
                      [Table("Data", ["delay µs", "P(1) after X", "P(0) Ramsey"],
                             [[float(a), round(float(b), 4), round(float(c), 4)] for a, b, c in zip(t, p1, p0)])],
                      [Chart("T1 decay", [f"{x:g}" for x in t],
                             {"P(1)": p1.tolist(), "fit": (A1 * np.exp(-t / T1) + B1).tolist()}, "line", "µs", "P(1)"),
                       Chart("Ramsey fringes", [f"{x:g}" for x in t], {"P(0)": p0.tolist()}, "line", "µs", "P(0)")],
                      "pass" if not flat else "warn")
