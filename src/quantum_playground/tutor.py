"""Built-in quantum computing tutor: an ordered curriculum, a glossary, and helpers.

The curriculum is a guided path from "what is a qubit" to real-world applications,
and every lesson ends with a concrete experiment to run in the playground. It
complements the per-experiment ``Tutor`` objects (see experiments/base.py): the
curriculum teaches the ideas in order; the per-experiment tutors explain each
runnable demo in place.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

LEVELS = ("foundations", "algorithms", "applications", "hardware")


@dataclass
class Lesson:
    id: str
    title: str
    level: str
    big_idea: str
    key_intuition: str
    common_misconception: str
    real_world_use: str
    try_experiment: str          # experiment id
    try_what_to_look_for: str
    steps: list[str] = field(default_factory=list)
    further_reading: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "level": self.level, "big_idea": self.big_idea,
                "key_intuition": self.key_intuition, "common_misconception": self.common_misconception,
                "real_world_use": self.real_world_use, "try_experiment": self.try_experiment,
                "try_what_to_look_for": self.try_what_to_look_for, "steps": list(self.steps),
                "further_reading": list(self.further_reading)}


CURRICULUM: list[Lesson] = [
    Lesson(
        "qubits", "Qubits and superposition", "foundations",
        "A classical bit is 0 or 1. A qubit can be in a superposition α|0⟩ + β|1⟩ — a weighted blend of both — "
        "until measured, when it randomly becomes 0 or 1 with probabilities |α|² and |β|².",
        "Superposition is not 'secretly 0 or 1 and we don't know which'. The qubit genuinely has no definite value; "
        "the blend itself is physical and leads to interference effects a hidden value could never produce.",
        "A qubit does not 'store both 0 and 1 so n qubits do 2ⁿ calculations at once'. You only ever read out one "
        "n-bit answer. The power comes from interference, not from reading a parallel memory.",
        "Superposition underlies quantum random number generators shipping today and is the raw material of every "
        "quantum algorithm.",
        "qrng", "Each |+⟩ qubit measured gives a true 50/50 bit; the per-qubit bias table shows how real hardware "
        "deviates from the ideal coin.",
        steps=["A Hadamard gate (H) turns |0⟩ into the equal superposition |+⟩ = (|0⟩+|1⟩)/√2.",
               "Measuring |+⟩ gives 0 or 1 with equal probability — genuine randomness.",
               "Run qrng and read the counts; then read the QRNG tutor for extractors."],
        further_reading=[{"title": "Quantum Country: Superposition", "url": "https://quantum.country/qcvc"}],
    ),
    Lesson(
        "measurement", "Measurement and the Bloch sphere", "foundations",
        "Measuring a qubit collapses its superposition to a basis state, and the basis you choose matters. A qubit's "
        "state is a point on the Bloch sphere; measurement projects it onto an axis.",
        "The Bloch sphere makes single-qubit states visual: north pole |0⟩, south pole |1⟩, equator the superpositions. "
        "Gates are rotations of this sphere; measurement reads the chosen axis.",
        "Measurement is not passive observation — it changes the state. And measuring in the 'wrong' basis destroys the "
        "information encoded in another basis (the fact BB84 security rests on).",
        "Basis-dependent measurement is exactly what makes eavesdropping detectable in quantum cryptography.",
        "custom", "Build a single-qubit circuit in the Circuit Lab and watch its Bloch vector move as you add H, S and "
        "T gates; the vector length (purity) stays 1 for a pure state.",
        steps=["Open the Circuit Lab, set qubits to 1.", "Add H, then S, then T and watch the Bloch sphere rotate.",
               "Add a measurement and run — the outcome statistics match the Bloch vector's Z-projection."],
    ),
    Lesson(
        "gates", "Gates, circuits and interference", "foundations",
        "Quantum gates are reversible rotations; a circuit is a sequence of them. The real power is INTERFERENCE: "
        "amplitudes can add or cancel, which is how quantum algorithms steer probability toward the right answer.",
        "Think of amplitudes as arrows with direction (phase). Two paths to the same outcome add their arrows; opposite "
        "arrows cancel. Algorithms arrange cancellation of wrong answers and reinforcement of right ones.",
        "Phase has no classical analogue and is invisible to a final measurement on its own — but interference converts "
        "phase differences into measurable probability differences. Ignoring phase misses the whole mechanism.",
        "Interference is the engine inside Deutsch–Jozsa, Grover and Shor.",
        "deutsch_jozsa", "A single oracle query decides 'constant vs balanced' because interference makes the all-zeros "
        "outcome certain or impossible — watch P(00…0).",
        steps=["Run deutsch_jozsa with oracle=constant0 (expect all zeros) then oracle=balanced (expect non-zero).",
               "Read the Deutsch–Jozsa tutor for how phase kickback sets up the interference."],
    ),
    Lesson(
        "entanglement", "Entanglement and Bell's theorem", "foundations",
        "Entangled qubits share correlations stronger than any classical system allows. A Bell pair's two qubits have "
        "no individual state, yet their measurements are perfectly linked.",
        "Entanglement is a property of the whole, not the parts. The CHSH test turns this into a number (S) that a "
        "classical 'hidden variable' universe can't reach.",
        "Entanglement does NOT allow faster-than-light signalling — each side sees only randomness until results are "
        "compared classically.",
        "Entanglement is the resource behind teleportation, superdense coding, QKD and quantum networking.",
        "chsh", "S above 2 violates the classical bound; the ideal quantum value is 2√2 ≈ 2.83. Watch the violation "
        "vanish when you rotate Bob's angles with bob_offset_deg.",
        steps=["Run bell_states and confirm fidelity ≈ 1 and ⟨XX⟩=⟨ZZ⟩=1, ⟨YY⟩=−1.",
               "Run chsh and read S; then set bob_offset_deg=45 and watch it fall to 2."],
        further_reading=[{"title": "Nobel Prize 2022 (Bell tests)", "url": "https://www.nobelprize.org/prizes/physics/2022/"}],
    ),
    Lesson(
        "teleportation", "Moving quantum information", "foundations",
        "You can't copy an unknown qubit (no-cloning), but you can MOVE it. Teleportation relocates a state using a "
        "shared Bell pair and two classical bits; superdense coding does the reverse trade.",
        "The entangled pair is a pre-positioned 'wire'; the classical bits tell the receiver which correction to apply. "
        "No information travels faster than those classical bits.",
        "Teleportation moves, not copies — the original is destroyed, consistent with no-cloning. Nothing material or "
        "superluminal is transmitted.",
        "Teleportation is the routing primitive of quantum networks and the quantum internet.",
        "teleportation", "The reconstructed Bloch vector should match the input and fidelity should beat the classical "
        "2/3 bound; 'dynamic' mode uses real mid-circuit feed-forward.",
        steps=["Run teleportation and check the fidelity and reconstructed Bloch vector.",
               "Run superdense and confirm all four 2-bit messages decode."],
    ),
    Lesson(
        "oracle-algorithms", "Oracle algorithms and speedups", "algorithms",
        "Oracle algorithms (Deutsch–Jozsa, Bernstein–Vazirani, Simon) prove quantum computers can need dramatically "
        "fewer queries than classical ones to learn a hidden structure — the first concrete speedups.",
        "Each uses phase kickback + interference to extract global information (a bit, a string, a period) in far fewer "
        "black-box calls than any classical strategy.",
        "These speedups are in the QUERY model with a given oracle; they don't by themselves speed up every problem. "
        "They are stepping stones to Shor and Grover.",
        "Simon's exponential query gap is the direct ancestor of Shor's factoring algorithm.",
        "simon", "Every measured y satisfies y·s = 0; collect several and solve over GF(2) to recover the hidden period s.",
        steps=["Run bernstein_vazirani to read a hidden string in one query.",
               "Run simon and watch distinct outcomes ≈ 2^(n−1), the 2-to-1 fingerprint."],
    ),
    Lesson(
        "grover", "Grover search and amplitude amplification", "algorithms",
        "Grover finds a marked item among N in ≈√N steps — a quadratic speedup over classical brute force, and provably "
        "optimal for unstructured search.",
        "Alternate an oracle (flip the target's sign) with a diffuser (reflect about the mean). Each round rotates "
        "amplitude toward the answer; stop at the peak.",
        "Amplitude amplification OVERSHOOTS — too many iterations lowers the success probability again. And √N is only "
        "quadratic, not exponential: no magic for NP-complete problems.",
        "Grover speeds up any brute-force search, including guessing symmetric keys and hash preimages — the reason "
        "quantum-era key lengths are debated.",
        "grover", "Success probability peaks near (π/4)√N iterations, then falls; the report plots this curve.",
        steps=["Run grover and set iterations beyond the optimum to see the overshoot.",
               "Run grover_sat to see a real logical oracle; read the security lessons for key-search implications."],
    ),
    Lesson(
        "qft-shor", "Period finding: QFT, phase estimation and Shor", "algorithms",
        "The Quantum Fourier Transform exposes hidden periods. Phase estimation reads an eigenphase; Shor's algorithm "
        "uses period finding to factor numbers exponentially faster than any known classical method.",
        "A periodic pattern becomes sharp peaks after the QFT. Shor turns 'factor N' into 'find the period of aˣ mod N', "
        "which the QFT reveals; number theory finishes the job.",
        "Today's hardware can only factor tiny numbers (15, 21). Breaking RSA-2048 needs millions of error-corrected "
        "qubits — a future threat, not a present capability.",
        "Shor is why post-quantum cryptography is being standardised and deployed now.",
        "shor", "Peaks appear at multiples of 2ᵗ/r; the report recovers the order r and factors (e.g. 15 = 3×5).",
        steps=["Run qft in periodic mode to see the peaks.", "Run qpe to read an eigenphase.",
               "Run shor on N=15, a=7 and read the recovered factors."],
    ),
    Lesson(
        "variational", "Variational algorithms for today's hardware", "algorithms",
        "VQE and QAOA are hybrid quantum-classical loops that run useful computations on NISQ (noisy, non-corrected) "
        "devices by keeping circuits shallow and letting a classical optimiser tune their parameters.",
        "The quantum device is a fast evaluator (of an energy, or an objective) inside a classical optimisation loop. "
        "Shallow circuits tolerate noise better than deep ones like Shor.",
        "Variational methods are heuristics: they can hit local minima or 'barren plateaus', and a quantum advantage "
        "over classical solvers is not guaranteed — it's an active research question.",
        "VQE targets chemistry and materials; QAOA targets optimisation in finance and logistics.",
        "vqe_h2", "The measured H₂ energy should approach the exact value within chemical accuracy (1.6 mHa); SPSA and "
        "readout mitigation help on noisy backends.",
        steps=["Run vqe_h2 and compare the measured energy to the exact value.",
               "Run qaoa_maxcut and read the approximation ratio vs the brute-force optimum."],
    ),
    Lesson(
        "security", "Quantum computing and cryptography", "applications",  # noqa: E128
        "Quantum computers threaten today's cryptography in two ways: Shor breaks public-key crypto (RSA, ECC), and "
        "Grover halves the effective strength of symmetric keys and hashes. The response is post-quantum crypto and QKD.",
        "Shor is an exponential break (public-key is doomed once big enough QPUs exist); Grover is 'only' quadratic, so "
        "doubling symmetric key lengths (AES-256) restores safety. 'Harvest now, decrypt later' makes it urgent for "
        "long-lived secrets.",
        "Quantum computers do NOT break everything, and they can't crack a well-chosen AES-256 key in practice. The "
        "demos here are toy-scale and synthetic — they illustrate the SCALING, they do not attack real systems.",
        "NIST standardised ML-KEM/ML-DSA (2024); migration to post-quantum crypto is underway across industry.",
        "grover_key_search", "A toy known-plaintext attack recovers a key with Grover's √ speedup, and the key-length "
        "table shows why AES-128 drops to ~64-bit quantum security while AES-256 stays safe.",
        steps=["Run grover_key_search to recover a secret key and read the key-length cost table.",
               "Run qday_estimator to factor 15 with Shor and estimate what breaking RSA-2048 would take.",
               "Run the Enigma Grover lab (model=mini) for cryptographic key search on a historical cipher."],
        further_reading=[{"title": "NIST Post-Quantum Cryptography", "url": "https://csrc.nist.gov/projects/post-quantum-cryptography"}],
    ),
    Lesson(
        "optimization", "Optimization, finance and logistics", "applications",
        "Many business problems — portfolio selection, routing, scheduling — are combinatorial optimisation. QAOA and "
        "quantum annealing encode them as QUBOs and search for good solutions.",
        "Encode the objective as an Ising/QUBO energy; the quantum algorithm biases sampling toward low-energy (good) "
        "configurations. More layers approximate the adiabatic optimum.",
        "These are heuristics with no proven advantage yet over the best classical solvers; pilots test whether and "
        "where they help, not a settled win.",
        "Banks, logistics firms and manufacturers run QAOA/annealing pilots on portfolio, routing and scheduling.",
        "qaoa_portfolio", "The chosen portfolio's return/risk vs the brute-force optimum, and whether it meets the "
        "budget — all from a QUBO solved by QAOA.",
        steps=["Run qaoa_portfolio to pick assets balancing return and risk.",
               "Run qaoa_mis for conflict-free allocation, and qaoa_maxcut for the base case — same QUBO machinery."],
    ),
    Lesson(
        "chemistry-ml", "Chemistry, materials and machine learning", "applications",
        "Simulating molecules is where quantum computers may help first, because nature is quantum. Quantum machine "
        "learning explores whether quantum feature maps can classify data classical kernels find hard.",
        "VQE finds molecular ground-state energies (structure, reactivity). Quantum kernels embed data into a large "
        "Hilbert space; the question is whether that embedding is genuinely useful.",
        "Neither is a solved advantage: molecule sizes are small today, and quantum-ML advantage on real data is "
        "unproven. The value is in the research direction, not current production use.",
        "Drug discovery, battery materials and catalyst design are the target applications; pilots exist at major labs.",
        "vqe_ising", "VQE's energy vs exact and the magnet's phase transition; for ML, the quantum-kernel accuracy vs a "
        "classical linear kernel on a 2D dataset.",
        steps=["Run vqe_ising to find a quantum magnet's ground state and see its phase transition.",
               "Run qkernel to classify data with a quantum kernel and compare to classical kernels.",
               "Run vqe_h2 for the molecular-chemistry version."],
    ),
    Lesson(
        "simulation-sensing", "Simulation, sensing and the quantum internet", "applications",
        "Beyond computing, quantum devices simulate physics (spin dynamics), sense with extreme precision (metrology), "
        "and network via entanglement (the quantum internet).",
        "Trotterization turns a Hamiltonian into gate sequences to watch dynamics. GHZ states beat the standard quantum "
        "limit in sensing. Entanglement swapping extends entanglement across a network.",
        "Analog quantum simulation already does useful physics; Heisenberg-limited sensing is real; a full quantum "
        "internet is still experimental.",
        "Quantum simulation studies magnetism and chemistry; quantum sensors improve clocks, gravimeters and imaging; "
        "quantum networks enable long-distance QKD.",
        "tfim_dynamics", "Simulated magnetization tracking the exact curve (quantum simulation), and — in the metrology "
        "and walk experiments — Heisenberg-limited sensing and ballistic spreading.",
        steps=["Run tfim_dynamics to simulate a quantum magnet evolving in real time.",
               "Run quantum_walk to see ballistic (vs classical diffusive) spreading.",
               "Run ghz_metrology to sense a phase N× more sharply with entanglement (Heisenberg limit)."],
    ),
    Lesson(
        "hardware-noise", "Real hardware: noise, coherence and error correction", "hardware",
        "Real qubits are noisy and forget quickly (T1, T2). Error correction spreads one logical qubit across many "
        "physical ones to detect and fix errors — the path to large-scale quantum computing.",
        "Coherence times bound how deep a circuit can run. Error correction measures parities (syndromes) to fix errors "
        "without reading the data; below a noise threshold, more qubits mean fewer logical errors.",
        "Error correction has overhead (many physical per logical qubit) and only works below threshold. 2023–2024 saw "
        "the first below-threshold demonstrations — a milestone, not a finished product.",
        "Fault-tolerant quantum computing — needed for Shor-scale algorithms — is built from error correction; it is "
        "the central engineering challenge of the field.",
        "coherence", "Fit T1 and T2 on a noise model or real device; then see the repetition and Shor codes suppress "
        "and correct errors.",
        steps=["Run coherence on local-noisy:heron_like and on ibm:fake_fez.",
               "Run repetition_code (one error type) and compare the logical vs unencoded error rate.",
               "Run shor_code to correct an arbitrary single-qubit error with live syndrome + feed-forward."],
    ),
]

GLOSSARY: dict[str, str] = {
    "qubit": "The basic unit of quantum information; can be in a superposition of |0⟩ and |1⟩.",
    "superposition": "A weighted combination of basis states; the qubit has no definite value until measured.",
    "amplitude": "The complex number whose squared magnitude gives an outcome's probability; carries phase.",
    "phase": "The direction (angle) of a complex amplitude; invisible alone but drives interference.",
    "interference": "Amplitudes for the same outcome adding or cancelling — the mechanism behind quantum speedups.",
    "entanglement": "A correlation between qubits with no classical explanation; the parts have no individual state.",
    "Bell state": "A maximally entangled two-qubit state, e.g. (|00⟩+|11⟩)/√2.",
    "measurement": "Reading a qubit, which collapses its superposition to a basis state along the chosen axis.",
    "Bloch sphere": "A geometric picture of a single qubit's state as a point on a unit sphere.",
    "Hadamard": "The gate H that creates equal superpositions; turns |0⟩ into |+⟩.",
    "CNOT": "A two-qubit gate that flips the target if the control is |1⟩; used to create entanglement.",
    "phase kickback": "A trick where a controlled operation stamps a phase onto the control qubit.",
    "oracle": "A black-box (or built) circuit that marks solutions, e.g. by flipping their sign.",
    "amplitude amplification": "Grover's technique of boosting a marked state's amplitude by reflections.",
    "QFT": "Quantum Fourier Transform; exposes periods and phases with O(n²) gates.",
    "phase estimation": "Reads the eigenphase of a unitary; the core of Shor and of quantum chemistry.",
    "VQE": "Variational Quantum Eigensolver; finds ground-state energies via a hybrid quantum-classical loop.",
    "QAOA": "Quantum Approximate Optimization Algorithm; a variational method for combinatorial problems.",
    "QUBO": "Quadratic Unconstrained Binary Optimization; the standard encoding for annealers and QAOA.",
    "NISQ": "Noisy Intermediate-Scale Quantum; today's error-prone devices without full error correction.",
    "T1": "Energy relaxation time: how long a qubit keeps its excited state.",
    "T2": "Dephasing time: how long a qubit keeps its phase coherence.",
    "QKD": "Quantum Key Distribution; sharing secret keys with security guaranteed by physics.",
    "QBER": "Quantum Bit Error Rate; the error fraction used to detect eavesdropping in QKD.",
    "no-cloning": "The theorem that an unknown quantum state cannot be copied.",
    "post-quantum cryptography": "Classical cryptography (e.g. ML-KEM, ML-DSA) believed secure against quantum attack.",
    "error correction": "Encoding logical qubits across many physical qubits to detect and fix errors.",
    "syndrome": "A parity measurement that reveals where an error occurred without reading the data.",
    "fidelity": "A measure (0–1) of how close a prepared state or result is to the ideal.",
    "shot": "One execution-and-measurement of a circuit; many shots build up outcome statistics.",
    "readout mitigation": "Correcting measurement (assignment) errors using calibration circuits.",
    "transpilation": "Rewriting a circuit into a device's native gates and connectivity.",
}


def lesson_by_id(lesson_id: str) -> Optional[Lesson]:
    for lsn in CURRICULUM:
        if lsn.id == lesson_id:
            return lsn
    return None


def curriculum_dict() -> list[dict]:
    return [lsn.to_dict() for lsn in CURRICULUM]


def format_lesson(lsn: Lesson) -> str:
    out = [f"=== {lsn.title}  [{lsn.level}] ===", "",
           "Big idea:", _wrap(lsn.big_idea), "",
           "Key intuition:", _wrap(lsn.key_intuition), "",
           "Common misconception:", _wrap(lsn.common_misconception), "",
           "Why it matters:", _wrap(lsn.real_world_use), "",
           f"Try in the playground:  qplay run {lsn.try_experiment}",
           _wrap("  " + lsn.try_what_to_look_for)]
    if lsn.steps:
        out += ["", "Steps:"] + [f"  {i}. {s}" for i, s in enumerate(lsn.steps, 1)]
    if lsn.further_reading:
        out += ["", "Further reading:"] + [f"  - {r['title']}: {r['url']}" for r in lsn.further_reading]
    return "\n".join(out)


def _wrap(text: str, width: int = 96) -> str:
    import textwrap
    return "\n".join(textwrap.fill(p, width) for p in text.split("\n"))
