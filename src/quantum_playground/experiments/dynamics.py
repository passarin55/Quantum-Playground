"""Quantum simulation, transport and sensing: Trotterized spin dynamics, a quantum walk, and GHZ metrology."""
from __future__ import annotations

import math

import numpy as np

from ..core.circuit import Circuit
from ..core.statevector import Statevector
from ..core.synthesis import apply_permutation, extend_permutation
from .base import Chart, Experiment, Param, Plan, Report, Table, Tutor, counts_chart, register


# =============================================================================
def _tfim_dense(n, J, h):
    X = np.array([[0, 1], [1, 0]], complex)
    Z = np.array([[1, 0], [0, -1]], complex)

    def op(s, site):
        m = np.array([[1.0]], complex)
        for q in range(n):
            m = np.kron(m, s if q == site else np.eye(2))
        return m

    H = np.zeros((1 << n, 1 << n), complex)
    for i in range(n - 1):
        H -= J * op(Z, i) @ op(Z, i + 1)
    for i in range(n):
        H -= h * op(X, i)
    return H


@register
class TFIMDynamics(Experiment):
    id = "tfim_dynamics"
    title = "Trotterized spin dynamics (quantum simulation)"
    category = "Simulation"
    summary = ("Watch a quantum magnet evolve in real time: Trotterize e^{-iHt} for the transverse-field Ising model "
               "and track the magnetization, the task quantum computers are naturally suited to.")
    description = (
        "Simulating how a quantum system changes in time is the original motivation for quantum computers (Feynman). "
        "Here the transverse-field Ising chain H = −J Σ ZᵢZᵢ₊₁ − h Σ Xᵢ is evolved from the all-up state by "
        "Trotterization: each small time step applies the ZZ couplings (RZZ) then the transverse field (RX). The "
        "magnetization ⟨Σ Zᵢ⟩/n is measured over time and compared to the exact evolution, exposing Trotter error.")
    hardware_notes = "n qubits (default 6); depth grows with Trotter steps — a core NISQ-era benchmark."
    params = [Param("spins", "int", 6, "Spins (qubits)", 2, 12),
              Param("coupling", "float", 1.0, "Ising coupling J", 0, 5),
              Param("field", "float", 1.0, "Transverse field h", 0, 5),
              Param("total_time", "float", 3.0, "Total evolution time", 0.5, 12),
              Param("points", "int", 10, "Time points sampled", 3, 20),
              Param("trotter_steps", "int", 6, "Trotter steps per time point", 1, 40)]
    tutor = Tutor(
        concept="Quantum computers are natural simulators of quantum physics. This evolves a quantum magnet in real "
                "time and watches its magnetization oscillate — a job that gets exponentially hard classically as the "
                "system grows.",
        how_it_works="Time evolution e^{-iHt} is chopped into small steps (Trotterization); each step applies the ZZ "
                     "couplings then the transverse field as gates. We measure the magnetization after each interval and "
                     "compare to the exact answer computed by diagonalising H.",
        intuition="You can't apply e^{-iHt} directly, but you can apply its pieces in sequence; the smaller the steps, "
                  "the better the approximation (Trotter error shrinks). The transverse field tips the spins, so "
                  "magnetization oscillates and decays.",
        misconception="Trotterization is approximate — too few steps gives visible error, and the circuit gets deeper "
                      "with more steps, so there's a noise-vs-accuracy trade-off on real hardware. This chain is small "
                      "enough to check classically; the value is the method and its scaling.",
        what_to_look_for="Measured magnetization tracking the exact curve; increasing trotter_steps reduces the gap. "
                         "The report reports the maximum deviation from exact.",
        try_this=["Lower trotter_steps and watch the simulation diverge from the exact curve.",
                  "Increase total_time to see more oscillations (and more accumulated Trotter error).",
                  "Run on ibm:fake_fez and watch noise add on top of Trotter error."],
        real_world_use="Digital quantum simulation studies magnetism, superconductivity and reaction dynamics; IBM's "
                       "2023 'utility' experiment simulated exactly this kind of Ising dynamics on 127 qubits.",
        going_deeper="VQE finds the GROUND state of the same Hamiltonian; the quantum walk is another dynamics demo.",
        references=[{"title": "IBM: Evidence for utility-scale quantum (Nature 2023)", "url": "https://www.nature.com/articles/s41586-023-06096-3"},
                    {"title": "Trotter–Suzuki decomposition", "url": "https://en.wikipedia.org/wiki/Time-evolving_block_decimation"}],
        prerequisites=["vqe_ising"],
    )

    def build(self, p):
        n, J, h = p["spins"], p["coupling"], p["field"]
        times = np.linspace(0, p["total_time"], p["points"])
        circuits = []
        for t in times:
            steps = max(1, p["trotter_steps"])
            dt = t / steps if t > 0 else 0.0
            qc = Circuit(n, name=f"tfim_t{t:.2f}")
            c = qc.add_creg("c", n)
            for _ in range(steps):
                for i in range(n - 1):
                    qc.rzz(-2 * J * dt, i, i + 1)     # exp(+i J dt ZZ)
                for i in range(n):
                    qc.rx(-2 * h * dt, i)             # exp(+i h dt X)
            qc.measure(list(range(n)), c)
            circuits.append(qc)
        return Plan(circuits, {"times": times.tolist()})

    def analyze(self, p, ctx, results):
        n, J, h = p["spins"], p["coupling"], p["field"]
        times = np.array(ctx["times"])
        meas = np.array([sum(r.expectation_parity([i]) for i in range(n)) / n for r in results])
        H = _tfim_dense(n, J, h)
        w, V = np.linalg.eigh(H)
        psi0 = np.zeros(1 << n, complex); psi0[0] = 1
        c0 = V.conj().T @ psi0
        exact = []
        Zdiag = np.array([sum(1 if not (s >> i) & 1 else -1 for i in range(n)) / n for s in range(1 << n)])
        for t in times:
            psit = V @ (np.exp(-1j * w * t) * c0)
            exact.append(float(np.real(np.sum(np.abs(psit) ** 2 * Zdiag))))
        exact = np.array(exact)
        max_dev = float(np.max(np.abs(meas - exact)))
        return Report(
            "Trotterized transverse-field Ising dynamics",
            [f"{n} spins, J={J}, h={h}, evolved to t={p['total_time']} in {p['trotter_steps']} Trotter steps/point.",
             f"Maximum deviation of simulated magnetization from exact: {max_dev:.4f}.",
             "Smaller Trotter steps track the exact curve more closely (less Trotter error)."],
            {"max_deviation": max_dev, "trotter_steps": p["trotter_steps"], "spins": n},
            [Table("Magnetization ⟨Z⟩/n vs time", ["t", "simulated", "exact"],
                   [[round(float(t), 3), round(float(m), 4), round(float(e), 4)] for t, m, e in zip(times, meas, exact)])],
            [Chart("Magnetization vs time", [f"{t:.2f}" for t in times],
                   {"simulated": meas.tolist(), "exact": exact.tolist()}, "line", "time", "⟨Z⟩/n")],
            "pass" if max_dev < 0.1 else "warn")


# =============================================================================
@register
class QuantumWalk(Experiment):
    id = "quantum_walk"
    title = "Discrete-time quantum walk on a line"
    category = "Simulation"
    summary = ("A quantum walker spreads BALLISTICALLY (distance ∝ steps), quadratically faster than a classical random "
               "walk (distance ∝ √steps) — the engine behind several quantum algorithms.")
    description = (
        "A coined quantum walk: a coin qubit is flipped by a Hadamard each step, and the walker moves right or left on "
        "a position register depending on the coin, in superposition. Interference makes the probability spread much "
        "faster than a classical random walk. The report measures the standard deviation of position after T steps and "
        "compares it to the classical √T scaling.")
    hardware_notes = "1 coin + m position qubits (default 5 → 32 sites); the shift is a controlled increment/decrement."
    params = [Param("position_qubits", "int", 5, "Position register size (2^m sites)", 3, 6),
              Param("steps", "int", 8, "Walk steps", 1, 20),
              Param("coin", "choice", "symmetric", "Initial coin state", choices=["symmetric", "right", "left"])]
    tutor = Tutor(
        concept="A quantum walk is the quantum version of a random walk. Instead of diffusing slowly, the walker's "
                "amplitude interferes and spreads ballistically — a quadratic speedup in how fast it explores.",
        how_it_works="Each step: flip a 'coin' qubit with a Hadamard, then move the walker right if the coin is |1⟩ and "
                     "left if |0⟩ — both at once, in superposition. The position register's amplitudes interfere across "
                     "steps, building a characteristic two-peaked, fast-spreading distribution.",
        intuition="A classical walker's position spreads like √T (diffusion). The quantum walker's spreads like T "
                  "(ballistic) because amplitudes, not probabilities, combine — the same reason light makes "
                  "interference fringes.",
        misconception="The distribution is NOT a bell curve — it has peaks at the edges, the fingerprint of quantum "
                      "interference. And 'ballistic' is a quadratic (√) edge in spreading, not an exponential one.",
        what_to_look_for="Position spread (standard deviation) growing roughly linearly with steps, well above the "
                         "classical √T line, with the characteristic twin-peaked distribution.",
        try_this=["Increase steps and watch the spread grow ∝ steps (ballistic), outpacing √steps.",
                  "Switch the coin to 'right' or 'left' for a lopsided walk.",
                  "Compare the twin-peaked quantum distribution to the single classical bell curve shown alongside."],
        real_world_use="Quantum walks power algorithms for element distinctness, graph search and network ranking, and "
                       "model energy transport in photosynthesis; continuous-time walks underlie some quantum speedups.",
        going_deeper="Grover's search can be recast as a quantum walk; the TFIM dynamics experiment is another look at "
                     "coherent evolution.",
        references=[{"title": "Quantum walk", "url": "https://en.wikipedia.org/wiki/Quantum_walk"}],
        prerequisites=["gates"],
    )

    def build(self, p):
        m = p["position_qubits"]
        N = 1 << m
        qc = Circuit(name=f"qwalk_m{m}")
        coin = qc.add_qreg("coin", 1)
        pos = qc.add_qreg("pos", m)
        creg = qc.add_creg("pos", m)
        center = N // 2
        for b in range(m):                       # start at the centre site
            if (center >> b) & 1:
                qc.x(pos[b])
        if p["coin"] == "symmetric":
            qc.h(coin[0]); qc.s(coin[0])         # (|0⟩ + i|1⟩)/√2 → symmetric spread
        elif p["coin"] == "right":
            qc.x(coin[0])
        inc = extend_permutation(tuple((x + 1) % N for x in range(N)), m)
        dec = extend_permutation(tuple((x - 1) % N for x in range(N)), m)
        for _ in range(p["steps"]):
            qc.h(coin[0])
            apply_permutation(qc, list(pos), inc, controls=[coin[0]], ctrl_state=1)   # coin=1 → right
            apply_permutation(qc, list(pos), dec, controls=[coin[0]], ctrl_state=0)   # coin=0 → left
        qc.measure(list(pos), creg)
        return Plan([qc], {"m": m, "center": center, "steps": p["steps"]})

    def analyze(self, p, ctx, results):
        m, center, steps = ctx["m"], ctx["center"], ctx["steps"]
        N = 1 << m
        res = results[0]
        counts = res.register("pos")
        probs = np.zeros(N)
        for k, c in counts.items():
            probs[int(k, 2)] += c / res.shots
        positions = np.arange(N) - center
        mean = float(np.sum(positions * probs))
        std = float(math.sqrt(max(0.0, np.sum((positions - mean) ** 2 * probs))))
        classical = math.sqrt(steps)
        ratio = std / classical if classical else 0.0
        rows = [[int(positions[i]), round(float(probs[i]), 4)] for i in range(N) if probs[i] > 1e-3]
        return Report(
            "Discrete-time quantum walk",
            [f"{steps} steps on {N} sites. Position spread σ = {std:.2f}.",
             f"Classical random walk would give σ ≈ √{steps} = {classical:.2f}; quantum/classical ratio = {ratio:.2f}.",
             "The ballistic (σ ∝ steps) spread and twin peaks are quantum interference at work."],
            {"std": std, "classical_std": classical, "ratio": ratio, "steps": steps, "mean": mean},
            [Table("Position distribution", ["position", "probability"], rows)],
            [Chart("Walker position distribution", [str(int(positions[i])) for i in range(N)],
                   {"quantum": probs.tolist()}, "bar", "position", "probability")],
            "pass" if ratio > 1.1 else "warn")


# =============================================================================
@register
class GHZMetrology(Experiment):
    id = "ghz_metrology"
    title = "GHZ-enhanced sensing (Heisenberg-limit metrology)"
    category = "Metrology"
    summary = ("Entangled GHZ probes sense a phase N times more sharply than N independent qubits — beating the "
               "standard quantum limit, the basis of quantum-enhanced sensors.")
    description = (
        "A sensor estimates an unknown phase φ. With N independent qubits (standard Ramsey interferometry) the signal "
        "oscillates as cos(φ) and precision improves as √N (the standard quantum limit). With an N-qubit GHZ state the "
        "accumulated phase is Nφ, so the parity oscillates as cos(Nφ) — N times faster — giving precision ∝ N (the "
        "Heisenberg limit). This experiment sweeps φ and measures both signals, extracting the N-fold frequency gain.")
    hardware_notes = "Sweeps N; each point is an N-qubit GHZ parity measurement. GHZ fragility limits useful N on hardware."
    params = [Param("n", "int", 4, "Number of entangled probe qubits N", 2, 8),
              Param("phases", "int", 32, "Phase points sampled", 8, 64),
              Param("phase_span", "float", 1.0, "Phase sweep span in full single-qubit periods (2π)", 0.5, 4)]
    tutor = Tutor(
        concept="Entanglement doesn't just help computing — it makes measurements sharper. N entangled qubits (a GHZ "
                "state) sense a phase N times more precisely than N separate qubits, beating the standard quantum limit.",
        how_it_works="Each probe accumulates the unknown phase φ. Independent qubits give a cos(φ) fringe; a GHZ state "
                     "accumulates Nφ collectively, so its parity oscillates as cos(Nφ) — N wiggles where the single "
                     "qubit makes one. The steeper fringe means a given phase change is easier to detect.",
        intuition="Precision is set by how fast the signal changes with φ. The GHZ state's N-times-faster oscillation "
                  "is an N-times-steeper slope, so the same measurement noise translates into an N-times-smaller phase "
                  "error — scaling 1/N (Heisenberg) instead of 1/√N (standard limit).",
        misconception="The catch: GHZ states are extremely fragile, so noise erodes the advantage fast — real sensors "
                      "trade entanglement depth against decoherence. The Heisenberg limit is a best case, not a free lunch.",
        what_to_look_for="The GHZ parity should oscillate N times faster than the single-qubit signal — the report "
                         "reports the measured frequency ratio, which should be ≈ N.",
        try_this=["Increase N and confirm the GHZ fringe frequency grows with N (the metrological gain).",
                  "Run on ibm:fake_fez and watch GHZ fragility shrink the fringe contrast as N grows.",
                  "Relate this to the GHZ experiment's parity oscillations — same physics, used for sensing."],
        real_world_use="GHZ/NOON-state metrology improves atomic clocks, gravimeters, magnetometers and LIGO-style "
                       "interferometers; squeezed and entangled probes are used in real precision sensors today.",
        references=[{"title": "Quantum metrology", "url": "https://en.wikipedia.org/wiki/Quantum_metrology"},
                    {"title": "Heisenberg limit", "url": "https://en.wikipedia.org/wiki/Heisenberg_limit"}],
        prerequisites=["ghz"],
    )

    def build(self, p):
        n, K = p["n"], p["phases"]
        phis = np.linspace(0, p["phase_span"] * 2 * math.pi, K)
        circuits = []
        for phi in phis:                          # single-qubit Ramsey (standard limit)
            qc = Circuit(1, name=f"ramsey1_{phi:.3f}")
            c = qc.add_creg("c", 1)
            qc.h(0); qc.rz(phi, 0); qc.h(0); qc.measure(0, c[0])
            circuits.append(qc)
        for phi in phis:                          # N-qubit GHZ parity (Heisenberg limit)
            qc = Circuit(n, name=f"ghz{n}_{phi:.3f}")
            c = qc.add_creg("c", n)
            qc.h(0)
            for i in range(n - 1):
                qc.cx(i, i + 1)
            qc.rz(phi, list(range(n)))
            for i in range(n - 2, -1, -1):
                qc.cx(i, i + 1)
            qc.h(0)
            qc.measure(list(range(n)), c)
            circuits.append(qc)
        return Plan(circuits, {"phis": phis.tolist(), "n": n})

    def analyze(self, p, ctx, results):
        n = p["n"]
        phis = np.array(ctx["phis"])
        K = len(phis)
        single = np.array([results[i].expectation_parity([0]) for i in range(K)])
        ghz = np.array([results[K + i].register("c").get("0" * n, 0) / results[K + i].shots -
                        (1 - results[K + i].register("c").get("0" * n, 0) / results[K + i].shots) for i in range(K)])
        f_single = _fringe_freq(phis, single)
        f_ghz = _fringe_freq(phis, ghz)
        ratio = f_ghz / f_single if f_single > 1e-6 else float("nan")
        return Report(
            "GHZ-enhanced metrology",
            [f"N = {n} entangled probes. Single-qubit fringe frequency {f_single:.2f}, GHZ fringe frequency {f_ghz:.2f}.",
             f"Frequency gain = {ratio:.2f} (ideal N = {n}) — the GHZ state senses the phase {n}× more sharply.",
             "This N-fold steeper fringe is the Heisenberg-limit advantage over the standard quantum limit."],
            {"n": n, "single_freq": f_single, "ghz_freq": f_ghz, "frequency_gain": ratio},
            [Table("Phase scan", ["φ", "single-qubit ⟨Z⟩", "GHZ parity"],
                   [[round(float(f), 3), round(float(s), 3), round(float(g), 3)] for f, s, g in zip(phis, single, ghz)])],
            [Chart("Interferometer fringes", [f"{f:.2f}" for f in phis],
                   {"single qubit": single.tolist(), f"GHZ (N={n})": ghz.tolist()}, "line", "φ", "signal")],
            "pass" if abs(ratio - n) < max(1.0, 0.25 * n) else "warn")


def _fringe_freq(phis, signal) -> float:
    """Dominant angular frequency of signal(φ) via a least-squares fit over candidate frequencies."""
    best = (np.inf, 0.0)
    span = phis[-1] - phis[0] if len(phis) > 1 else 1.0
    for f in np.linspace(0.2, 12, 400):
        M = np.vstack([np.cos(f * phis), np.sin(f * phis), np.ones_like(phis)]).T
        coef, *_ = np.linalg.lstsq(M, signal, rcond=None)
        err = float(np.sum((M @ coef - signal) ** 2))
        if err < best[0]:
            best = (err, f)
    return best[1]
