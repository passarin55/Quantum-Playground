"""Combinatorial optimization with QAOA: portfolio selection and maximum independent set.

Both reduce a business problem to a QUBO (quadratic unconstrained binary optimization),
map it to an Ising Hamiltonian, and solve it with the Quantum Approximate Optimization
Algorithm. Angles are optimised on the exact simulator; the circuit then samples
candidate solutions on the chosen backend, compared against a brute-force optimum.
"""
from __future__ import annotations

import itertools
import math

import numpy as np

from ..core.circuit import Circuit
from ..core.statevector import Statevector
from ..optim import multistart
from .base import Chart, Experiment, Param, Plan, Report, Table, Tutor, counts_chart, register


def qubo_to_ising(Q: np.ndarray, c: float = 0.0):
    """x^T Q x + c (x∈{0,1}) → Σ h_i Z_i + Σ_{i<j} J_ij Z_i Z_j + offset, with x_i=(1−Z_i)/2."""
    n = Q.shape[0]
    Q = (Q + Q.T) / 2
    h = np.zeros(n)
    J = np.zeros((n, n))
    offset = c
    for i in range(n):
        offset += Q[i, i] / 2
        h[i] -= Q[i, i] / 2
        for j in range(i + 1, n):
            offset += Q[i, j] / 2
            h[i] -= Q[i, j] / 2
            h[j] -= Q[i, j] / 2
            J[i, j] += Q[i, j] / 2
    return h, J, offset


def qubo_energy(Q: np.ndarray, x: np.ndarray, c: float = 0.0) -> float:
    return float(x @ Q @ x + c)


def qaoa_circuit(h, J, gammas, betas, measure=True) -> Circuit:
    n = len(h)
    qc = Circuit(n, name=f"qaoa_p{len(gammas)}")
    qc.h(list(range(n)))
    for g, b in zip(gammas, betas):
        for i in range(n):
            if abs(h[i]) > 1e-12:
                qc.rz(2 * g * h[i], i)
        for i in range(n):
            for j in range(i + 1, n):
                if abs(J[i, j]) > 1e-12:
                    qc.rzz(2 * g * J[i, j], i, j)
        qc.rx(2 * b, list(range(n)))
    if measure:
        qc.measure_all(register_name="c")
    return qc


def _ising_diag(h, J, offset) -> np.ndarray:
    """Energy of every bitstring (z_i = ±1, x_i = (1−z)/2)."""
    n = len(h)
    e = np.full(1 << n, offset, dtype=float)
    for s in range(1 << n):
        z = np.array([1 if not (s >> i) & 1 else -1 for i in range(n)])
        e[s] += h @ z + sum(J[i, j] * z[i] * z[j] for i in range(n) for j in range(i + 1, n))
    return e


def optimize_qaoa(Q, c, layers, minimize=True, starts=6, seed=3):
    h, J, offset = qubo_to_ising(np.asarray(Q, float), c)
    n = len(h)
    diag = _ising_diag(h, J, offset)      # = qubo value for each bitstring (little-endian)
    sign = 1 if minimize else -1

    def objective(params):
        probs = Statevector.from_circuit(qaoa_circuit(h, J, params[:layers], params[layers:], measure=False)).probabilities()
        return sign * float(probs @ diag)

    res = multistart(objective, 2 * layers, starts=starts, seed=seed, low=0, high=math.pi)
    return h, J, offset, diag, res


def brute_force(Q, c, minimize=True):
    n = Q.shape[0]
    best = None
    for s in range(1 << n):
        x = np.array([(s >> i) & 1 for i in range(n)])
        e = qubo_energy(Q, x, c)
        if best is None or (e < best[1] if minimize else e > best[1]):
            best = (s, e, x)
    return best


@register
class QAOAPortfolio(Experiment):
    id = "qaoa_portfolio"
    title = "QAOA portfolio optimization (finance)"
    category = "Optimization"
    summary = ("Pick the best B of n assets to balance expected return against risk, encoded as a QUBO and solved with "
               "QAOA — the canonical quantum-finance use case.")
    description = (
        "Mean-variance portfolio selection: maximise expected return μ·x minus risk-aversion q·(xᵀΣx), subject to "
        "choosing exactly B assets (a budget penalty λ(Σxᵢ−B)²). This becomes a QUBO, maps to an Ising Hamiltonian, and "
        "QAOA samples low-'energy' (high-quality) portfolios. The report compares the sampled portfolio to the "
        "brute-force optimum and checks the budget constraint.")
    hardware_notes = "One qubit per asset (default 6). Each asset pair contributes an RZZ per layer."
    params = [Param("assets", "int", 6, "Number of candidate assets", 2, 10),
              Param("budget", "int", 3, "Assets to hold (budget)", 1, 9),
              Param("risk_aversion", "float", 0.5, "Risk-aversion q (higher = more cautious)", 0, 5),
              Param("penalty", "float", 2.0, "Budget-constraint penalty strength λ", 0.1, 20),
              Param("layers", "int", 2, "QAOA layers p", 1, 4),
              Param("seed", "int", 7, "Seed for the synthetic market (returns/covariance)", 0, 2**31)]
    tutor = Tutor(
        concept="Choosing a portfolio — which assets to hold to maximise return for a given risk — is a hard "
                "combinatorial problem at scale. It's the flagship quantum-finance demo: encode it as a QUBO and let "
                "QAOA search good portfolios.",
        how_it_works="Expected returns and a covariance (risk) matrix define an objective: reward return, penalise risk "
                     "and penalise breaking the budget. That becomes an Ising energy; QAOA prepares a superposition "
                     "biased toward low-energy (good) portfolios and samples them.",
        intuition="The covariance terms become qubit-qubit (RZZ) interactions; the return and budget terms become "
                  "single-qubit fields. QAOA's cost layer makes good portfolios 'heavier', the mixer lets amplitude flow "
                  "toward them.",
        misconception="This is a heuristic on a tiny synthetic market — not investment advice and not a proven advantage "
                      "over classical optimisers. Real portfolio optimisation has far more assets and constraints; this "
                      "shows the ENCODING and the method, not a trading edge.",
        what_to_look_for="The sampled portfolio's return/risk vs the brute-force optimum, and whether the budget "
                         "constraint (exactly B assets) is satisfied. More layers (p) improve the approximation.",
        try_this=["Raise risk_aversion and watch the chosen portfolio shift toward low-covariance assets.",
                  "Increase layers (p) and see the approximation ratio improve.",
                  "Change the market seed to get a different returns/covariance instance."],
        real_world_use="Banks and asset managers (e.g. via Qiskit Finance, D-Wave) pilot QAOA/annealing for portfolio "
                       "optimisation, index tracking and risk analysis.",
        going_deeper="Max-independent-set and MaxCut use the same QUBO→Ising→QAOA machinery for networks and scheduling.",
        references=[{"title": "Qiskit Finance: Portfolio Optimization", "url": "https://qiskit-community.github.io/qiskit-finance/"},
                    {"title": "QAOA", "url": "https://en.wikipedia.org/wiki/Quantum_optimization_algorithms"}],
        prerequisites=["qaoa_maxcut"],
    )

    def _market(self, p):
        rng = np.random.default_rng(p["seed"])
        n = p["assets"]
        mu = rng.uniform(0.02, 0.18, n)
        A = rng.normal(0, 1, (n, n))
        sigma = (A @ A.T) / n * 0.1 + np.eye(n) * 0.02       # SPD covariance
        return mu, sigma

    def _qubo(self, p, mu, sigma):
        n, B, q, lam = p["assets"], p["budget"], p["risk_aversion"], p["penalty"]
        Q = np.zeros((n, n))
        for i in range(n):
            Q[i, i] += -mu[i] + q * sigma[i, i] + lam * (1 - 2 * B)
            for j in range(n):
                if i != j:
                    Q[i, j] += q * sigma[i, j] + lam
        return Q, lam * B * B

    def build(self, p):
        if p["budget"] > p["assets"]:
            raise ValueError("budget cannot exceed the number of assets")
        mu, sigma = self._market(p)
        Q, c = self._qubo(p, mu, sigma)
        h, J, offset, diag, res = optimize_qaoa(Q, c, p["layers"])
        qc = qaoa_circuit(h, J, res.x[:p["layers"]], res.x[p["layers"]:])
        return Plan([qc], {"mu": mu.tolist(), "sigma": sigma.tolist(), "Q": Q.tolist(), "c": c,
                           "params": res.x, "layers": p["layers"]})

    def analyze(self, p, ctx, results):
        mu = np.array(ctx["mu"]); sigma = np.array(ctx["sigma"]); Q = np.array(ctx["Q"]); c = ctx["c"]
        n = p["assets"]
        res = results[0]
        s_opt, e_opt, x_opt = brute_force(Q, c, minimize=True)
        # most frequent sampled portfolio
        best_bits = res.most_frequent()
        x = np.array([int(best_bits[n - 1 - i]) for i in range(n)])
        ret = float(mu @ x); risk = float(x @ sigma @ x); held = int(x.sum())
        opt_ret = float(mu @ x_opt); opt_risk = float(x_opt @ sigma @ x_opt)
        p_opt = sum(c2 for k, c2 in res.counts.items()
                    if np.array_equal(np.array([int(k[n - 1 - i]) for i in range(n)]), x_opt)) / res.shots
        feasible = held == p["budget"]
        rows = [[f"asset {i}", round(mu[i], 3), round(sigma[i, i], 3), "✓" if x[i] else ""] for i in range(n)]
        return Report(
            "QAOA portfolio optimization",
            [f"Chose {held} of {n} assets (budget {p['budget']}): indices {[int(i) for i in np.nonzero(x)[0]]}.",
             f"Portfolio return {ret:.3f}, risk {risk:.3f}. Brute-force optimum: return {opt_ret:.3f}, risk {opt_risk:.3f}.",
             f"Budget constraint satisfied: {feasible}. P(sampling the optimal portfolio) = {p_opt:.4f}."],
            {"held": held, "return": ret, "risk": risk, "optimal_return": opt_ret, "optimal_risk": opt_risk,
             "feasible": feasible, "p_optimal": p_opt},
            [Table("Assets (expected return, variance, held)", ["asset", "E[return]", "variance", "held"], rows)],
            [counts_chart("Sampled portfolios", res.counts, top=16,
                          ideal={format(s_opt, f"0{n}b"): 1.0})],
            "pass" if feasible and p_opt > 2 / (1 << n) else "warn")


@register
class QAOAMaxIndependentSet(Experiment):
    id = "qaoa_mis"
    title = "QAOA maximum independent set (scheduling / networks)"
    category = "Optimization"
    summary = ("Find the largest set of mutually non-conflicting items — wireless channels, compatible jobs, "
               "non-adjacent nodes — as a QUBO solved with QAOA.")
    description = (
        "Maximum independent set: pick the most vertices of a graph with no edge between any two. It models "
        "conflict-free allocation (frequencies, time slots, non-interfering transmitters). As a QUBO we maximise the "
        "number chosen minus a penalty for every conflicting pair selected, then solve with QAOA and compare to the "
        "brute-force maximum.")
    hardware_notes = "One qubit per vertex (default from the graph); each edge is an RZZ per layer."
    params = [Param("edges", "str", "0-1,1-2,2-3,3-4,4-0,0-2", "Graph edges a-b, comma separated"),
              Param("penalty", "float", 3.0, "Conflict penalty λ (≥ 2 guarantees independence)", 1, 20),
              Param("layers", "int", 2, "QAOA layers p", 1, 4)]
    tutor = Tutor(
        concept="Maximum independent set asks for the biggest group of items that don't conflict — the backbone of "
                "channel assignment, scheduling and resource allocation. It's a natural QUBO for QAOA.",
        how_it_works="Each vertex is a qubit (in/out of the set). The objective rewards including vertices but penalises "
                     "any selected pair joined by an edge (a conflict). QAOA samples high-reward, conflict-free selections.",
        intuition="Edges become penalty (RZZ) couplings that make conflicting pairs costly; the reward is a single-qubit "
                  "field. A large enough penalty guarantees the best solutions are genuinely independent.",
        misconception="MIS is NP-hard, and QAOA gives approximate solutions with no guaranteed quantum advantage — the "
                      "value is the modelling pattern and the approximation quality, demonstrated against brute force.",
        what_to_look_for="The sampled set's size vs the true maximum, and that it's a valid independent set (no edges "
                         "inside it).",
        try_this=["Edit the graph and watch the maximum independent set change.",
                  "Lower the penalty below 2 and see conflicting vertices sneak in (invalid sets).",
                  "Add layers (p) to improve the approximation ratio."],
        real_world_use="Independent-set and graph-coloring QUBOs model frequency assignment, register allocation, "
                       "timetabling and wireless scheduling — all piloted on QAOA and quantum annealers.",
        going_deeper="Graph coloring extends this to k colors; portfolio optimization uses the same QUBO toolkit for finance.",
        references=[{"title": "Independent set (graph theory)", "url": "https://en.wikipedia.org/wiki/Independent_set_(graph_theory)"},
                    {"title": "Ising formulations of NP problems (Lucas 2014)", "url": "https://arxiv.org/abs/1302.5843"}],
        prerequisites=["qaoa_maxcut"],
    )

    def _parse(self, text):
        edges = []
        for tok in text.replace(";", ",").split(","):
            tok = tok.strip()
            if not tok:
                continue
            a, b = (int(x) for x in tok.replace(" ", "").split("-"))
            edges.append((min(a, b), max(a, b)))
        if not edges:
            raise ValueError("graph has no edges")
        return sorted(set(edges))

    def build(self, p):
        edges = self._parse(p["edges"])
        n = max(max(e) for e in edges) + 1
        if n > 14:
            raise ValueError("at most 14 vertices")
        lam = p["penalty"]
        Q = np.zeros((n, n))
        for i in range(n):
            Q[i, i] -= 1.0                     # reward choosing vertex i
        for a, b in edges:
            Q[a, b] += lam                     # penalise choosing both endpoints of an edge
        h, J, offset, diag, res = optimize_qaoa(Q, 0.0, p["layers"])
        qc = qaoa_circuit(h, J, res.x[:p["layers"]], res.x[p["layers"]:])
        return Plan([qc], {"n": n, "edges": edges, "Q": Q.tolist(), "layers": p["layers"]})

    def analyze(self, p, ctx, results):
        n, edges = ctx["n"], [tuple(e) for e in ctx["edges"]]
        Q = np.array(ctx["Q"])
        res = results[0]

        def independent(x):
            return all(not (x[a] and x[b]) for a, b in edges)

        # true maximum independent set
        best = max(range(1 << n), key=lambda s: (sum((s >> i) & 1 for i in range(n))
                   if independent([(s >> i) & 1 for i in range(n)]) else -1))
        max_size = sum((best >> i) & 1 for i in range(n))
        bits = res.most_frequent()
        x = [int(bits[n - 1 - i]) for i in range(n)]
        size = sum(x)
        valid = independent(x)
        p_opt = sum(c for k, c in res.counts.items()
                    if independent([int(k[n - 1 - i]) for i in range(n)])
                    and sum(int(k[n - 1 - i]) for i in range(n)) == max_size) / res.shots
        return Report(
            "QAOA maximum independent set",
            [f"Graph: {n} vertices, {len(edges)} edges. Maximum independent set size: {max_size}.",
             f"Sampled set {[i for i in range(n) if x[i]]} (size {size}), valid (conflict-free): {valid}.",
             f"P(sampling a maximum independent set) = {p_opt:.4f}."],
            {"n": n, "max_size": max_size, "sampled_size": size, "valid": valid, "p_optimal": p_opt},
            [Table("Vertices chosen", ["vertex", "chosen"], [[i, "✓" if x[i] else ""] for i in range(n)])],
            [counts_chart("Sampled selections", res.counts, top=16)],
            "pass" if valid and p_opt > 1 / (1 << n) else "warn")
