"""Shor's nine-qubit code: the first code to correct an arbitrary single-qubit error.

Unlike the repetition code (one error type), the Shor code concatenates a phase-flip code
with bit-flip codes to fix ANY single-qubit error (X, Y or Z). It encodes one logical
qubit in nine physical qubits, measures eight stabilizers with a reused ancilla
(mid-circuit measurement), applies a feed-forward correction, and reads out the logical
qubit — a complete, if small, fault-tolerance demonstration.
"""
from __future__ import annotations

from ..core.circuit import Circuit
from .base import Chart, Experiment, Param, Plan, Report, Table, Tutor, counts_chart, register

BLOCKS = [(0, 1, 2), (3, 4, 5), (6, 7, 8)]
# (name, pauli, qubits) for the eight stabilizers: six Z-type (bit-flip), two X-type (phase).
STABS = [
    ("Z0Z1", "Z", (0, 1)), ("Z1Z2", "Z", (1, 2)),
    ("Z3Z4", "Z", (3, 4)), ("Z4Z5", "Z", (4, 5)),
    ("Z6Z7", "Z", (6, 7)), ("Z7Z8", "Z", (7, 8)),
    ("X012345", "X", (0, 1, 2, 3, 4, 5)), ("X345678", "X", (3, 4, 5, 6, 7, 8)),
]


def encode(qc: Circuit, data: list[int]) -> None:
    """Encode the logical qubit currently on data[0] into the nine-qubit codeword."""
    d = data
    qc.cx(d[0], d[3]); qc.cx(d[0], d[6])          # phase-flip (outer) code
    qc.h(d[0]); qc.h(d[3]); qc.h(d[6])
    for a, b, c in BLOCKS:                          # bit-flip (inner) code per block
        qc.cx(d[a], d[b]); qc.cx(d[a], d[c])


def measure_stabilizer(qc: Circuit, anc: int, pauli: str, qubits, cbit: int) -> None:
    """Measure one stabilizer into cbit using the ancilla in |+⟩ (ancilla is reset first)."""
    qc.reset(anc)
    qc.h(anc)
    for q in qubits:
        if pauli == "Z":
            qc.cz(anc, q)
        else:
            qc.cx(anc, q)
    qc.h(anc)
    qc.measure(anc, cbit)


@register
class ShorCode(Experiment):
    id = "shor_code"
    title = "Shor's 9-qubit code: correcting any single-qubit error"
    category = "Error correction"
    summary = ("Encode one logical qubit in nine, inject any single-qubit error (bit, phase or both), measure the "
               "stabilizers, and watch feed-forward correction recover the logical state — real quantum error correction.")
    description = (
        "The Shor code concatenates a 3-qubit phase-flip code with 3-qubit bit-flip codes, so it corrects an arbitrary "
        "single-qubit error — the first code to do so. This runs the full cycle: encode a logical |0⟩ or |1⟩, inject a "
        "chosen Pauli error, measure the eight stabilizers with a reused ancilla (mid-circuit measurement), decode the "
        "syndrome and apply the correction via classical feed-forward, then measure the logical qubit. Any single X, Y "
        "or Z error is detected and fixed.")
    hardware_notes = ("9 data + 1 reused ancilla = 10 qubits, with mid-circuit measurement, reset and feed-forward — "
                      "needs a dynamic-circuit backend (local, or ibm:fake_*).")
    params = [Param("logical", "int", 1, "Logical state to protect (0 or 1)", 0, 1),
              Param("error_type", "choice", "Y", "Injected single-qubit error", choices=["I", "X", "Y", "Z"]),
              Param("error_qubit", "int", 4, "Qubit the error hits (0–8)", 0, 8),
              Param("correct", "bool", True, "Apply feed-forward correction")]
    default_shots = 512
    tutor = Tutor(
        concept="Quantum information is fragile, but it can be protected. Shor's code was the first to show that ANY "
                "single-qubit error — a bit flip, a phase flip, or both — can be detected and reversed without ever "
                "measuring (and destroying) the data.",
        how_it_works="One logical qubit is spread across nine. Eight 'stabilizer' measurements check parities between "
                     "qubits — revealing WHERE and WHAT error struck without reading the logical value. A classical "
                     "decoder turns that syndrome into a correction, applied by feed-forward, and the logical qubit is "
                     "measured intact.",
        intuition="Bit flips are caught by comparing qubits within each block of three; phase flips are caught by "
                  "comparing the three blocks. A Y error is both at once, and the two layers catch it together. The "
                  "trick is measuring relationships, never the data itself.",
        misconception="This corrects ONE error; two errors in the wrong places defeat distance-3 codes. And the "
                      "stabilizer measurements themselves must be fault-tolerant at scale. Real machines use the surface "
                      "code (lower overhead), but Shor's code is the conceptual origin.",
        what_to_look_for="The syndrome pinpoints the injected error, and with correction ON the logical measurement "
                         "returns the state you encoded. Turn correction OFF and a phase/Y error corrupts the logical bit.",
        try_this=["Inject each error_type on different qubits and read the syndrome — each error has a distinct signature.",
                  "Set correct=false with error_type=Z and watch the logical value flip; turn it on to recover.",
                  "Run on ibm:fake_fez: real noise adds errors the code sometimes can't fix (it handles only one)."],
        real_world_use="Error correction is the bridge to large-scale quantum computing — without it, Shor-scale "
                       "algorithms are impossible. Google's 2024 surface-code results showed error rates falling as the "
                       "code grows (below threshold), the key milestone.",
        going_deeper="The repetition code is the single-error-type on-ramp; the surface code is the scalable "
                     "descendant used in today's roadmaps.",
        references=[{"title": "Shor code", "url": "https://en.wikipedia.org/wiki/Quantum_error_correction#Shor_code"},
                    {"title": "Google: below-threshold surface code (Nature 2024)", "url": "https://www.nature.com/articles/s41586-024-08449-y"}],
        prerequisites=["repetition_code"],
    )

    def build(self, p):
        qc = Circuit(name=f"shor_code_{p['error_type']}{p['error_qubit']}")
        data = qc.add_qreg("d", 9)
        anc = qc.add_qreg("a", 1)
        syn = qc.add_creg("syn", 8)
        logical = qc.add_creg("log", 3)
        d = list(data)
        if p["logical"]:
            qc.x(d[0])                              # logical |1⟩ before encoding
        encode(qc, d)
        qc.barrier()
        e, eq = p["error_type"], p["error_qubit"]   # inject the error
        if e == "X":
            qc.x(d[eq])
        elif e == "Z":
            qc.z(d[eq])
        elif e == "Y":
            qc.y(d[eq])
        qc.barrier()
        for i, (_, pauli, qubits) in enumerate(STABS):
            measure_stabilizer(qc, anc[0], pauli, [d[q] for q in qubits], syn[i])
        if p["correct"]:
            self._correct(qc, d, syn)
        # logical Z_L = X0X1X2: measure block 0 in the X basis, parity gives the logical value
        for q in (0, 1, 2):
            qc.h(d[q])
            qc.measure(d[q], logical[q])
        return Plan([qc], {"logical": p["logical"], "error": f"{e} on q{eq}", "corrected": p["correct"]})

    def _correct(self, qc: Circuit, d, syn):
        # Bit-flip correction per block from its two Z-syndrome bits (clbits 2b, 2b+1).
        for b, (q0, q1, q2) in enumerate(BLOCKS):
            s_a, s_b = syn[2 * b], syn[2 * b + 1]
            with qc.if_test([s_a, s_b], 0b01):      # (Z_a Z_b=1, Z_b Z_c=0) → outer qubit q0
                qc.x(d[q0])
            with qc.if_test([s_a, s_b], 0b11):      # both → middle qubit q1
                qc.x(d[q1])
            with qc.if_test([s_a, s_b], 0b10):      # (0,1) → outer qubit q2
                qc.x(d[q2])
        # Phase-flip correction from the two X-syndrome bits (clbits 6, 7).
        p0, p1 = syn[6], syn[7]
        with qc.if_test([p0, p1], 0b01):            # block 0 phase flip
            qc.z(d[0])
        with qc.if_test([p0, p1], 0b11):            # block 1
            qc.z(d[3])
        with qc.if_test([p0, p1], 0b10):            # block 2
            qc.z(d[6])

    def analyze(self, p, ctx, results):
        res = results[0]
        logical_bit = ctx["logical"]
        # logical value = parity of the three X-basis measurements of block 0
        log_counts: dict[int, int] = {}
        syn_counts: dict[str, int] = {}
        for key, c in res.counts.items():
            log = res_marginal(res, key, "log")
            syn = res_marginal(res, key, "syn")
            val = log.count("1") % 2
            log_counts[val] = log_counts.get(val, 0) + c
            syn_counts[syn] = syn_counts.get(syn, 0) + c
        recovered = log_counts.get(logical_bit, 0) / res.shots
        top_syn = max(syn_counts.items(), key=lambda kv: kv[1])[0]
        # syndrome string is clbits high→low; show it human-ordered s0..s7
        syn_bits = top_syn.replace(" ", "").zfill(8)
        labelled = ", ".join(f"{STABS[i][0]}={syn_bits[8 - 1 - i]}" for i in range(8))
        ok = recovered > 0.9
        return Report(
            "Shor nine-qubit code",
            [f"Protected logical |{logical_bit}⟩; injected {ctx['error']}; correction {'ON' if ctx['corrected'] else 'OFF'}.",
             f"Syndrome: {labelled}.",
             f"Logical state recovered correctly in {recovered:.1%} of shots.",
             ("Any single-qubit error is detected and corrected." if ctx["corrected"]
              else "With correction off, a phase or Y error flips the logical bit — turn correction on to fix it.")],
            {"logical": logical_bit, "recovered_fraction": recovered, "corrected": ctx["corrected"],
             "syndrome": labelled},
            [Table("Logical measurement", ["logical value", "fraction"],
                   [[v, round(c / res.shots, 4)] for v, c in sorted(log_counts.items())])],
            [counts_chart("Syndrome patterns", syn_counts, top=8)],
            "pass" if ok else ("warn" if not ctx["corrected"] else "fail"))


def res_marginal(res, key: str, reg: str) -> str:
    """Extract register ``reg``'s bits from a full-width count key."""
    key = key.replace(" ", "")
    for name, start, size in res.registers:
        if name == reg:
            return key[res.num_clbits - start - size: res.num_clbits - start]
    return ""
