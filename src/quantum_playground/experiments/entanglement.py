"""Entanglement experiments: Bell-state fidelity, CHSH inequality, GHZ coherence."""
from __future__ import annotations

import math

import numpy as np

from ..core.circuit import Circuit
from ..core.statevector import Statevector
from .base import Chart, Experiment, Param, Plan, Report, Table, binomial_sigma, counts_chart, register

_BELL = {"phi+": ("Φ+", False, False), "phi-": ("Φ−", True, False), "psi+": ("Ψ+", False, True),
         "psi-": ("Ψ−", True, True)}


def _bell_prep(qc: Circuit, which: str, a: int = 0, b: int = 1) -> None:
    _, z, x = _BELL[which]
    qc.h(a)
    qc.cx(a, b)
    if x:
        qc.x(b)
    if z:
        qc.z(a)


def _basis_change(qc: Circuit, q: int, basis: str) -> None:
    if basis == "X":
        qc.h(q)
    elif basis == "Y":
        qc.sdg(q)
        qc.h(q)


@register
class BellStates(Experiment):
    id = "bell_states"
    title = "Bell-state fidelity (XX / YY / ZZ correlations)"
    category = "Entanglement"
    summary = "Prepare a Bell state and estimate its fidelity from three Pauli correlators."
    description = ("A Bell projector is |B><B| = (II + s_x XX + s_y YY + s_z ZZ)/4, so measuring the three "
                   "two-qubit correlators gives the fidelity F = (1 + s_x<XX> + s_y<YY> + s_z<ZZ>)/4 exactly. "
                   "F > 0.5 certifies entanglement.")
    hardware_notes = "3 circuits, 2 qubits, 1 CX each — ideal first hardware test."
    params = [Param("state", "choice", "phi+", "Bell state", choices=list(_BELL))]

    def build(self, p):
        circuits = []
        for basis in "XYZ":
            qc = Circuit(2, name=f"bell_{p['state']}_{basis}{basis}")
            c = qc.add_creg("c", 2)
            _bell_prep(qc, p["state"])
            for q in (0, 1):
                _basis_change(qc, q, basis)
            qc.measure([0, 1], c)
            circuits.append(qc)
        return Plan(circuits, {"bases": ["XX", "YY", "ZZ"]})

    def analyze(self, p, ctx, results):
        prep = Circuit(2)
        _bell_prep(prep, p["state"])
        sv = Statevector.from_circuit(prep)
        rows, F = [], 1.0
        sigma2 = 0.0
        for pauli, res in zip(("XX", "YY", "ZZ"), results):
            meas = res.expectation_parity([0, 1])
            ideal = sv.expectation_pauli(pauli)
            sign = 1 if ideal > 0 else -1
            F += sign * meas
            sigma2 += (1 - meas ** 2) / res.shots
            rows.append([pauli, round(ideal, 4), round(meas, 4)])
        F /= 4
        sigma = math.sqrt(sigma2) / 4
        verdict = "pass" if F - 3 * sigma > 0.5 else ("warn" if F > 0.5 else "fail")
        return Report(
            f"Bell state |{_BELL[p['state']][0]}⟩",
            [f"Estimated fidelity F = {F:.4f} ± {sigma:.4f}",
             "Entanglement witnessed (F > 0.5)" if F > 0.5 else "No entanglement witnessed"],
            {"fidelity": F, "sigma": sigma, "shots_per_basis": results[0].shots},
            [Table("Correlators", ["Pauli", "ideal", "measured"], rows)],
            [counts_chart(f"{b} basis outcomes", r.counts) for b, r in zip(("XX", "YY", "ZZ"), results)],
            verdict)


@register
class CHSH(Experiment):
    id = "chsh"
    title = "CHSH Bell-inequality test"
    category = "Entanglement"
    summary = "Violate the CHSH inequality |S| ≤ 2 obeyed by every local-hidden-variable theory."
    description = ("Alice measures at angles 0 and π/2, Bob at π/4 and −π/4 (in the X–Z plane). Quantum "
                   "mechanics predicts S = 2√2 ≈ 2.828 (Tsirelson's bound); any local realistic model gives "
                   "|S| ≤ 2. Rotate Bob's settings with `bob_offset_deg` to watch the violation vanish.")
    hardware_notes = "4 circuits × 2 qubits. Heron-class devices typically reach S ≈ 2.6–2.75."
    params = [Param("bob_offset_deg", "float", 0.0, "Extra rotation of Bob's measurement axes (degrees)",
                    -180, 180)]

    def _angles(self, p):
        off = math.radians(p["bob_offset_deg"])
        return [0.0, math.pi / 2], [math.pi / 4 + off, -math.pi / 4 + off]

    def build(self, p):
        A, B = self._angles(p)
        circuits = []
        for i, a in enumerate(A):
            for j, b in enumerate(B):
                qc = Circuit(2, name=f"chsh_a{i}b{j}")
                c = qc.add_creg("c", 2)
                _bell_prep(qc, "phi+")
                qc.ry(-a, 0)
                qc.ry(-b, 1)
                qc.measure([0, 1], c)
                circuits.append(qc)
        return Plan(circuits, {"alice": A, "bob": B})

    def analyze(self, p, ctx, results):
        A, B = ctx["alice"], ctx["bob"]
        E, rows, var = [], [], 0.0
        k = 0
        for i, a in enumerate(A):
            for j, b in enumerate(B):
                res = results[k]
                e = res.expectation_parity([0, 1])
                E.append(e)
                var += (1 - e ** 2) / res.shots
                rows.append([f"a{i}={math.degrees(a):.0f}°", f"b{j}={math.degrees(b):.0f}°", round(math.cos(a - b), 4),
                             round(e, 4)])
                k += 1
        S = E[0] + E[1] + E[2] - E[3]
        ideal = sum(math.cos(A[i] - B[j]) * (1 if (i, j) != (1, 1) else -1) for i in range(2) for j in range(2))
        sigma = math.sqrt(var)
        z = (abs(S) - 2) / sigma if sigma else float("inf")
        verdict = "pass" if z > 3 else ("warn" if abs(S) > 2 else "fail")
        return Report(
            "CHSH inequality",
            [f"S = {S:.4f} ± {sigma:.4f}  (classical bound 2, Tsirelson bound {2 * math.sqrt(2):.4f})",
             f"Violation significance: {z:.1f} σ" if abs(S) > 2 else "No violation of the classical bound"],
            {"S": S, "sigma": sigma, "ideal_S": ideal, "violation_sigma": z},
            [Table("Correlators E(a,b)", ["Alice", "Bob", "ideal", "measured"], rows)],
            [Chart("Correlators", ["E00", "E01", "E10", "E11"], {"measured": E,
                   "ideal": [math.cos(A[i] - B[j]) for i in range(2) for j in range(2)]})],
            verdict)


@register
class GHZ(Experiment):
    id = "ghz"
    title = "GHZ state: populations + parity oscillations"
    category = "Entanglement"
    summary = "Create an n-qubit GHZ state and estimate its fidelity from parity oscillations."
    description = ("Fidelity F = (P(0…0) + P(1…1))/2 + C/2, where C is the amplitude of the parity "
                   "oscillation ⟨P(φ)⟩ = C cos(nφ) obtained by rotating every qubit by RZ(φ) and measuring X. "
                   "Population alone does not prove coherence; the parity contrast does.")
    hardware_notes = "1 + `phases` circuits; n−1 CX in a chain (or log-depth tree)."
    params = [Param("n", "int", 4, "Number of qubits", 2, 20),
              Param("phases", "int", 8, "Parity phases sampled", 4, 16),
              Param("layout", "choice", "chain", "Entangling pattern", choices=["chain", "tree"])]

    def _prep(self, qc, n, layout):
        qc.h(0)
        if layout == "chain":
            for i in range(n - 1):
                qc.cx(i, i + 1)
        else:
            have = 1
            while have < n:
                for i in range(min(have, n - have)):
                    qc.cx(i, i + have)
                have *= 2

    def build(self, p):
        n, K = p["n"], p["phases"]
        qc = Circuit(n, name=f"ghz{n}_Z")
        c = qc.add_creg("c", n)
        self._prep(qc, n, p["layout"])
        qc.measure(list(range(n)), c)
        circuits = [qc]
        phis = [2 * math.pi * k / (K * n) for k in range(K)]
        for k, phi in enumerate(phis):
            qp = Circuit(n, name=f"ghz{n}_parity{k}")
            cp = qp.add_creg("c", n)
            self._prep(qp, n, p["layout"])
            qp.rz(phi, list(range(n)))
            qp.h(list(range(n)))
            qp.measure(list(range(n)), cp)
            circuits.append(qp)
        return Plan(circuits, {"phis": phis})

    def analyze(self, p, ctx, results):
        n = p["n"]
        pop = results[0]
        P0 = pop.counts.get("0" * n, 0) / pop.shots
        P1 = pop.counts.get("1" * n, 0) / pop.shots
        phis = np.array(ctx["phis"])
        par = np.array([r.expectation_parity(range(n)) for r in results[1:]])
        M = np.vstack([np.cos(n * phis), np.sin(n * phis)]).T
        coef, *_ = np.linalg.lstsq(M, par, rcond=None)
        C = float(math.hypot(*coef))
        F = (P0 + P1) / 2 + C / 2
        verdict = "pass" if F > 0.5 else "warn"
        return Report(
            f"{n}-qubit GHZ state",
            [f"Population P(0…0)+P(1…1) = {P0 + P1:.4f}", f"Parity contrast C = {C:.4f}",
             f"Fidelity estimate F = {F:.4f} " + ("(genuine multipartite entanglement: F > 0.5)" if F > 0.5
                                                   else "(F ≤ 0.5: GME not certified)")],
            {"P_all0": P0, "P_all1": P1, "parity_contrast": C, "fidelity": F},
            [Table("Parity scan", ["φ (rad)", "ideal cos(nφ)", "measured ⟨P⟩"],
                   [[round(float(f), 4), round(math.cos(n * f), 4), round(float(v), 4)] for f, v in zip(phis, par)])],
            [Chart("Parity oscillation", [f"{f:.2f}" for f in phis],
                   {"measured": [float(v) for v in par], "ideal": [math.cos(n * f) for f in phis]}, "line", "φ",
                   "⟨P⟩"),
             counts_chart("Z-basis populations", pop.counts, top=16)],
            verdict)
