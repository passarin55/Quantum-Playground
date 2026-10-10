"""Quantum communication protocols: teleportation, superdense coding, BB84/BBM92 QKD, QRNG."""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

from ..core.circuit import Circuit
from ..core.statevector import Statevector, exact_distribution
from .base import Chart, Experiment, Param, Plan, Report, Table, counts_chart, register
from .library import (binary_entropy, bits_to_bytes, bits_to_hex, chi_square_bytes, monobit_pvalue, rng_from,
                      runs_pvalue, toeplitz_extract, von_neumann)


# =============================================================================
@register
class Teleportation(Experiment):
    id = "teleportation"
    title = "Quantum teleportation with state tomography"
    category = "Protocols"
    summary = "Teleport RY(θ)RZ(φ)|0⟩ from q0 to q2 and reconstruct it on Bob's side."
    description = ("`dynamic` mode uses real mid-circuit measurements and classically-conditioned X/Z "
                   "corrections (IBM dynamic circuits). `deferred` mode replaces them with controlled gates "
                   "(principle of deferred measurement) for devices without feed-forward. Bob's qubit is "
                   "measured in X, Y and Z to reconstruct its Bloch vector and the teleportation fidelity.")
    hardware_notes = "3 circuits × 3 qubits. Dynamic mode needs a backend with feed-forward (IBM Heron: yes)."
    params = [Param("theta", "float", 1.0, "Polar angle θ (rad)", 0, math.pi),
              Param("phi", "float", 0.7, "Azimuth φ (rad)", -math.pi, math.pi),
              Param("mode", "choice", "dynamic", "Correction style", choices=["dynamic", "deferred"])]

    def build(self, p):
        circuits = []
        for basis in "XYZ":
            qc = Circuit(3, name=f"teleport_{p['mode']}_{basis}")
            m = qc.add_creg("m", 2)
            bob = qc.add_creg("bob", 1)
            qc.ry(p["theta"], 0).rz(p["phi"], 0)
            qc.barrier()
            qc.h(1).cx(1, 2)
            qc.barrier()
            qc.cx(0, 1).h(0)
            if p["mode"] == "dynamic":
                qc.measure([0, 1], m)
                with qc.if_test(m[1], 1):
                    qc.x(2)
                with qc.if_test(m[0], 1):
                    qc.z(2)
            else:
                qc.cx(1, 2)
                qc.cz(0, 2)
                qc.measure([0, 1], m)
            if basis == "X":
                qc.h(2)
            elif basis == "Y":
                qc.sdg(2).h(2)
            qc.measure(2, bob[0])
            circuits.append(qc)
        return Plan(circuits, {"bases": "XYZ"})

    def analyze(self, p, ctx, results):
        ref = Circuit(1)
        ref.ry(p["theta"], 0).rz(p["phi"], 0)
        ideal = np.array(Statevector.from_circuit(ref).bloch_vector(0))
        r = []
        for res in results:
            b = res.register("bob")
            tot = sum(b.values())
            r.append((b.get("0", 0) - b.get("1", 0)) / tot)
        r = np.array(r)
        length = float(np.linalg.norm(r))
        if length > 1:   # finite-sampling can leave the Bloch ball; project back (physical state)
            r = r / length
        F = float((1 + np.dot(r, ideal)) / 2)
        verdict = "pass" if F > 2 / 3 else "warn"
        return Report(
            "Teleportation",
            [f"Teleported Bloch vector {np.round(r, 3).tolist()} (ideal {np.round(ideal, 3).tolist()})",
             f"Fidelity F = {F:.4f}; the best classical (measure-and-prepare) strategy averages 2/3."],
            {"fidelity": F, "bloch_length": length, "x": float(r[0]), "y": float(r[1]), "z": float(r[2])},
            [Table("Bloch components", ["axis", "ideal", "measured"],
                   [[a, round(float(i), 4), round(float(m), 4)] for a, i, m in zip("XYZ", ideal, r)])],
            [Chart("Bloch vector", ["X", "Y", "Z"], {"measured": r.tolist(), "ideal": ideal.tolist()})],
            verdict)


# =============================================================================
@register
class SuperdenseCoding(Experiment):
    id = "superdense"
    title = "Superdense coding: 2 classical bits in 1 qubit"
    category = "Protocols"
    summary = "Alice encodes 00/01/10/11 with I/X/Z/XZ on her half of a Bell pair; Bob decodes all 4."
    hardware_notes = "4 circuits × 2 qubits."
    params = []

    def build(self, p):
        circuits = []
        for msg in ("00", "01", "10", "11"):
            qc = Circuit(2, name=f"superdense_{msg}")
            c = qc.add_creg("c", 2)
            qc.h(0).cx(0, 1)
            if msg[1] == "1":
                qc.x(0)
            if msg[0] == "1":
                qc.z(0)
            qc.cx(0, 1).h(0)
            qc.measure([0, 1], c)
            circuits.append(qc)
        return Plan(circuits, {"messages": ["00", "01", "10", "11"]})

    def analyze(self, p, ctx, results):
        rows, rates = [], []
        build = self.build(p)
        for msg, res, qc in zip(ctx["messages"], results, build.circuits):
            ideal = max(exact_distribution(qc).items(), key=lambda kv: kv[1])[0]
            rate = res.counts.get(ideal, 0) / res.shots
            rates.append(rate)
            rows.append([msg, ideal, round(rate, 4)])
        mean = sum(rates) / 4
        return Report("Superdense coding",
                      [f"Average decoding success {mean:.4f} (ideal 1.0, random guessing 0.25)",
                       "Each 2-bit message travelled in a single qubit (plus pre-shared entanglement)."],
                      {"mean_success": mean},
                      [Table("Messages", ["sent", "decoded bitstring", "success"], rows)],
                      [Chart("Success per message", ctx["messages"], {"measured": rates})],
                      "pass" if mean > 0.9 else "warn")


# =============================================================================
def _cascade_correct(alice: list[int], bob: list[int], rng: np.random.Generator, passes: int = 4,
                     qber: float = 0.05) -> tuple[list[int], int]:
    """Simplified Cascade/BINARY: block parities + binary search. Returns (corrected bob, leaked bits)."""
    bob = list(bob)
    n = len(alice)
    leaked = 0
    if n == 0:
        return bob, 0
    k = max(4, int(0.73 / max(qber, 0.01)))
    for _ in range(passes):
        perm = rng.permutation(n)
        for start in range(0, n, k):
            idx = list(perm[start:start + k])
            pa = sum(alice[i] for i in idx) & 1
            pb = sum(bob[i] for i in idx) & 1
            leaked += 1
            while pa != pb and len(idx) > 1:
                half = idx[: len(idx) // 2]
                pa_h = sum(alice[i] for i in half) & 1
                pb_h = sum(bob[i] for i in half) & 1
                leaked += 1
                if pa_h != pb_h:
                    idx = half
                else:
                    idx = idx[len(idx) // 2:]
                    pa = sum(alice[i] for i in idx) & 1
                    pb = sum(bob[i] for i in idx) & 1
            if pa != pb and len(idx) == 1:
                bob[idx[0]] ^= 1
        k = min(n, 2 * k)
    return bob, leaked


@register
class BB84(Experiment):
    id = "bb84"
    title = "Quantum key distribution (BB84 / BBM92) with an eavesdropper"
    category = "Protocols"
    summary = "Distil a secret key; an intercept-resend eavesdropper shows up as ~25 % QBER."
    description = ("BB84: Alice prepares random bits in random Z/X bases (one shot per round); Bob measures "
                   "in random bases. BBM92: Bell pairs, both parties measure in random bases (many shots). "
                   "Eve intercepts a fraction of qubits in a random basis. Post-processing: sifting, QBER "
                   "estimation on a public sample, abort above 11 %, simplified Cascade error correction, "
                   "Toeplitz privacy amplification with the asymptotic BB84 rate 1 − 2h(QBER).")
    hardware_notes = "BB84 uses shots=1 circuits (rounds × qubits); BBM92 uses fewer circuits with many shots."
    params = [Param("protocol", "choice", "bb84", "Protocol", choices=["bb84", "bbm92"]),
              Param("qubits", "int", 12, "Qubits (BB84) or Bell pairs (BBM92) per circuit", 1, 12),
              Param("rounds", "int", 24, "Circuits", 1, 300),
              Param("eve", "float", 0.0, "Fraction of qubits intercepted by Eve", 0, 1),
              Param("pairs_shots", "int", 64, "Shots per circuit (BBM92 only)", 1, 4096),
              Param("seed", "int", 2024, "Seed for Alice/Bob/Eve basis choices (-1 = random)", -1, 2**31)]
    default_shots = 1

    def build(self, p):
        rng = rng_from(p["seed"])
        n, R = p["qubits"], p["rounds"]
        circuits, rounds = [], []
        bbm = p["protocol"] == "bbm92"
        for r in range(R):
            if bbm:
                qc = Circuit(2 * n, name=f"bbm92_round{r}")
                a = qc.add_creg("alice", n)
                b = qc.add_creg("bob", n)
                ab = rng.integers(0, 2, n).tolist()
                bb = rng.integers(0, 2, n).tolist()
                ev = (rng.random(n) < p["eve"]).tolist()
                eb = rng.integers(0, 2, n).tolist()
                e = qc.add_creg("eve", n) if any(ev) else None
                for i in range(n):
                    qc.h(2 * i).cx(2 * i, 2 * i + 1)
                for i in range(n):
                    if ev[i]:
                        if eb[i]:
                            qc.h(2 * i + 1)
                        qc.measure(2 * i + 1, e[i])
                        if eb[i]:
                            qc.h(2 * i + 1)
                for i in range(n):
                    if ab[i]:
                        qc.h(2 * i)
                    if bb[i]:
                        qc.h(2 * i + 1)
                    qc.measure(2 * i, a[i])
                    qc.measure(2 * i + 1, b[i])
                rounds.append({"alice_basis": ab, "bob_basis": bb, "eve": ev, "eve_basis": eb})
            else:
                qc = Circuit(n, name=f"bb84_round{r}")
                b = qc.add_creg("bob", n)
                bits = rng.integers(0, 2, n).tolist()
                ab = rng.integers(0, 2, n).tolist()
                bb = rng.integers(0, 2, n).tolist()
                ev = (rng.random(n) < p["eve"]).tolist()
                eb = rng.integers(0, 2, n).tolist()
                e = qc.add_creg("eve", n) if any(ev) else None
                for i in range(n):
                    if bits[i]:
                        qc.x(i)
                    if ab[i]:
                        qc.h(i)
                for i in range(n):
                    if ev[i]:
                        if eb[i]:
                            qc.h(i)
                        qc.measure(i, e[i])
                        if eb[i]:
                            qc.h(i)
                for i in range(n):
                    if bb[i]:
                        qc.h(i)
                    qc.measure(i, b[i])
                rounds.append({"alice_bits": bits, "alice_basis": ab, "bob_basis": bb, "eve": ev, "eve_basis": eb})
            circuits.append(qc)
        shots = p["pairs_shots"] if bbm else 1
        return Plan(circuits, {"rounds": rounds}, memory=True, shots=shots)

    def analyze(self, p, ctx, results):
        rng = rng_from(None if p["seed"] < 0 else p["seed"] + 1)
        n = p["qubits"]
        alice, bob = [], []
        raw = 0
        for info, res in zip(ctx["rounds"], results):
            bob_mem = res.register_memory("bob") if res.memory else [k for k, v in res.register("bob").items()
                                                                     for _ in range(v)]
            alice_mem = None
            if p["protocol"] == "bbm92":
                alice_mem = res.register_memory("alice") if res.memory else None
            for s, bstr in enumerate(bob_mem):
                for i in range(n):
                    raw += 1
                    if info["alice_basis"][i] != info["bob_basis"][i]:
                        continue
                    bbit = int(bstr[n - 1 - i])
                    if p["protocol"] == "bbm92":
                        abit = int(alice_mem[s][n - 1 - i])
                    else:
                        abit = info["alice_bits"][i]
                    alice.append(abit)
                    bob.append(bbit)
        sifted = len(alice)
        if sifted < 8:
            return Report("QKD", ["Too few sifted bits; increase rounds/qubits."], {"sifted": sifted}, verdict="fail")
        idx = rng.permutation(sifted)
        sample = idx[: sifted // 2]
        keep = sorted(idx[sifted // 2:])
        errors = sum(alice[i] != bob[i] for i in sample)
        qber = errors / max(1, len(sample))
        true_errors = sum(alice[i] != bob[i] for i in keep)
        ka = [alice[i] for i in keep]
        kb = [bob[i] for i in keep]
        aborted = qber > 0.11
        summary = [f"Raw transmissions: {raw}, sifted: {sifted}, sample revealed: {len(sample)}",
                   f"Estimated QBER = {qber:.2%} (Eve intercepting a fraction f adds ≈ f × 25 %)"]
        metrics = {"raw": raw, "sifted": sifted, "qber": qber, "eve_fraction": p["eve"],
                   "expected_qber_from_eve": 0.25 * p["eve"]}
        if aborted:
            summary.append("ABORT: QBER above 11 % — an eavesdropper (or a very noisy channel) is present.")
            return Report("QKD", summary, metrics, verdict="warn" if p["eve"] > 0 else "fail",
                          notes=["No key is produced when the protocol aborts."])
        kb_corr, leaked = _cascade_correct(ka, kb, rng, qber=max(qber, 0.01))
        residual = sum(x != y for x, y in zip(ka, kb_corr))
        rate = max(0.0, 1 - 2 * binary_entropy(max(qber, 1e-9)))
        final_len = max(0, int(len(ka) * rate) - leaked) if qber > 0 else max(0, len(ka) - leaked)
        final_len = min(final_len, len(ka))
        seed_bits = rng.integers(0, 2, len(ka) + max(final_len, 1)).tolist()
        key_a = toeplitz_extract(ka, final_len, seed_bits)
        key_b = toeplitz_extract(kb_corr, final_len, seed_bits)
        agree = key_a == key_b
        summary += [f"Error correction leaked {leaked} parity bits; corrected {true_errors - residual} of "
                    f"{true_errors} errors",
                    f"Final secret key: {final_len} bits, Alice/Bob keys identical: {agree}",
                    f"Key (hex): {bits_to_hex(key_a)[:64] or '(shorter than one byte)'}"]
        metrics.update({"errors_in_key_before_ec": true_errors, "residual_errors": residual, "leaked": leaked,
                        "final_key_bits": final_len, "keys_agree": agree, "secret_fraction": rate})
        verdict = "pass" if agree and final_len > 0 else "warn"
        return Report("Quantum key distribution", summary, metrics,
                      charts=[Chart("Key budget", ["raw", "sifted", "kept", "final"],
                                    {"bits": [raw, sifted, len(ka), final_len]})],
                      verdict=verdict)


# =============================================================================
@register
class QRNG(Experiment):
    id = "qrng"
    title = "Quantum random number generator + randomness tests"
    category = "Protocols"
    summary = "Measure |+⟩ states, test the bits (NIST-style monobit/runs, χ²) and extract with Toeplitz hashing."
    hardware_notes = "1 circuit; bits = qubits × shots. Hardware bias per qubit is visible in the table."
    params = [Param("qubits", "int", 8, "Qubits measured in parallel", 1, 26),
              Param("extractor", "choice", "toeplitz", "Randomness extractor",
                    choices=["none", "von_neumann", "toeplitz"])]
    default_shots = 1024

    def build(self, p):
        n = p["qubits"]
        qc = Circuit(n, name=f"qrng_{n}")
        c = qc.add_creg("c", n)
        qc.h(list(range(n)))
        qc.measure(list(range(n)), c)
        return Plan([qc], {}, memory=True)

    def analyze(self, p, ctx, results):
        res = results[0]
        n = p["qubits"]
        mem = res.memory or [k for k, v in res.counts.items() for _ in range(v)]
        bits = [int(ch) for m in mem for ch in m]
        per_q = []
        for q in range(n):
            ones = sum(int(m[n - 1 - q]) for m in mem)
            per_q.append(ones / len(mem))
        max_p = max(max(x, 1 - x) for x in per_q)
        hmin = -math.log2(max_p) if max_p < 1 else 0.0
        if p["extractor"] == "von_neumann":
            out = von_neumann(bits)
        elif p["extractor"] == "toeplitz":
            out_len = int(len(bits) * hmin * 0.9)
            seed = np.random.default_rng(12345).integers(0, 2, len(bits) + out_len).tolist()
            out = toeplitz_extract(bits, out_len, seed) if out_len > 0 else []
        else:
            out = bits
        mono, runs = monobit_pvalue(out), runs_pvalue(out)
        chi, chi_p = chi_square_bytes(bits_to_bytes(out))
        ok = all(x > 0.01 for x in (mono, runs) if not math.isnan(x))
        return Report(
            "Quantum random bits",
            [f"Raw bits: {len(bits)}; per-qubit min-entropy bound {hmin:.4f} bits/bit",
             f"Extractor '{p['extractor']}' → {len(out)} output bits",
             f"Monobit p = {mono:.4f}, runs p = {runs:.4f}" + (f", byte χ² p = {chi_p:.4f}" if not math.isnan(chi_p) else ""),
             f"Sample (hex): {bits_to_hex(out)[:64]}"],
            {"raw_bits": len(bits), "output_bits": len(out), "min_entropy_per_bit": hmin, "monobit_p": mono,
             "runs_p": runs, "chi2_p": chi_p},
            [Table("Per-qubit bias", ["qubit", "P(1)", "bias"], [[q, round(x, 4), round(x - 0.5, 4)]
                                                                 for q, x in enumerate(per_q)])],
            [Chart("P(1) per qubit", [f"q{q}" for q in range(n)], {"measured": per_q, "ideal": [0.5] * n})],
            "pass" if ok else "warn",
            notes=["Statistical tests can reject bad generators but never prove randomness; the security "
                   "argument comes from the measurement physics plus the extractor."])
