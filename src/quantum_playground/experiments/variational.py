"""Variational hybrid algorithms: VQE for H2 and QAOA for MaxCut."""
from __future__ import annotations

import itertools
import math

import numpy as np

from ..core.circuit import Circuit
from ..core.statevector import Statevector
from ..optim import multistart, nelder_mead, spsa
from .base import Chart, Experiment, Param, Plan, Report, Table, Tutor, counts_chart, register

# H2 at 0.735 Å, STO-3G, parity mapping with two-qubit reduction (Qiskit Nature reference values).
# Pauli strings in Qiskit order (left = qubit 1).
H2_TERMS = {"II": -1.052373245772859, "IZ": 0.39793742484318045, "ZI": -0.39793742484318045,
            "ZZ": -0.01128010425623538, "XX": 0.18093119978423156}
CHEMICAL_ACCURACY = 1.6e-3  # Hartree


def _pauli_matrix(label: str) -> np.ndarray:
    mats = {"I": np.eye(2), "X": np.array([[0, 1], [1, 0]]), "Y": np.array([[0, -1j], [1j, 0]]),
            "Z": np.diag([1, -1])}
    out = np.array([[1]])
    for ch in label:  # left-most = highest qubit
        out = np.kron(out, mats[ch])
    return out


def h2_exact() -> float:
    H = sum(c * _pauli_matrix(p) for p, c in H2_TERMS.items())
    return float(np.linalg.eigvalsh(H)[0])


def _ansatz(qc: Circuit, theta, kind: str) -> None:
    if kind == "ucc1":
        qc.x(0)
        qc.ry(theta[0], 1)
        qc.cx(1, 0)
    else:  # hardware-efficient RY-CX-RY
        qc.ry(theta[0], 0).ry(theta[1], 1)
        qc.cx(0, 1)
        qc.ry(theta[2], 0).ry(theta[3], 1)


def _energy_exact(theta, kind: str) -> float:
    qc = Circuit(2)
    _ansatz(qc, theta, kind)
    sv = Statevector.from_circuit(qc)
    return sum(c * (1.0 if p == "II" else sv.expectation_pauli(p)) for p, c in H2_TERMS.items())


@register
class VQEH2(Experiment):
    id = "vqe_h2"
    tutor = Tutor(
        concept="The Variational Quantum Eigensolver finds the lowest energy (ground state) of a molecule — the quantity "
                "that determines its structure and reactivity — on today's noisy hardware. It's quantum chemistry's "
                "flagship near-term application.",
        how_it_works="A classical optimiser tunes the angles of a short parameterised circuit (the 'ansatz'). For each "
                     "setting, the quantum device prepares the trial state and MEASURES the energy ⟨H⟩ by sampling the "
                     "Hamiltonian's Pauli terms in commuting groups (Z-basis and X-basis here). The optimiser walks the "
                     "angles downhill until the energy stops dropping.",
        intuition="The variational principle guarantees any trial energy is ≥ the true ground energy, so 'lowest wins'. "
                  "The quantum computer is a fast energy-evaluator inside a classical optimisation loop — a hybrid algorithm.",
        misconception="VQE isn't pure quantum magic: it's a quantum-classical loop, its answer is only as good as the "
                      "ansatz, and it can get stuck in local minima or on 'barren plateaus' where gradients vanish. It "
                      "trades Shor-style depth for many shallow measurements.",
        what_to_look_for="Measured energy close to the exact diagonalisation value. 'Chemical accuracy' is 1.6 mHa; the "
                         "report flags whether you're within it (or within shot noise of it).",
        try_this=["Switch optimizer between nelder_mead and spsa (SPSA is built for noisy measurements).",
                  "Run on ibm:fake_fez with --mitigate-readout and watch the energy error shrink.",
                  "Compare ucc1 vs hardware_efficient ansatz."],
        real_world_use="VQE and its successors target battery materials, catalysts and drug molecules — the cases where "
                       "classical chemistry scales badly. Companies and national labs run VQE pilots on real QPUs today.",
        going_deeper="QAOA is VQE's optimisation cousin; phase estimation is the fault-tolerant alternative once error "
                     "correction arrives.",
        references=[{"title": "Variational quantum eigensolver", "url": "https://en.wikipedia.org/wiki/Variational_quantum_eigensolver"}],
        prerequisites=["bell_states"],
    )
    title = "VQE: ground-state energy of H₂"
    category = "Variational"
    summary = "Optimise an ansatz classically, then measure ⟨H⟩ on the chosen backend (Z and X groups)."
    description = ("Two-qubit H₂ Hamiltonian (0.735 Å, STO-3G, parity-reduced). Parameters are optimised "
                   "against an exact simulator (Nelder–Mead or SPSA), then the energy is *measured* on the "
                   "backend from two commuting groups: {II, IZ, ZI, ZZ} in the Z basis and {XX} in the X basis. "
                   "Combine with --mitigate-readout on hardware to approach chemical accuracy.")
    params = [Param("ansatz", "choice", "ucc1", "Ansatz", choices=["ucc1", "hardware_efficient"]),
              Param("optimizer", "choice", "nelder_mead", "Optimiser", choices=["nelder_mead", "spsa"])]
    hardware_notes = "2 circuits × 2 qubits, ≤ 1 CX — excellent hardware demo."
    default_shots = 8000

    def _optimise(self, p):
        kind = p["ansatz"]
        dim = 1 if kind == "ucc1" else 4
        f = lambda th: _energy_exact(th, kind)
        if p["optimizer"] == "spsa":
            res = spsa(f, [0.1] * dim, iterations=200)
        else:
            res = multistart(f, dim, starts=4) if dim > 1 else nelder_mead(f, [0.1], step=0.6)
        return res

    def build(self, p):
        res = self._optimise(p)
        theta = res.x
        circuits = []
        for basis in ("Z", "X"):
            qc = Circuit(2, name=f"vqe_h2_{basis}")
            c = qc.add_creg("c", 2)
            _ansatz(qc, theta, p["ansatz"])
            if basis == "X":
                qc.h([0, 1])
            qc.measure([0, 1], c)
            circuits.append(qc)
        return Plan(circuits, {"theta": theta, "optimizer_energy": res.fun, "nfev": res.nfev,
                               "history": res.history[-60:]})

    def analyze(self, p, ctx, results):
        rz, rx = results
        z0 = rz.expectation_parity([0])
        z1 = rz.expectation_parity([1])
        zz = rz.expectation_parity([0, 1])
        xx = rx.expectation_parity([0, 1])
        terms = {"II": 1.0, "IZ": z0, "ZI": z1, "ZZ": zz, "XX": xx}
        E = sum(H2_TERMS[k] * v for k, v in terms.items())
        var = sum((H2_TERMS[k] ** 2) * (1 - v ** 2) / rz.shots for k, v in terms.items() if k != "II")
        exact = h2_exact()
        err = E - exact
        rows = [[k, round(H2_TERMS[k], 6), round(v, 4)] for k, v in terms.items()]
        scan = np.linspace(-math.pi, math.pi, 41)
        chart = None
        if p["ansatz"] == "ucc1":
            chart = Chart("Energy landscape E(θ) (exact)", [f"{t:.2f}" for t in scan],
                          {"E(θ)": [_energy_exact([t], "ucc1") for t in scan]}, "line", "θ", "Hartree")
        sigma = math.sqrt(var)
        within_noise = abs(err) < 3 * sigma
        verdict = "pass" if (abs(err) < CHEMICAL_ACCURACY or within_noise) else ("warn" if abs(err) < 0.05 else "fail")
        return Report(
            "VQE — H₂ ground state",
            [f"Measured energy E = {E:.6f} ± {math.sqrt(var):.6f} Ha",
             f"Exact (diagonalisation) {exact:.6f} Ha; optimiser reached {ctx['optimizer_energy']:.6f} Ha",
             f"Error {err * 1000:.3f} mHa — chemical accuracy is 1.6 mHa"
             + (" (statistically consistent with the exact value at 3σ; add shots to tighten)"
                if within_noise and abs(err) >= CHEMICAL_ACCURACY else "")],
            {"energy": E, "exact": exact, "error_mHa": err * 1000, "theta": ctx["theta"], "nfev": ctx["nfev"]},
            [Table("Pauli expectation values", ["term", "coefficient", "⟨P⟩"], rows)],
            [c for c in (chart, Chart("Optimiser trace", [str(i) for i in range(len(ctx["history"]))],
                                      {"energy": ctx["history"]}, "line", "step", "Hartree")) if c],
            verdict)


# =============================================================================
def _parse_edges(text: str) -> list[tuple[int, int]]:
    edges = []
    for tok in text.replace(";", ",").split(","):
        tok = tok.strip()
        if not tok:
            continue
        a, b = (int(x) for x in tok.replace(" ", "").split("-"))
        if a == b:
            raise ValueError("self-loops not allowed")
        edges.append((min(a, b), max(a, b)))
    if not edges:
        raise ValueError("graph has no edges")
    return sorted(set(edges))


def _cut(bits: int, edges) -> int:
    return sum(((bits >> a) & 1) != ((bits >> b) & 1) for a, b in edges)


def _qaoa_circuit(n, edges, gammas, betas, measure=True) -> Circuit:
    qc = Circuit(n, name=f"qaoa_p{len(gammas)}")
    qc.h(list(range(n)))
    for g, b in zip(gammas, betas):
        for a, c in edges:
            qc.rzz(-g, a, c)       # exp(-i γ C), C = Σ (1 - Z_a Z_c)/2, up to global phase
        qc.rx(2 * b, list(range(n)))
    if measure:
        cr = qc.add_creg("c", n)
        qc.measure(list(range(n)), cr)
    return qc


@register
class QAOAMaxCut(Experiment):
    id = "qaoa_maxcut"
    tutor = Tutor(
        concept="The Quantum Approximate Optimization Algorithm attacks hard combinatorial problems — here MaxCut, "
                "splitting a graph's nodes into two groups to cut the most edges — by encoding the objective into a "
                "quantum circuit and tuning it toward good solutions.",
        how_it_works="Start in an equal superposition of all partitions. Alternate two layers p times: a COST layer "
                     "(RZZ on each edge) that imprints each cut's value as a phase, and a MIXER layer (RX on every qubit) "
                     "that spreads amplitude between partitions. A classical optimiser picks the layer angles (γ, β). "
                     "Measuring samples high-cut partitions more often.",
        intuition="Cost phases make good cuts 'heavier'; the mixer lets amplitude flow toward them. More layers p give a "
                  "closer approximation, interpolating toward adiabatic quantum optimisation at large p.",
        misconception="QAOA is a HEURISTIC — it returns good (not provably optimal) cuts, and whether it beats classical "
                      "solvers is still open and problem-dependent. The win is an approximation ratio, demonstrated here "
                      "against a brute-force optimum.",
        what_to_look_for="The sampled average cut and the approximation ratio vs the brute-force maximum, plus P(optimal "
                         "cut). Compare to random guessing and to the ideal expectation for your p.",
        try_this=["Edit the graph `edges` and add layers (p) to push the approximation ratio up.",
                  "Try a triangle (odd cycle) — frustrated graphs are where MaxCut gets interesting.",
                  "Run on ibm:fake_fez: each edge costs two CX per layer, so watch depth vs noise."],
        real_world_use="MaxCut-style QUBOs model portfolio optimisation, logistics/routing, scheduling and network "
                       "design; banks and logistics firms pilot QAOA and quantum annealing on exactly these.",
        going_deeper="The portfolio-optimization and max-independent-set experiments apply the same QAOA machinery to "
                     "money and networks.",
        references=[{"title": "Quantum approximate optimization algorithm", "url": "https://en.wikipedia.org/wiki/Quantum_optimization_algorithms"}],
        prerequisites=["bell_states"],
    )
    title = "QAOA for MaxCut"
    category = "Variational"
    summary = "Optimise QAOA angles exactly, sample cuts on the backend, compare with brute force."
    params = [Param("edges", "str", "0-1,1-2,2-3,3-0,0-2,3-4,4-1", "Graph edges a-b, comma separated"),
              Param("p", "int", 2, "QAOA layers", 1, 4)]
    hardware_notes = "Qubits = vertices; 2 CX per edge per layer after RZZ decomposition."

    def build(self, p):
        edges = _parse_edges(p["edges"])
        n = max(max(e) for e in edges) + 1
        if n > 14:
            raise ValueError("at most 14 vertices")
        L = p["p"]
        cuts = np.array([_cut(b, edges) for b in range(1 << n)], dtype=float)

        def neg_expect(x):
            qc = _qaoa_circuit(n, edges, x[:L], x[L:], measure=False)
            probs = Statevector.from_circuit(qc).probabilities()
            return -float(probs @ cuts)

        res = multistart(neg_expect, 2 * L, starts=5, low=0, high=math.pi / 2)
        qc = _qaoa_circuit(n, edges, res.x[:L], res.x[L:])
        return Plan([qc], {"n": n, "edges": edges, "gammas": res.x[:L], "betas": res.x[L:],
                           "ideal_expectation": -res.fun, "max_cut": float(cuts.max())})

    def analyze(self, p, ctx, results):
        n, edges = ctx["n"], [tuple(e) for e in ctx["edges"]]
        res = results[0]
        best_cut = ctx["max_cut"]
        dist: dict[int, int] = {}
        exp = 0.0
        best_found, best_bits = -1, None
        for k, c in res.counts.items():
            v = _cut(int(k, 2), edges)
            dist[v] = dist.get(v, 0) + c
            exp += v * c / res.shots
            if v > best_found:
                best_found, best_bits = v, k
        p_opt = dist.get(int(best_cut), 0) / res.shots
        ratio = exp / best_cut
        random_ratio = (len(edges) / 2) / best_cut
        return Report(
            "QAOA MaxCut",
            [f"Graph: {n} vertices, {len(edges)} edges; maximum cut {int(best_cut)} (brute force)",
             f"Sampled ⟨cut⟩ = {exp:.3f} → approximation ratio {ratio:.3f} (random guessing {random_ratio:.3f}, "
             f"ideal p={p['p']}: {ctx['ideal_expectation'] / best_cut:.3f})",
             f"Best sampled cut {best_found} via partition {best_bits}; P(optimal cut) = {p_opt:.4f}"],
            {"approx_ratio": ratio, "ideal_ratio": ctx["ideal_expectation"] / best_cut, "p_optimal": p_opt,
             "gammas": ctx["gammas"], "betas": ctx["betas"]},
            [Table("Cut value distribution", ["cut", "probability"],
                   [[k, round(v / res.shots, 4)] for k, v in sorted(dist.items())])],
            [Chart("Cut value distribution", [str(k) for k in sorted(dist)],
                   {"measured": [dist[k] / res.shots for k in sorted(dist)]}, "bar", "cut size", "probability")],
            "pass" if ratio > random_ratio + 0.05 else "warn")
