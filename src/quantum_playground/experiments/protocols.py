"""Quantum communication protocols: teleportation, superdense coding, BB84/BBM92 QKD, QRNG."""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

from ..core.circuit import Circuit
from ..core.statevector import Statevector, exact_distribution
from .base import Chart, Experiment, Param, Plan, Report, Table, Tutor, counts_chart, register
from .library import (binary_entropy, bits_to_bytes, bits_to_hex, chi_square_bytes, monobit_pvalue, rng_from,
                      runs_pvalue, toeplitz_extract, von_neumann)


# =============================================================================
@register
class Teleportation(Experiment):
    id = "teleportation"
    tutor = Tutor(
        concept="Quantum teleportation moves an unknown qubit state from Alice to Bob using one shared Bell pair and "
                "two classical bits — without ever measuring (and thus destroying) the state in transit.",
        how_it_works="Alice entangles the mystery qubit with her half of a Bell pair and measures both (a Bell-basis "
                     "measurement). She sends the two outcome bits to Bob, who applies an X and/or Z correction to his "
                     "half, which then becomes an exact copy of the original. The original is gone — no cloning violated.",
        intuition="You're not copying the qubit, you're relocating it. The entangled pair is the 'wire'; the two "
                  "classical bits tell Bob which of four rotations undoes the randomness Alice's measurement injected.",
        misconception="No matter or energy teleports, and it's not faster-than-light: Bob's qubit is useless until the "
                      "two classical bits arrive over an ordinary channel. 'dynamic' mode uses real mid-circuit "
                      "measurement + feed-forward; 'deferred' mode fakes it with controlled gates for simpler hardware.",
        what_to_look_for="The report reconstructs Bob's Bloch vector from X/Y/Z measurements and reports fidelity with "
                         "the original. Above 2/3 beats the best 'measure-and-resend' classical strategy; ideal is 1.",
        try_this=["Change theta/phi to teleport different states and confirm the Bloch vector tracks them.",
                  "Run 'dynamic' mode on ibm:fake_fez (needs feed-forward) vs 'deferred' mode anywhere.",
                  "Compare fidelity on local vs a noisy backend — the Bell pair quality sets the ceiling."],
        real_world_use="Teleportation is the routing primitive of the quantum internet: it moves qubits between "
                       "processors and through quantum repeaters, and underlies measurement-based quantum computing.",
        going_deeper="Entanglement swapping teleports entanglement itself — the building block of quantum repeaters.",
        references=[{"title": "Quantum teleportation", "url": "https://en.wikipedia.org/wiki/Quantum_teleportation"}],
        prerequisites=["bell_states"],
    )
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
    tutor = Tutor(
        concept="Superdense coding is teleportation's mirror image: using one shared Bell pair, Alice sends TWO "
                "classical bits to Bob by transmitting just ONE qubit.",
        how_it_works="Alice and Bob pre-share a Bell pair. To send 2 bits, Alice applies one of {I, X, Z, ZX} to her "
                     "qubit — rotating the pair into one of the four orthogonal Bell states — and ships it to Bob. Bob "
                     "undoes the entanglement (CNOT then H) and reads both bits perfectly.",
        intuition="The four Bell states are perfectly distinguishable, and Alice can steer between them by touching "
                  "only her half. The 'second bit' of capacity was pre-positioned in the entanglement.",
        misconception="This doesn't beat Shannon in a vacuum: you spent entanglement (established earlier) to double "
                      "the later channel. It's a resource trade, not free bandwidth.",
        what_to_look_for="All four messages should decode with ~100% success on an ideal backend. Noise shows up as "
                         "cross-talk between the four outcomes.",
        try_this=["Run on ibm:fake_fez and watch the average success drop below 1 — the CNOT+H decode is the weak link.",
                  "Add --mitigate-readout and compare the per-message success rates."],
        real_world_use="Superdense coding is a textbook demonstration that entanglement is a communication resource; "
                       "variants appear in quantum network capacity results and dense-coding protocols.",
        going_deeper="Teleportation sends a qubit with 2 classical bits + 1 Bell pair; superdense sends 2 bits with 1 "
                     "qubit + 1 Bell pair. They are duals.",
        references=[{"title": "Superdense coding", "url": "https://en.wikipedia.org/wiki/Superdense_coding"}],
        prerequisites=["bell_states"],
    )
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
    tutor = Tutor(
        concept="Quantum key distribution lets two people grow a shared secret key whose secrecy is guaranteed by "
                "physics, not by assuming an eavesdropper lacks computing power. Spying leaves fingerprints.",
        how_it_works="BB84: Alice sends qubits in randomly chosen Z or X bases; Bob measures in random bases. They "
                     "publicly compare bases and keep only the matching rounds (sifting). They sacrifice a sample to "
                     "estimate the error rate (QBER), run error correction, then privacy amplification (Toeplitz "
                     "hashing) to squeeze out a shorter, secret key. BBM92 does the same with shared Bell pairs.",
        intuition="Measuring an unknown qubit in the wrong basis disturbs it (no-cloning + measurement collapse). An "
                  "eavesdropper who intercepts and resends must guess the basis, and guesses wrong half the time, "
                  "injecting ~25% errors Alice and Bob can detect.",
        misconception="QKD distributes a KEY, it doesn't encrypt messages, and it doesn't make eavesdropping impossible "
                      "— it makes it DETECTABLE. If the error rate is too high, they abort and no key is used.",
        what_to_look_for="With eve=0 the QBER is ~0 and Alice/Bob keys match. Turn Eve up and the QBER climbs toward "
                         "25%; above the ~11% threshold the protocol aborts. The report shows the full key budget.",
        try_this=["Set eve=1.0 and watch QBER ≈ 25% → ABORT. Then eve=0.3 and see a partial but detectable leak.",
                  "Switch protocol=bbm92 (entanglement-based) and compare.",
                  "Run on ibm:fake_fez with eve=0: real device noise alone can push QBER near the abort threshold."],
        real_world_use="QKD is deployed today over fiber and satellite (e.g. China's Micius satellite, metro QKD "
                       "networks) to protect against 'harvest-now-decrypt-later' attacks on long-lived secrets.",
        going_deeper="The E91 protocol replaces the disturbance test with a CHSH violation — security from Bell's theorem itself.",
        references=[{"title": "BB84", "url": "https://en.wikipedia.org/wiki/BB84"},
                    {"title": "Quantum key distribution", "url": "https://en.wikipedia.org/wiki/Quantum_key_distribution"}],
        prerequisites=["bell_states", "qrng"],
    )
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
class E91(Experiment):
    id = "e91_qkd"
    title = "E91 entanglement-based QKD with a Bell-test security certificate"
    category = "Protocols"
    summary = ("Ekert's protocol: Alice and Bob build a shared key from entangled pairs, and a CHSH Bell test on the "
               "leftover rounds CERTIFIES no one is listening — security from physics, not assumptions.")
    description = (
        "Bell pairs are shared; Alice measures at angles {0°,45°,90°} and Bob at {45°,90°,135°}, chosen at random. "
        "Rounds where they picked the same angle (45° or 90°) are perfectly correlated and become the key. The "
        "remaining angle combinations feed a CHSH estimate: a genuine entangled channel gives S ≈ 2√2, but an "
        "intercept-resend eavesdropper breaks the entanglement and drags S toward 2 while injecting key errors. If "
        "S ≤ 2, the parties abort.")
    hardware_notes = "2 qubits per pair per circuit; many rounds. Shares the CHSH and BB84 machinery."
    params = [Param("rounds", "int", 60, "Measurement rounds (circuits)", 10, 400),
              Param("pairs", "int", 4, "Entangled pairs per round", 1, 8),
              Param("eve", "float", 0.0, "Fraction of pairs an eavesdropper intercepts", 0, 1),
              Param("seed", "int", 91, "Seed for angle choices (-1 = random)", -1, 2**31)]
    default_shots = 1
    tutor = Tutor(
        concept="E91 is QKD whose security comes directly from Bell's theorem: the same CHSH violation that rules out "
                "classical physics also rules out an undetected eavesdropper. Spying destroys entanglement, and the "
                "Bell test sees it.",
        how_it_works="Shared entangled pairs are each measured by Alice and Bob at random angles. Same-angle rounds are "
                     "perfectly correlated → the secret key. Different-angle rounds estimate CHSH's S. High S certifies "
                     "strong entanglement (no eavesdropper); low S plus key errors flags an intruder.",
        intuition="An eavesdropper who measures a qubit collapses it, breaking the entanglement the Bell test depends "
                  "on. So the very correlations that make the key also serve as a tamper-evident seal.",
        misconception="E91 distributes a KEY and DETECTS eavesdropping; it doesn't encrypt or make interception "
                      "impossible. And it needs genuine entanglement — a loophole-free Bell violation is what makes it "
                      "'device-independent' in the strong form.",
        what_to_look_for="With eve=0, S ≈ 2.8 and the sifted keys agree. Turn Eve up and watch S fall toward (or below) "
                         "2 while the key error rate climbs — the abort condition.",
        try_this=["Run eve=0 (S≈2.8, keys match) then eve=1.0 (S≤2, high QBER → abort).",
                  "Compare to BB84: E91 replaces the disturbance test with a Bell inequality.",
                  "Run on ibm:fake_fez: device noise alone lowers S, the real-world challenge for QKD."],
        real_world_use="Entanglement-based QKD has been demonstrated over fiber and via the Micius satellite; "
                       "device-independent QKD (security from Bell violations) is an active frontier.",
        going_deeper="The CHSH experiment is the Bell test at E91's heart; BB84 is the prepare-and-measure cousin.",
        references=[{"title": "Ekert 1991 (E91)", "url": "https://en.wikipedia.org/wiki/Quantum_key_distribution#E91_protocol"},
                    {"title": "Micius satellite QKD", "url": "https://en.wikipedia.org/wiki/Quantum_Experiments_at_Space_Scale"}],
        prerequisites=["chsh", "bb84"],
    )

    ALICE = [0.0, math.pi / 4, math.pi / 2]
    BOB = [math.pi / 4, math.pi / 2, 3 * math.pi / 4]

    def build(self, p):
        rng = rng_from(p["seed"])
        n = p["pairs"]
        circuits, rounds = [], []
        for r in range(p["rounds"]):
            qc = Circuit(2 * n, name=f"e91_r{r}")
            a = qc.add_creg("alice", n)
            b = qc.add_creg("bob", n)
            ai = rng.integers(0, 3, n).tolist()
            bi = rng.integers(0, 3, n).tolist()
            ev = (rng.random(n) < p["eve"]).tolist()
            eb = rng.integers(0, 2, n).tolist()
            ereg = qc.add_creg("eve", n) if any(ev) else None
            for i in range(n):
                qc.h(2 * i).cx(2 * i, 2 * i + 1)        # |Φ+⟩ pair
            for i in range(n):
                if ev[i]:                                 # intercept-resend in Z or X
                    if eb[i]:
                        qc.h(2 * i + 1)
                    qc.measure(2 * i + 1, ereg[i])
                    if eb[i]:
                        qc.h(2 * i + 1)
            for i in range(n):
                qc.ry(-self.ALICE[ai[i]], 2 * i)       # E(a,b) = cos(a−b) for |Φ+⟩
                qc.ry(-self.BOB[bi[i]], 2 * i + 1)
                qc.measure(2 * i, a[i])
                qc.measure(2 * i + 1, b[i])
            circuits.append(qc)
            rounds.append({"a": ai, "b": bi})
        return Plan(circuits, {"rounds": rounds}, memory=True, shots=1)

    def analyze(self, p, ctx, results):
        n = p["pairs"]
        key_a, key_b = [], []
        # CHSH accumulators: E(ai,bj) for ai in {0,2} (0°,90°), bj in {0,2} (45°,135°)
        chsh_pairs = {(0, 0): [0, 0], (0, 2): [0, 0], (2, 0): [0, 0], (2, 2): [0, 0]}
        for info, res in zip(ctx["rounds"], results):
            am = res.register_memory("alice")[0] if res.memory else next(iter(res.register("alice")))
            bm = res.register_memory("bob")[0] if res.memory else next(iter(res.register("bob")))
            for i in range(n):
                ai, bi = info["a"][i], info["b"][i]
                abit = int(am[n - 1 - i]); bbit = int(bm[n - 1 - i])
                if self.ALICE[ai] == self.BOB[bi]:               # same angle → key (correlated for |Φ+⟩)
                    key_a.append(abit); key_b.append(bbit)
                elif (ai, bi) in chsh_pairs:
                    acc = chsh_pairs[(ai, bi)]
                    acc[0] += 1 if abit == bbit else -1
                    acc[1] += 1
        def E(key):
            s, c = chsh_pairs[key]
            return s / c if c else 0.0
        S = E((0, 0)) - E((0, 2)) + E((2, 0)) + E((2, 2))   # maximal for the E91 angle set
        sifted = len(key_a)
        qber = sum(x != y for x, y in zip(key_a, key_b)) / sifted if sifted else 0.0
        secure = abs(S) > 2.0 and qber < 0.15
        summary = [f"Sifted key length {sifted}, key error rate {qber:.2%}.",
                   f"CHSH security test: S = {S:.3f} (|S|>2 certifies no eavesdropper; ideal 2√2 ≈ 2.83).",
                   ("Channel secure — entanglement intact, key accepted." if secure
                    else "ABORT: Bell test failed and/or errors too high — an eavesdropper is likely present.")]
        return Report(
            "E91 entanglement-based QKD", summary,
            {"sifted_key_bits": sifted, "qber": qber, "chsh_S": S, "secure": secure, "eve_fraction": p["eve"]},
            charts=[Chart("CHSH correlators", ["E(0,45)", "E(0,135)", "E(90,45)", "E(90,135)"],
                          {"measured": [E((0, 0)), E((0, 2)), E((2, 0)), E((2, 2))]})],
            verdict=("pass" if secure and p["eve"] == 0 else ("warn" if p["eve"] > 0 else "warn")),
            notes=["Same-angle rounds form the key; mismatched-angle rounds certify security via the Bell test."])


@register
class QRNG(Experiment):
    id = "qrng"
    tutor = Tutor(
        concept="A quantum random number generator makes bits that are random by the laws of physics, not by a "
                "hard-to-predict formula. The unpredictability is fundamental, not just practical.",
        how_it_works="Put a qubit in |+⟩ with a Hadamard, then measure in the Z basis. Quantum mechanics says the "
                     "outcome is a genuine 50/50 coin flip with no hidden cause. Do this on many qubits in parallel for a "
                     "stream of bits, then run NIST-style tests (monobit, runs, χ²) and optionally an extractor.",
        intuition="A classical PRNG is deterministic — if you know the seed, you know every 'random' number. A measured "
                  "|+⟩ has no seed and no formula; the randomness comes from measurement collapse itself.",
        misconception="Real devices are biased (a qubit might read 1 slightly more than 0), so raw quantum bits aren't "
                      "uniform. That's why we apply a randomness EXTRACTOR (von Neumann or Toeplitz) to distill fewer, "
                      "near-perfect bits from the device's measured min-entropy.",
        what_to_look_for="Per-qubit P(1) near 0.5 (the table shows each qubit's bias), statistical-test p-values above "
                         "0.01, and the min-entropy bound that sets how many extracted bits are safe to keep.",
        try_this=["Run on ibm:fake_fez and watch the per-qubit bias table — hardware qubits are visibly skewed.",
                  "Switch extractor between none / von_neumann / toeplitz and compare output length vs quality.",
                  "Increase shots for a longer bitstream and tighter statistics."],
        real_world_use="QRNGs are a shipping product (ID Quantique, cloud 'quantum random' APIs) used for cryptographic "
                       "keys, lotteries and simulations. Device-independent QRNG certified by a CHSH violation is the gold standard.",
        going_deeper="Combine with a CHSH test for randomness you can certify even if you don't trust the hardware vendor.",
        references=[{"title": "Hardware RNG / quantum", "url": "https://en.wikipedia.org/wiki/Hardware_random_number_generator"},
                    {"title": "NIST SP 800-22 (randomness tests)", "url": "https://csrc.nist.gov/pubs/sp/800/22/r1/upd1/final"}],
        prerequisites=[],
    )
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
