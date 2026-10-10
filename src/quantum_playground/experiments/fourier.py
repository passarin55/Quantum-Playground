"""Fourier-family algorithms: QFT round trip / period finding, phase estimation, Shor order finding."""
from __future__ import annotations

import math
from fractions import Fraction

import numpy as np

from ..core.circuit import Circuit
from ..core.synthesis import apply_permutation
from .base import Chart, Experiment, Param, Plan, Report, Table, counts_chart, register
from .library import continued_fraction_candidates, fourier_state, multiplicative_order, qft


@register
class QFTExperiment(Experiment):
    id = "qft"
    title = "Quantum Fourier transform: round trip and period finding"
    category = "Fourier"
    summary = "Encode an integer in Fourier phases and read it back with QFT†, or reveal a period with the QFT."
    description = ("`fourier_state`: prepare QFT|y⟩ with H + phase gates, apply the inverse QFT, measure y. "
                   "`periodic`: prepare a uniform superposition over multiples of r (r a power of two), apply "
                   "the QFT, and observe peaks at multiples of 2^n / r.")
    params = [Param("n", "int", 5, "Qubits", 2, 12),
              Param("mode", "choice", "fourier_state", "Demo", choices=["fourier_state", "periodic"]),
              Param("value", "int", 13, "Integer y (fourier_state) or period r (periodic, power of 2)", 1, 4095)]

    def build(self, p):
        n = p["n"]
        qc = Circuit(n, name=f"qft_{p['mode']}")
        c = qc.add_creg("c", n)
        q = list(range(n))
        if p["mode"] == "fourier_state":
            y = p["value"] % (1 << n)
            fourier_state(qc, q, y)
            qc.barrier()
            qft(qc, q, inverse=True)
            ideal = {format(y, f"0{n}b"): 1.0}
        else:
            r = p["value"]
            if r & (r - 1) or r >= (1 << n):
                raise ValueError("period must be a power of two smaller than 2^n")
            k = r.bit_length() - 1
            qc.h(q[k:])                         # superposition of multiples of r
            qc.barrier()
            qft(qc, q)
            ideal = {format(j * ((1 << n) // r), f"0{n}b"): 1 / r for j in range(r)}
        qc.measure(q, c)
        return Plan([qc], {"ideal": ideal})

    def analyze(self, p, ctx, results):
        res = results[0]
        ideal = ctx["ideal"]
        succ = sum(res.counts.get(k, 0) for k in ideal) / res.shots
        return Report("QFT", [f"Probability mass on ideal outcomes: {succ:.4f}"], {"ideal_mass": succ},
                      charts=[counts_chart("Outcomes", res.counts, top=32, ideal=ideal)],
                      verdict="pass" if succ > 0.5 else "warn")


@register
class PhaseEstimation(Experiment):
    id = "qpe"
    title = "Quantum phase estimation of P(2πφ)"
    category = "Fourier"
    summary = "Estimate the eigenphase φ of a phase gate with t counting qubits (precision 2^-t)."
    params = [Param("phi", "float", 0.3125, "Eigenphase φ in [0, 1)", 0, 0.999999),
              Param("t", "int", 5, "Counting qubits", 1, 12)]

    def build(self, p):
        t = p["t"]
        qc = Circuit(name="qpe")
        cnt = qc.add_qreg("count", t)
        tgt = qc.add_qreg("eig", 1)
        c = qc.add_creg("c", t)
        qc.x(tgt[0])
        qc.h(cnt)
        for k in range(t):
            qc.cp(2 * math.pi * p["phi"] * (1 << k), cnt[k], tgt[0])
        qft(qc, list(cnt), inverse=True)
        qc.measure(cnt, c)
        return Plan([qc], {})

    def analyze(self, p, ctx, results):
        t = p["t"]
        res = results[0]
        best = res.most_frequent()
        est = int(best, 2) / (1 << t)
        exact = round(p["phi"] * (1 << t)) % (1 << t)
        near = {format((exact + d) % (1 << t), f"0{t}b") for d in (-1, 0, 1)}
        p_near = sum(res.counts.get(k, 0) for k in near) / res.shots
        return Report("Phase estimation",
                      [f"φ = {p['phi']}, estimate = {est} (resolution {1 / (1 << t):.5f})",
                       f"P(within ±1 bin) = {p_near:.4f} (ideal ≥ 0.81 for any φ)"],
                      {"phi": p["phi"], "estimate": est, "abs_error": abs(est - p["phi"]), "p_within_1": p_near},
                      charts=[counts_chart("Counting register", res.counts, top=32)],
                      verdict="pass" if abs(est - p["phi"]) <= 1 / (1 << t) else "warn")


@register
class Shor(Experiment):
    id = "shor"
    title = "Shor's algorithm: order finding and factoring"
    category = "Fourier"
    summary = "Quantum order finding of a mod N with exact reversible modular multipliers, then classical factoring."
    description = ("Controlled multiplication by a^(2^k) mod N is compiled as an exact permutation of the work "
                   "register (values ≥ N fixed) with transformation-based synthesis — a full modular "
                   "multiplier on every basis state, not a shortcut that assumes the answer. Continued fractions "
                   "turn each measured y/2^t into a candidate order r; factors follow from gcd(a^(r/2) ± 1, N).")
    params = [Param("N", "int", 15, "Number to factor (odd composite, ≤ 63)", 15, 63),
              Param("a", "int", 7, "Base coprime to N", 2, 62),
              Param("t", "int", 0, "Counting qubits (0 = 2·⌈log2 N⌉, capped at 12)", 0, 12)]
    hardware_notes = "N=15: 12 qubits. Multipliers compile to hundreds of 2q gates — a stress test on hardware."

    def build(self, p):
        N, a = p["N"], p["a"]
        if N % 2 == 0 or all(N % k for k in range(3, int(math.isqrt(N)) + 1, 2)):
            raise ValueError("N must be an odd composite number")
        if math.gcd(a, N) != 1:
            raise ValueError(f"gcd({a}, {N}) = {math.gcd(a, N)} already factors N — choose a coprime a")
        n = (N - 1).bit_length()
        t = p["t"] or min(12, 2 * n)
        qc = Circuit(name=f"shor_N{N}_a{a}")
        cnt = qc.add_qreg("count", t)
        work = qc.add_qreg("work", n)
        c = qc.add_creg("c", t)
        qc.x(work[0])
        qc.h(cnt)
        for k in range(t):
            m = pow(a, 1 << k, N)
            if m == 1:
                continue
            perm = [(m * x) % N if x < N else x for x in range(1 << n)]
            apply_permutation(qc, list(work), perm, controls=[cnt[k]])
        qft(qc, list(cnt), inverse=True)
        qc.measure(cnt, c)
        return Plan([qc], {"n_work": n, "t": t})

    def analyze(self, p, ctx, results):
        N, a = p["N"], p["a"]
        t = ctx["t"]
        res = results[0]
        true_r = multiplicative_order(a, N)
        rows, good_shots, factor_set = [], 0, set()
        for key, cnt in sorted(res.counts.items(), key=lambda kv: -kv[1]):
            y = int(key, 2)
            cands = [r for r in continued_fraction_candidates(y, t, N) if pow(a, r, N) == 1]
            r = min(cands) if cands else None
            factors = []
            if r and r % 2 == 0:
                x = pow(a, r // 2, N)
                factors = sorted({g for g in (math.gcd(x - 1, N), math.gcd(x + 1, N)) if 1 < g < N})
            if factors:
                good_shots += cnt
                factor_set.update(factors)
            if len(rows) < 12:
                rows.append([key, y, f"{Fraction(y, 1 << t)}", round(cnt / res.shots, 4), r or "-",
                             " × ".join(map(str, factors)) or "-"])
        frac = good_shots / res.shots
        ok = bool(factor_set)
        return Report(f"Shor order finding for N = {N}, a = {a}",
                      [f"True order r = {true_r}; peaks expected at multiples of 2^{t}/{true_r}",
                       f"Shots giving a non-trivial factor: {frac:.2%}",
                       f"Factors found: {sorted(factor_set) or 'none'}"],
                      {"order": true_r, "success_fraction": frac, "factors": sorted(factor_set),
                       "qubits": t + ctx["n_work"]},
                      [Table("Measured phases", ["bits", "y", "y/2^t", "freq", "order r", "factors"], rows)],
                      [counts_chart("Counting register", res.counts, top=32)],
                      "pass" if ok else "warn")
