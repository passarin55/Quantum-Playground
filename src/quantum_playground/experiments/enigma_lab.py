"""Enigma experiments: Grover key search on the reversible oracle, and a QRNG-driven key sheet."""
from __future__ import annotations

import math

from ..core.circuit import Circuit
from ..enigma import (BitSource, EnigmaConfig, build_grover_circuit, encrypt, generate_keysheet, groups,
                      historical_problem, letters, mini_encrypt, mini_problem, optimal_iterations,
                      success_probability)
from ..enigma.machine import ABC
from .base import Chart, Experiment, Param, Plan, Report, Table, Tutor, counts_chart, register
from .library import bits_to_hex


@register
class EnigmaGrover(Experiment):
    id = "enigma_grover"
    tutor = Tutor(
        concept="This is Grover's algorithm aimed at a real cipher: given a plaintext/ciphertext pair, it searches for "
                "the secret Enigma rotor setting that links them — a quantum spin on the codebreaking that won WWII.",
        how_it_works="The unknown is one rotor's start window among 2^b candidates. A quantum oracle runs the ACTUAL "
                     "Enigma wiring as a reversible circuit on a 5-qubit letter register, for all candidate keys in "
                     "superposition, and phase-marks the key that maps the crib plaintext to the known ciphertext. "
                     "Grover amplification then concentrates the measurement on that key.",
        intuition="The oracle doesn't store the answer — it re-encrypts under each candidate key and checks the result, "
                  "exactly as a codebreaker would, but on all keys at once. Grover boosts whichever key passes the check.",
        misconception="This is NOT a practical Enigma cracker and claims no speedup over classical codebreaking. A "
                      "classical scan of all 17,576 rotor windows takes milliseconds; the quantum search is a small, "
                      "educational restricted search. The 26-letter oracle is far beyond today's hardware — only the "
                      "Mini-Enigma runs meaningfully on a real QPU. It attacks a synthetic toy, not any live system.",
        what_to_look_for="The most frequent measured key should decode to the real setting, and the report decrypts the "
                         "whole message with it. P(crib-consistent key) vs random tells you how well amplification worked.",
        try_this=["Run model=mini on ibm:fake_fez — small enough to see real amplification on a device model.",
                  "Increase crib_length to 2 to disambiguate when several 1-letter keys match.",
                  "Use 'Compare oracle synthesis' (web) or inspect the circuit to see staged vs factored vs compiled cost."],
        real_world_use="Demonstrates concretely why symmetric cryptography worried about Grover (quadratic key-search "
                       "speedup) and why key lengths matter — the same logic behind the password-search demo.",
        going_deeper="The password/key brute-force demo generalises this to arbitrary synthetic keys; Grover-SAT shows "
                     "the oracle-building pattern.",
        references=[{"title": "Enigma machine", "url": "https://en.wikipedia.org/wiki/Enigma_machine"},
                    {"title": "Grover's algorithm", "url": "https://en.wikipedia.org/wiki/Grover%27s_algorithm"}],
        prerequisites=["grover", "grover_sat"],
    )
    title = "Enigma: Grover search for the rotor start window"
    category = "Enigma"
    summary = "Encrypt a message, then let Grover's algorithm find which of 2^b candidate start windows was used."
    description = ("The secret setting differs from the publicly-known settings only in one rotor's start "
                   "window (right rotor by default). The oracle runs the *real* Enigma permutation coherently "
                   "on a 5-qubit letter register for every candidate (see enigma/quantum.py), compares with the "
                   "known crib, and phase-marks matches. The measured key index is turned back into a machine "
                   "setting and used to decrypt the whole message. This is an educational restricted search: a "
                   "classical scan of all 17 576 windows takes milliseconds and is shown for comparison.")
    hardware_notes = ("Mini model: 4 qubits, tens of gates — realistic on IBM Heron. Historical model: 7–10 "
                      "qubits and hundreds of multi-controlled gates — expect near-uniform output on today's "
                      "hardware; use the preflight to see native two-qubit counts first.")
    params = [Param("model", "choice", "historical", "Machine", choices=["historical", "mini"]),
              Param("message", "str", "WETTERBERICHTXNORDSEE", "Plaintext (A–Z; ABCD for mini)"),
              Param("crib_length", "int", 1, "Known-plaintext letters used by the oracle", 1, 3),
              Param("rotors", "str", "I II III", "Rotor order (historical)"),
              Param("rings", "str", "1 1 1", "Ring settings"),
              Param("reflector", "str", "B", "Reflector"),
              Param("plugboard", "str", "AV BS CG", "Plugboard pairs"),
              Param("secret_window", "str", "AAC", "Secret start window (historical) or 0-3 (mini)"),
              Param("key_bits", "int", 2, "Unknown key qubits (historical: 1-4)", 1, 4),
              Param("first", "str", "A", "First candidate letter of the unknown rotor window"),
              Param("vary", "choice", "right", "Which rotor window is unknown", choices=["right", "middle", "left"]),
              Param("synthesis", "choice", "auto", "Oracle synthesis", choices=["auto", "compiled", "staged", "factored"]),
              Param("oracle", "choice", "phase", "Oracle style", choices=["phase", "flag"]),
              Param("iterations", "int", -1, "Grover iterations (-1 = optimal for one solution)", -1, 6)]

    def build(self, p):
        L = p["crib_length"]
        if p["model"] == "mini":
            key = int(p["secret_window"]) if p["secret_window"].isdigit() else 0
            msg = "".join(ch for ch in p["message"].upper() if ch in "ABCD") or "ABCD"
            ct = mini_encrypt(msg, key)
            prob = mini_problem(msg[:L], ct[:L])
            context = {"model": "mini", "ciphertext": ct, "secret": str(key)}
        else:
            base = EnigmaConfig.create(p["rotors"], p["rings"], p["secret_window"].upper(), p["reflector"],
                                       p["plugboard"])
            msg = letters(p["message"])
            if len(msg) < L:
                raise ValueError("message shorter than crib")
            ct = encrypt(msg, base)
            prob = historical_problem(base, msg[:L], ct[:L], key_bits=p["key_bits"], vary=p["vary"],
                                      first=p["first"])
            if base.positions not in prob.candidate_labels:
                raise ValueError(f"secret window {base.positions} is not among the candidates "
                                 f"{prob.candidate_labels}; adjust 'first'/'key_bits'")
            context = {"model": "historical", "ciphertext": ct, "secret": base.positions,
                       "candidates": [c.to_dict() for c in prob.candidates]}
        it = None if p["iterations"] < 0 else p["iterations"]
        qc = build_grover_circuit(prob, iterations=it, synthesis=p["synthesis"], oracle=p["oracle"])
        context.update({"labels": prob.candidate_labels, "crib": prob.plaintext, "crib_cipher": prob.ciphertext,
                        "classical_matches": prob.classical_matches(), "iterations": qc.metadata["iterations"],
                        "synthesis": qc.metadata["synthesis"], "key_bits": prob.key_bits})
        return Plan([qc], context)

    def analyze(self, p, ctx, results):
        res = results[0]
        b = ctx["key_bits"]
        labels = ctx["labels"]
        key_counts = res.register("key")
        best = max(key_counts.items(), key=lambda kv: kv[1])[0]
        idx = int(best, 2)
        matches = ctx["classical_matches"]
        p_match = sum(key_counts.get(format(m, f"0{b}b"), 0) for m in matches) / res.shots
        ideal = success_probability(1 << b, len(matches), ctx["iterations"])
        if ctx["model"] == "mini":
            decrypted = mini_encrypt(ctx["ciphertext"], idx)
        else:
            decrypted = encrypt(ctx["ciphertext"], EnigmaConfig.from_dict(ctx["candidates"][idx]))
        rows = [[format(k, f"0{b}b"), labels[k], round(key_counts.get(format(k, f"0{b}b"), 0) / res.shots, 4),
                 k in matches] for k in range(1 << b)]
        recovered = labels[idx] == ctx["secret"]
        return Report(
            "Enigma Grover key search",
            [f"Ciphertext: {groups(ctx['ciphertext'])}",
             f"Crib {ctx['crib']} → {ctx['crib_cipher']}; oracle synthesis '{ctx['synthesis']}', "
             f"{ctx['iterations']} Grover iteration(s)",
             f"Most frequent key {best} → window {labels[idx]} (secret {ctx['secret']})",
             f"Decryption with recovered key: {groups(decrypted)}",
             f"P(crib-consistent key) = {p_match:.4f} (ideal {ideal:.4f}, random {len(matches) / (1 << b):.4f})"],
            {"recovered": recovered, "p_match": p_match, "ideal": ideal, "candidates": 1 << b,
             "crib_consistent_keys": len(matches)},
            [Table("Candidates", ["key", "window", "freq", "crib-consistent"], rows)],
            [counts_chart("Key register", key_counts, ideal={format(m, f"0{b}b"): ideal / max(1, len(matches))
                                                               for m in matches})],
            "pass" if recovered else "warn",
            notes=["Several candidates can be crib-consistent for a 1-letter crib; increase crib_length to "
                   "disambiguate (the oracle then marks only simultaneous matches)."] if len(matches) > 1 else [])


@register
class EnigmaKeySheet(Experiment):
    id = "enigma_keysheet"
    tutor = Tutor(
        concept="A playful mash-up of history and physics: generate a WWII-style Enigma daily key sheet using true "
                "quantum randomness measured from qubits, then encrypt a message with day one's settings.",
        how_it_works="Measure |+⟩ qubits to get a stream of random bits, then use rejection sampling (to avoid bias) to "
                     "choose rotor order, ring settings, plugboard pairs and start windows for each day. If the quantum "
                     "bits run out, a classical CSPRNG fills in, and the report says how many bits came from each source.",
        intuition="Key material is only as strong as its randomness. Historically, predictable operator habits helped "
                  "break Enigma; here the keys come from a source with no pattern to exploit.",
        misconception="Quantum-random keys don't make Enigma secure — the cipher itself is broken. The lesson is about "
                      "the RANDOMNESS SOURCE, which matters for any cipher, modern ones included.",
        what_to_look_for="A valid key sheet, a correct encrypt/decrypt round-trip with day one's settings, and the "
                         "quantum-vs-fallback bit tally.",
        try_this=["Increase qubits per shot for more quantum bits and fewer fallbacks.",
                  "Run on ibm:fake_fez to source the randomness from a device model.",
                  "Generate 31 days and inspect the variety of rotor/plugboard choices."],
        real_world_use="Hardware quantum RNGs seed real cryptographic keys today; weak randomness is a recurring cause "
                       "of real-world crypto failures.",
        going_deeper="The QRNG experiment covers randomness extraction and statistical testing in depth.",
        references=[{"title": "Enigma machine", "url": "https://en.wikipedia.org/wiki/Enigma_machine"}],
        prerequisites=["qrng"],
    )
    title = "Quantum-random Enigma key sheet"
    category = "Enigma"
    summary = "Generate a daily key sheet from measured quantum random bits, then encrypt a message with day 1."
    description = ("Random bits come from |+⟩ measurements; integers are drawn by rejection sampling (no "
                   "modulo bias) to pick rotor order, rings, plugboard pairs and start windows. If the quantum "
                   "bits run out, the OS CSPRNG fills in and the report says how many bits came from each.")
    params = [Param("days", "int", 7, "Days on the sheet", 1, 31),
              Param("qubits", "int", 16, "Qubits per shot", 1, 26),
              Param("message", "str", "ANGRIFFUMNULLSECHSHUNDERT", "Message to encrypt with day 1")]
    default_shots = 256

    def build(self, p):
        n = p["qubits"]
        qc = Circuit(n, name="keysheet_qrng")
        c = qc.add_creg("c", n)
        qc.h(list(range(n)))
        qc.measure(list(range(n)), c)
        return Plan([qc], {}, memory=True)

    def analyze(self, p, ctx, results):
        res = results[0]
        mem = res.memory or [k for k, v in res.counts.items() for _ in range(v)]
        bits = [int(ch) for m in mem for ch in m]
        src = BitSource(bits, fallback=True)
        sheet = generate_keysheet(p["days"], src)
        d1 = sheet.days[0]
        cfg = EnigmaConfig.create(" ".join(d1["rotors"]), d1["rings"], d1["positions"], d1["reflector"],
                                  " ".join(d1["plugboard"]))
        msg = letters(p["message"])
        ct = encrypt(msg, cfg)
        round_trip = encrypt(ct, cfg) == msg
        rows = [[d["day"], " ".join(d["rotors"]), " ".join(f"{r:02d}" for r in d["rings"]), " ".join(d["plugboard"]),
                 d["positions"]] for d in sheet.days]
        return Report(
            "Quantum-random Enigma key sheet",
            [f"{src.used_quantum} quantum bits used, {src.used_fallback} fallback bits",
             f"Day 1: {cfg.describe()}", f"Plaintext : {groups(msg)}", f"Ciphertext: {groups(ct)}",
             f"Decrypts back correctly: {round_trip}"],
            {"quantum_bits": src.used_quantum, "fallback_bits": src.used_fallback, "round_trip": round_trip,
             "sample_hex": bits_to_hex(bits[:64])},
            [Table("Key sheet", ["Tag", "Walzenlage", "Ringstellung", "Steckerverbindungen", "Grundstellung"], rows)],
            verdict="pass" if round_trip and src.used_fallback == 0 else "warn")
