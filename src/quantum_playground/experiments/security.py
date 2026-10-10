"""Defensive, educational quantum-security experiments.

Both experiments are STRICTLY TOY-SCALE and SYNTHETIC. They illustrate how quantum
algorithms scale against cryptography so a learner understands why key lengths and
post-quantum migration matter. They cannot attack any real cipher, hash, password or
system: the "cipher" is a fixed public toy permutation over a few bits, and the only
secret is one chosen inside the experiment.
"""
from __future__ import annotations

import math

import numpy as np

from ..core.circuit import Circuit
from ..core.statevector import exact_distribution
from ..core.synthesis import apply_permutation, extend_permutation
from .base import Chart, Experiment, Param, Plan, Report, Table, Tutor, counts_chart, register

# Public, fixed demo S-box (a shuffled permutation) and round count. These are published,
# not secret — Grover treats the whole cipher as an unstructured black box regardless.
_SBOX_SEED = 0x513E


def _sbox(width: int) -> tuple[int, ...]:
    rng = np.random.default_rng(_SBOX_SEED + width)
    perm = list(range(1 << width))
    rng.shuffle(perm)
    return tuple(int(x) for x in perm)


def toy_encrypt(plaintext: int, key: int, width: int, rounds: int = 3) -> int:
    """A tiny substitution-permutation block cipher: x = Sbox(x ⊕ k), repeated, then ⊕ k."""
    sbox = _sbox(width)
    x = plaintext & ((1 << width) - 1)
    k = key & ((1 << width) - 1)
    for _ in range(rounds):
        x = sbox[x ^ k]
    return x ^ k


def toy_decrypt(ciphertext: int, key: int, width: int, rounds: int = 3) -> int:
    sbox = _sbox(width)
    inv = [0] * (1 << width)
    for i, v in enumerate(sbox):
        inv[v] = i
    x = ciphertext & ((1 << width) - 1)
    k = key & ((1 << width) - 1)
    x ^= k
    for _ in range(rounds):
        x = inv[x] ^ k
    return x


def _keyed_encrypt_circuit(width: int, rounds: int) -> Circuit:
    """Circuit on (key, data) computing data ← E_key(data) coherently over all keys."""
    qc = Circuit(name="toy_cipher")
    key = qc.add_qreg("k", width)
    data = qc.add_qreg("d", width)
    sbox = extend_permutation(_sbox(width), width)
    for _ in range(rounds):
        for i in range(width):
            qc.cx(key[i], data[i])           # data ^= key
        apply_permutation(qc, list(data), sbox)   # data = Sbox(data)
    for i in range(width):
        qc.cx(key[i], data[i])               # final key addition
    return qc


@register
class GroverKeySearch(Experiment):
    id = "grover_key_search"
    title = "Grover key search: a quantum known-plaintext attack (toy cipher)"
    category = "Security"
    summary = ("Encrypt a message with a secret key on a tiny toy cipher, then let Grover recover the key from "
               "known plaintext/ciphertext pairs — and see the quadratic speedup that halves symmetric-key strength.")
    description = (
        "A SYNTHETIC demonstration of why quantum computers worry symmetric cryptography. A small public toy cipher "
        "E_key encrypts chosen plaintext blocks under a secret key. Grover's algorithm searches the key space: a "
        "reversible oracle encrypts the known plaintext(s) under every candidate key in superposition, marks the key(s) "
        "that reproduce the known ciphertext(s), and amplitude amplification concentrates the measurement on the real "
        "key in ≈(π/4)√N steps instead of ≈N/2 classical trials. The report then extrapolates this √ speedup to real "
        "key lengths (why AES-128 has ~64-bit quantum security and AES-256 restores safety). It cannot attack any real "
        "cipher — the only secret is the one this experiment chose.")
    hardware_notes = ("key+block qubits (2×width) + one flag per pair. Deep for width>4 due to the S-box permutation; "
                      "start on the simulator, then try width=3 on ibm:fake_fez.")
    params = [Param("width", "int", 4, "Key and block size in bits", 2, 6),
              Param("pairs", "int", 2, "Known plaintext/ciphertext pairs the attacker has", 1, 2),
              Param("rounds", "int", 3, "Toy-cipher rounds", 1, 4),
              Param("secret_key", "int", -1, "Secret key to recover (-1 = pick one for you)", -1, 63),
              Param("iterations", "int", -1, "Grover iterations (-1 = optimal for the solution count)", -1, 12)]
    tutor = Tutor(
        concept="A hands-on look at the real quantum threat to symmetric keys and passwords: Grover turns an N-key "
                "brute force into a √N search. This toy runs the whole attack so you can watch it work, then scales the "
                "lesson up to real key lengths.",
        how_it_works="A small public cipher encrypts known plaintext blocks under a secret key. The Grover oracle "
                     "re-encrypts those blocks under EVERY candidate key at once (the key register is in superposition, "
                     "entangled with the data), flags the keys that match the known ciphertexts, and amplitude "
                     "amplification boosts them. Measuring returns the secret key, which then decrypts the message.",
        intuition="Grover doesn't exploit any weakness in the cipher — it treats encryption as a black box and searches "
                  "keys. That's why the speedup is a universal quadratic (√N), applying to AES, passwords, anything: it "
                  "halves the effective bit-strength of a symmetric key.",
        misconception="This is a TOY and cannot break real encryption. Also, the quadratic speedup is NOT an "
                      "exponential break: a real AES-256 key keeps ~128 bits of quantum security, which is still "
                      "unbreakable. The fix is simply longer keys — the opposite of panic. Real fault-tolerant Grover on "
                      "AES also costs far more than the naive 2^(k/2) due to the huge reversible-cipher oracle and depth limits.",
        what_to_look_for="The recovered key should match the secret and decrypt the ciphertext back to the plaintext. "
                         "The key-length table is the real payload: classical 2^(k−1) vs Grover 2^(k/2) for 64–256-bit keys.",
        try_this=["Use pairs=2 for a unique key; pairs=1 often leaves several consistent keys (an underdetermined attack).",
                  "Set iterations beyond the optimum and watch success drop — Grover overshoots.",
                  "Read the cost table: this is why NIST pairs AES-128 with 'category 1' and recommends AES-256."],
        real_world_use="Explains the 'double your symmetric key length' guidance, NIST post-quantum security categories, "
                       "and why passwords/keys below ~128 bits of entropy are a quantum concern (and why ≥256-bit keys are not).",
        going_deeper="The Q-Day estimator shows the public-key side (Shor vs RSA/ECC) and the harvest-now-decrypt-later timeline.",
        references=[{"title": "Grover's algorithm", "url": "https://en.wikipedia.org/wiki/Grover%27s_algorithm"},
                    {"title": "NIST PQC security categories", "url": "https://csrc.nist.gov/projects/post-quantum-cryptography"},
                    {"title": "Grassl et al., Applying Grover to AES", "url": "https://arxiv.org/abs/1512.04965"}],
        prerequisites=["grover"],
    )

    def build(self, p):
        width, rounds = p["width"], p["rounds"]
        n = 1 << width
        key = p["secret_key"] if p["secret_key"] >= 0 else (0b1011 % n) or 1
        key %= n
        plaintexts = list(range(p["pairs"]))
        ciphertexts = [toy_encrypt(pt, key, width, rounds) for pt in plaintexts]
        solutions = [k for k in range(n)
                     if all(toy_encrypt(pt, k, width, rounds) == ct for pt, ct in zip(plaintexts, ciphertexts))]
        iters = p["iterations"] if p["iterations"] >= 0 else _opt_iters(n, len(solutions))

        qc = Circuit(name=f"grover_key_search_w{width}")
        kreg = qc.add_qreg("k", width)
        data = qc.add_qreg("d", width)
        flags = qc.add_qreg("f", len(plaintexts))
        creg = qc.add_creg("key", width)
        enc = _keyed_encrypt_circuit(width, rounds)

        def mark(uncompute: bool):
            for i, (pt, ct) in enumerate(zip(plaintexts, ciphertexts)):
                for b in range(width):                     # load plaintext
                    if (pt >> b) & 1:
                        qc.x(data[b])
                qc.compose(enc, qubits=[*kreg, *data])
                for b in range(width):                     # compare to ciphertext → flag
                    if not ((ct >> b) & 1):
                        qc.x(data[b])
                qc.mcx(list(data), flags[i])
                for b in range(width):
                    if not ((ct >> b) & 1):
                        qc.x(data[b])
                qc.compose(enc.inverse(), qubits=[*kreg, *data])
                for b in range(width):
                    if (pt >> b) & 1:
                        qc.x(data[b])

        qc.h(list(kreg))
        for _ in range(iters):
            mark(False)
            if len(flags) == 1:
                qc.z(flags[0])
            else:
                qc.mcz(list(flags)[:-1], flags[len(flags) - 1])
            mark(True)                                      # uncompute flags
            qc.h(list(kreg)); qc.phase_flip_on(list(kreg), 0); qc.h(list(kreg))
        qc.measure(list(kreg), creg)
        return Plan([qc], {"width": width, "rounds": rounds, "secret": key, "plaintexts": plaintexts,
                           "ciphertexts": ciphertexts, "solutions": solutions, "iterations": iters})

    def analyze(self, p, ctx, results):
        width = ctx["width"]
        res = results[0]
        n = 1 << width
        sols = ctx["solutions"]
        counts = res.register("key")
        best = max(counts.items(), key=lambda kv: kv[1])[0]
        idx = int(best, 2)
        p_sol = sum(counts.get(format(s, f"0{width}b"), 0) for s in sols) / res.shots
        ideal = _grover_prob(n, len(sols), ctx["iterations"])
        secret = ctx["secret"]
        recovered_ok = idx in sols
        # Decrypt the message with the recovered key to prove the attack.
        msg_blocks = ctx["ciphertexts"]
        decrypted = [toy_decrypt(c, idx, width, ctx["rounds"]) for c in msg_blocks]
        decrypt_ok = decrypted == ctx["plaintexts"]
        rows = [[format(k, f"0{width}b"), k, round(counts.get(format(k, f"0{width}b"), 0) / res.shots, 4), k in sols]
                for k in sorted(range(n), key=lambda k: -counts.get(format(k, f"0{width}b"), 0))[:12]]
        cost = Table("Quantum cost of brute-forcing real symmetric keys",
                     ["key bits", "classical ~2^(k-1)", "Grover ~2^(k/2)", "note"],
                     [[k, f"2^{k-1}", f"2^{k // 2}", note] for k, note in
                      [(56, "DES — already broken classically"), (64, "legacy"), (80, "legacy"),
                       (112, "3DES"), (128, "AES-128 → ~64-bit quantum security"),
                       (192, "AES-192"), (256, "AES-256 → ~128-bit quantum, safe")]])
        return Report(
            "Grover key search (toy cipher)",
            [f"Secret key {format(secret, f'0{width}b')} ({secret}); attacker knows {len(ctx['plaintexts'])} "
             f"plaintext/ciphertext pair(s).",
             f"Searched {n} keys with {ctx['iterations']} Grover iteration(s) (classical brute force ≈ {n // 2}).",
             f"Recovered key {best} ({idx}); matches a consistent key: {recovered_ok}; decrypts the message correctly: {decrypt_ok}.",
             f"P(a consistent key) = {p_sol:.4f} (ideal {ideal:.4f}, random {len(sols) / n:.4f}).",
             "The √N speedup below is the real lesson — it HALVES the bit-strength of any symmetric key or password."],
            {"width": width, "secret_key": secret, "recovered_key": idx, "recovered_ok": recovered_ok,
             "decrypt_ok": decrypt_ok, "consistent_keys": len(sols), "p_success": p_sol, "ideal": ideal},
            [Table("Candidate keys", ["bits", "key", "freq", "consistent"], rows), cost],
            [counts_chart("Key register", counts,
                          ideal={format(s, f"0{width}b"): ideal / max(1, len(sols)) for s in sols})],
            "pass" if recovered_ok else "warn",
            notes=["Toy, synthetic, defensive: a public toy cipher and a self-chosen secret. It cannot attack any real "
                   "cipher, hash or password — it demonstrates query-count SCALING only."])


def _opt_iters(n, m):
    if m <= 0 or m >= n:
        return 0
    return max(1, round(math.pi / (4 * math.asin(math.sqrt(m / n))) - 0.5))


def _grover_prob(n, m, k):
    if m <= 0:
        return 0.0
    theta = math.asin(math.sqrt(min(1.0, m / n)))
    return math.sin((2 * k + 1) * theta) ** 2


# =============================================================================
@register
class QDayEstimator(Experiment):
    id = "qday_estimator"
    title = "Q-Day resource estimator: is my encryption quantum-safe?"
    category = "Security"
    summary = ("Factor 15 with Shor as a live proof the quantum attack is real, then estimate what breaking RSA/ECC "
               "would actually take — and whether 'harvest now, decrypt later' threatens your data.")
    description = (
        "The public-key counterpart to Grover key search. It runs a genuine Shor order-finding circuit to factor 15, "
        "then presents published resource estimates for breaking real RSA/ECC: logical and physical qubit counts and "
        "runtimes (Gidney–Ekerå 2019: ~20M physical qubits for RSA-2048; 2025 improvements: <1M). A 'harvest now, "
        "decrypt later' calculator flags whether data with a given secrecy lifetime is at risk before an estimated "
        "Q-Day, and a symmetric-key table shows Grover's gentler (quadratic) threat. The estimates are order-of-"
        "magnitude teaching figures from the cited literature, not predictions.")
    hardware_notes = "Reuses the Shor N=15 circuit (12 qubits). The estimates themselves use no qubits."
    params = [Param("rsa_bits", "int", 2048, "RSA modulus size to estimate (bits)", 512, 8192),
              Param("secret_lifetime_years", "int", 15, "How long your data must stay secret", 0, 100),
              Param("q_day_year", "int", 2035, "Assumed year a cryptographically-relevant quantum computer arrives",
                    2030, 2060),
              Param("today_year", "int", 2026, "Current year (for the harvest-now-decrypt-later clock)", 2024, 2060)]
    tutor = Tutor(
        concept="Shor's algorithm will eventually break RSA and elliptic-curve cryptography — the backbone of HTTPS, "
                "signatures and key exchange. This experiment proves the attack works (on tiny N=15) and estimates the "
                "hardware a real break needs, so you can reason about your own data's risk.",
        how_it_works="It factors 15 with a real Shor circuit (live quantum proof), then applies published scaling laws: "
                     "Shor needs ~2n–3n logical qubits for an n-bit modulus, inflated by surface-code overhead to "
                     "millions of physical qubits. The harvest-now-decrypt-later clock compares today + your data's "
                     "secrecy lifetime against an assumed Q-Day.",
        intuition="Public-key crypto faces an EXPONENTIAL break (Shor), so it must be replaced, not just lengthened. "
                  "Symmetric crypto faces only a QUADRATIC one (Grover), so longer keys suffice. Encrypted data with a "
                  "long shelf life is already at risk today, because adversaries can store it and decrypt later.",
        misconception="No quantum computer can factor cryptographic-size numbers today — honest demos stop at 15, 21, "
                      "35. The threat is FUTURE and the estimates are uncertain; but 'harvest now, decrypt later' makes "
                      "the planning problem PRESENT for long-lived secrets. The estimates here are rough literature "
                      "figures, not forecasts.",
        what_to_look_for="Shor factors 15 = 3×5 (the quantum part works), the RSA estimate in physical qubits and time, "
                         "and a red/green harvest-now-decrypt-later verdict for your data's lifetime.",
        try_this=["Set secret_lifetime_years long (e.g. 30) and watch the harvest-now-decrypt-later verdict turn to risk.",
                  "Compare rsa_bits = 1024 vs 2048 vs 4096 in the estimate.",
                  "Read the symmetric table: Grover is far gentler than Shor — key length, not replacement, is the fix."],
        real_world_use="This is the core of every organisation's post-quantum readiness assessment: inventory crypto, "
                       "estimate exposure, and migrate long-lived secrets to NIST PQC (ML-KEM, ML-DSA) first.",
        going_deeper="See the Shor tutor for the algorithm and the security curriculum lesson for the migration picture.",
        references=[{"title": "Gidney & Ekerå (2019): 20M qubits, 8h for RSA-2048", "url": "https://arxiv.org/abs/1905.09749"},
                    {"title": "Gidney (2025): <1M qubits for RSA-2048", "url": "https://arxiv.org/abs/2505.15917"},
                    {"title": "NIST Post-Quantum Cryptography", "url": "https://csrc.nist.gov/projects/post-quantum-cryptography"}],
        prerequisites=["shor"],
    )

    def _shor(self):
        from .fourier import Shor
        exp = Shor()
        params = exp.resolve({"N": 15, "a": 7, "t": 8})
        return exp, params

    def build(self, p):
        exp, sp = self._shor()
        plan = exp.build(sp)
        plan.context["qday"] = dict(p)
        plan.context["shor_ctx"] = {k: v for k, v in plan.context.items() if k not in ("qday", "shor_ctx")}
        return plan

    def analyze(self, p, ctx, results):
        exp, sp = self._shor()
        base = exp.analyze(sp, ctx.get("shor_ctx", ctx), results)
        q = ctx["qday"]
        n = q["rsa_bits"]
        # Rough, literature-anchored estimates (order of magnitude only).
        logical = 3 * n
        phys_2019 = 20e6 * (n / 2048) ** 2          # Gidney–Ekerå scaling anchor
        phys_2025 = 1e6 * (n / 2048) ** 2
        hours = 8 * (n / 2048) ** 3
        at_risk = (q["today_year"] + q["secret_lifetime_years"]) >= q["q_day_year"]
        margin = q["q_day_year"] - (q["today_year"] + q["secret_lifetime_years"])
        est = Table(f"Breaking RSA-{n} with Shor (order-of-magnitude, from the literature)",
                    ["metric", "estimate"],
                    [["logical qubits (~3n)", f"{logical:,}"],
                     ["physical qubits (2019 surface-code anchor)", f"~{phys_2019/1e6:.1f} million"],
                     ["physical qubits (2025 improvements)", f"~{phys_2025/1e6:.2f} million"],
                     ["runtime", f"~{hours:.1f} hours" if hours >= 1 else f"~{hours*60:.0f} minutes"],
                     ["largest honestly factored on hardware", "15, 21, 35 (no cryptographic numbers)"]])
        grover = Table("Symmetric keys face only Grover's quadratic threat",
                       ["key bits", "quantum security", "status"],
                       [[128, "~64 bits", "AES-128: weakened, still very hard"],
                        [256, "~128 bits", "AES-256: effectively quantum-safe"]])
        hndl = ["", "Harvest-now-decrypt-later check:",
                f"  Data encrypted today must stay secret until {q['today_year'] + q['secret_lifetime_years']}; "
                f"assumed Q-Day {q['q_day_year']}.",
                f"  {'⚠ AT RISK' if at_risk else '✓ likely safe'} — "
                + (f"your secrecy window overshoots Q-Day by {-margin} years; migrate long-lived secrets to post-quantum "
                   "crypto now." if at_risk else f"{margin}-year margin, but Q-Day timing is uncertain — stay crypto-agile.")]
        base.title = "Q-Day resource estimator"
        base.summary = [f"Live quantum proof: Shor factored 15 → {base.metrics.get('factors', [3, 5])} "
                        f"(success {base.metrics.get('success_fraction', 0):.0%} of shots).",
                        f"Public-key crypto (RSA-{n}, ECC) faces an EXPONENTIAL break and must be replaced.",
                        *hndl]
        base.tables = [est, grover] + base.tables
        base.metrics.update({"rsa_bits": n, "logical_qubits": logical, "phys_qubits_2025_millions": round(phys_2025/1e6, 2),
                             "harvest_now_decrypt_later_risk": at_risk})
        base.verdict = "warn" if at_risk else "pass"
        base.notes = (base.notes or []) + ["Estimates are rough, order-of-magnitude teaching figures from the cited "
                                           "papers — not predictions. Q-Day timing is genuinely uncertain."]
        return base
