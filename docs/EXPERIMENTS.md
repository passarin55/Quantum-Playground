# Experiments

Generated from the registry (`python scripts/gen_experiment_docs.py`). Run any of them with
`qplay run <id> [-p name=value ...] [-b backend]`; every report carries a pass/warn/fail verdict.

## Chemistry & Materials

### `vqe_ising` — VQE: quantum magnet ground state & phase transition

Find the ground state of a transverse-field Ising spin chain with VQE, and sweep the field to watch a quantum phase transition — the kind of materials problem quantum computers target.

The transverse-field Ising model H = −J Σ ZᵢZᵢ₊₁ − h Σ Xᵢ is the textbook quantum magnet: at small field h the spins order (ferromagnet); at large h they align with the field (paramagnet), with a quantum phase transition between. VQE optimises a hardware-efficient ansatz to approximate the ground energy, measured on the backend from Z- and X-basis groups. The report compares to exact diagonalisation and reports the magnetisation order parameter.

*Hardware:* n qubits (default 6), a linear CX entangler — a realistic condensed-matter demo on hardware.

| parameter | type | default | description |
|---|---|---|---|
| `spins` | int | `6` | Number of spins (qubits) |
| `coupling` | float | `1.0` | Ising coupling J |
| `field` | float | `0.5` | Transverse field h (h≈J is near the transition) |
| `layers` | int | `2` | Ansatz entangling layers |
| `optimizer` | choice (nelder_mead, spsa) | `nelder_mead` | Optimiser |

Default shots: 2000

## Circuit Lab

### `custom` — Custom circuit

Execute a circuit from the composer (JSON) or OpenQASM on any backend, compared with the ideal.

| parameter | type | default | description |
|---|---|---|---|
| `circuit` | str | `—` | qplay circuit JSON or OpenQASM 2/3 source |

Default shots: 2000

## Device physics

### `coherence` — Qubit coherence: T1 relaxation and Ramsey T2*

Delay sweeps with exponential / damped-cosine fits — run on a noisy simulator or real hardware.

T1: X, wait t, measure → P(1) = A·e^(−t/T1) + B. Ramsey: H (a π/2 pulse), wait t, virtual detuning rotation RZ(2π f t), H, measure → damped oscillation with envelope e^(−t/T2*). The ideal `local` simulator has no decoherence (flat curves); use `local-noisy:heron_like`, `aer:fake_fez` or a real device.

*Hardware:* 2 × points single-qubit circuits.

| parameter | type | default | description |
|---|---|---|---|
| `delays_us` | str | `0,15,30,60,100,150,220,300` | Delay points in microseconds |
| `detuning_mhz` | float | `0.02` | Ramsey virtual detuning (MHz) |

Default shots: 1000

## Enigma

### `enigma_grover` — Enigma: Grover search for the rotor start window

Encrypt a message, then let Grover's algorithm find which of 2^b candidate start windows was used.

The secret setting differs from the publicly-known settings only in one rotor's start window (right rotor by default). The oracle runs the *real* Enigma permutation coherently on a 5-qubit letter register for every candidate (see enigma/quantum.py), compares with the known crib, and phase-marks matches. The measured key index is turned back into a machine setting and used to decrypt the whole message. This is an educational restricted search: a classical scan of all 17 576 windows takes milliseconds and is shown for comparison.

*Hardware:* Mini model: 4 qubits, tens of gates — realistic on IBM Heron. Historical model: 7–10 qubits and hundreds of multi-controlled gates — expect near-uniform output on today's hardware; use the preflight to see native two-qubit counts first.

| parameter | type | default | description |
|---|---|---|---|
| `model` | choice (historical, mini) | `historical` | Machine |
| `message` | str | `WETTERBERICHTXNORDSEE` | Plaintext (A–Z; ABCD for mini) |
| `crib_length` | int | `1` | Known-plaintext letters used by the oracle |
| `rotors` | str | `I II III` | Rotor order (historical) |
| `rings` | str | `1 1 1` | Ring settings |
| `reflector` | str | `B` | Reflector |
| `plugboard` | str | `AV BS CG` | Plugboard pairs |
| `secret_window` | str | `AAC` | Secret start window (historical) or 0-3 (mini) |
| `key_bits` | int | `2` | Unknown key qubits (historical: 1-4) |
| `first` | str | `A` | First candidate letter of the unknown rotor window |
| `vary` | choice (right, middle, left) | `right` | Which rotor window is unknown |
| `synthesis` | choice (auto, compiled, staged, factored) | `auto` | Oracle synthesis |
| `oracle` | choice (phase, flag) | `phase` | Oracle style |
| `iterations` | int | `-1` | Grover iterations (-1 = optimal for one solution) |

Default shots: 2000

### `enigma_keysheet` — Quantum-random Enigma key sheet

Generate a daily key sheet from measured quantum random bits, then encrypt a message with day 1.

Random bits come from |+⟩ measurements; integers are drawn by rejection sampling (no modulo bias) to pick rotor order, rings, plugboard pairs and start windows. If the quantum bits run out, the OS CSPRNG fills in and the report says how many bits came from each.

| parameter | type | default | description |
|---|---|---|---|
| `days` | int | `7` | Days on the sheet |
| `qubits` | int | `16` | Qubits per shot |
| `message` | str | `ANGRIFFUMNULLSECHSHUNDERT` | Message to encrypt with day 1 |

Default shots: 256

## Entanglement

### `bell_states` — Bell-state fidelity (XX / YY / ZZ correlations)

Prepare a Bell state and estimate its fidelity from three Pauli correlators.

A Bell projector is |B><B| = (II + s_x XX + s_y YY + s_z ZZ)/4, so measuring the three two-qubit correlators gives the fidelity F = (1 + s_x<XX> + s_y<YY> + s_z<ZZ>)/4 exactly. F > 0.5 certifies entanglement.

*Hardware:* 3 circuits, 2 qubits, 1 CX each — ideal first hardware test.

| parameter | type | default | description |
|---|---|---|---|
| `state` | choice (phi+, phi-, psi+, psi-) | `phi+` | Bell state |

Default shots: 2000

### `chsh` — CHSH Bell-inequality test

Violate the CHSH inequality |S| ≤ 2 obeyed by every local-hidden-variable theory.

Alice measures at angles 0 and π/2, Bob at π/4 and −π/4 (in the X–Z plane). Quantum mechanics predicts S = 2√2 ≈ 2.828 (Tsirelson's bound); any local realistic model gives |S| ≤ 2. Rotate Bob's settings with `bob_offset_deg` to watch the violation vanish.

*Hardware:* 4 circuits × 2 qubits. Heron-class devices typically reach S ≈ 2.6–2.75.

| parameter | type | default | description |
|---|---|---|---|
| `bob_offset_deg` | float | `0.0` | Extra rotation of Bob's measurement axes (degrees) |

Default shots: 2000

### `ghz` — GHZ state: populations + parity oscillations

Create an n-qubit GHZ state and estimate its fidelity from parity oscillations.

Fidelity F = (P(0…0) + P(1…1))/2 + C/2, where C is the amplitude of the parity oscillation ⟨P(φ)⟩ = C cos(nφ) obtained by rotating every qubit by RZ(φ) and measuring X. Population alone does not prove coherence; the parity contrast does.

*Hardware:* 1 + `phases` circuits; n−1 CX in a chain (or log-depth tree).

| parameter | type | default | description |
|---|---|---|---|
| `n` | int | `4` | Number of qubits |
| `phases` | int | `8` | Parity phases sampled |
| `layout` | choice (chain, tree) | `chain` | Entangling pattern |

Default shots: 2000

## Error correction

### `repetition_code` — Repetition code: syndrome extraction and majority decoding

Encode one logical qubit in d physical qubits, inject errors, measure syndromes, decode.

Errors are injected as coherent rotations RX(θ) (bit-flip code) or RZ(θ) (phase-flip code) with sin²(θ/2) = p on every data qubit; syndrome measurement discretises them into probabilistic Pauli errors. Majority voting fails only when more than (d−1)/2 qubits flip, so P_L ≈ Σ_{k>d/2} C(d,k) p^k (1−p)^(d−k) ≪ p for small p. An unencoded qubit with the same error is run alongside for comparison.

*Hardware:* 2d−1 qubits; ancillas measured mid-circuit (data measured at the end).

| parameter | type | default | description |
|---|---|---|---|
| `distance` | int | `3` | Code distance d (odd) |
| `p` | float | `0.1` | Injected error probability per data qubit |
| `flip` | choice (bit, phase) | `bit` | Error/code type |
| `logical` | int | `1` | Logical state to protect (0 or 1) |

Default shots: 2000

### `shor_code` — Shor's 9-qubit code: correcting any single-qubit error

Encode one logical qubit in nine, inject any single-qubit error (bit, phase or both), measure the stabilizers, and watch feed-forward correction recover the logical state — real quantum error correction.

The Shor code concatenates a 3-qubit phase-flip code with 3-qubit bit-flip codes, so it corrects an arbitrary single-qubit error — the first code to do so. This runs the full cycle: encode a logical |0⟩ or |1⟩, inject a chosen Pauli error, measure the eight stabilizers with a reused ancilla (mid-circuit measurement), decode the syndrome and apply the correction via classical feed-forward, then measure the logical qubit. Any single X, Y or Z error is detected and fixed.

*Hardware:* 9 data + 1 reused ancilla = 10 qubits, with mid-circuit measurement, reset and feed-forward — needs a dynamic-circuit backend (local, or ibm:fake_*).

| parameter | type | default | description |
|---|---|---|---|
| `logical` | int | `1` | Logical state to protect (0 or 1) |
| `error_type` | choice (I, X, Y, Z) | `Y` | Injected single-qubit error |
| `error_qubit` | int | `4` | Qubit the error hits (0–8) |
| `correct` | bool | `True` | Apply feed-forward correction |

Default shots: 512

## Fourier

### `qft` — Quantum Fourier transform: round trip and period finding

Encode an integer in Fourier phases and read it back with QFT†, or reveal a period with the QFT.

`fourier_state`: prepare QFT|y⟩ with H + phase gates, apply the inverse QFT, measure y. `periodic`: prepare a uniform superposition over multiples of r (r a power of two), apply the QFT, and observe peaks at multiples of 2^n / r.

| parameter | type | default | description |
|---|---|---|---|
| `n` | int | `5` | Qubits |
| `mode` | choice (fourier_state, periodic) | `fourier_state` | Demo |
| `value` | int | `13` | Integer y (fourier_state) or period r (periodic, power of 2) |

Default shots: 2000

### `qpe` — Quantum phase estimation of P(2πφ)

Estimate the eigenphase φ of a phase gate with t counting qubits (precision 2^-t).

| parameter | type | default | description |
|---|---|---|---|
| `phi` | float | `0.3125` | Eigenphase φ in [0, 1) |
| `t` | int | `5` | Counting qubits |

Default shots: 2000

### `shor` — Shor's algorithm: order finding and factoring

Quantum order finding of a mod N with exact reversible modular multipliers, then classical factoring.

Controlled multiplication by a^(2^k) mod N is compiled as an exact permutation of the work register (values ≥ N fixed) with transformation-based synthesis — a full modular multiplier on every basis state, not a shortcut that assumes the answer. Continued fractions turn each measured y/2^t into a candidate order r; factors follow from gcd(a^(r/2) ± 1, N).

*Hardware:* N=15: 12 qubits. Multipliers compile to hundreds of 2q gates — a stress test on hardware.

| parameter | type | default | description |
|---|---|---|---|
| `N` | int | `15` | Number to factor (odd composite, ≤ 63) |
| `a` | int | `7` | Base coprime to N |
| `t` | int | `0` | Counting qubits (0 = 2·⌈log2 N⌉, capped at 12) |

Default shots: 2000

## Machine Learning

### `qkernel` — Quantum-kernel classifier (machine learning)

Embed data into quantum states, estimate a quantum kernel on the backend, and classify a 2D dataset — then compare the decision boundary to a classical kernel.

Quantum machine learning via kernels. Each 2D point is embedded by a feature-map circuit into a 2-qubit state; the kernel K(x,x') = |⟨φ(x')|φ(x)⟩|² is estimated on the backend by running U(x')†U(x) and measuring the all-zeros probability. A kernel classifier (nearest class by mean kernel) then labels test points. The report compares quantum-kernel accuracy to a classical RBF kernel on the same split.

*Hardware:* 2 qubits; one overlap circuit per (train,point) pair — many shallow circuits, ideal for batching.

| parameter | type | default | description |
|---|---|---|---|
| `dataset` | choice (circles, xor, linear) | `circles` | Synthetic dataset |
| `train` | int | `12` | Training points |
| `test` | int | `6` | Test points |
| `reps` | int | `2` | Feature-map repetitions (depth/expressibility) |
| `seed` | int | `1` | Dataset seed |

Default shots: 2048

## Metrology

### `ghz_metrology` — GHZ-enhanced sensing (Heisenberg-limit metrology)

Entangled GHZ probes sense a phase N times more sharply than N independent qubits — beating the standard quantum limit, the basis of quantum-enhanced sensors.

A sensor estimates an unknown phase φ. With N independent qubits (standard Ramsey interferometry) the signal oscillates as cos(φ) and precision improves as √N (the standard quantum limit). With an N-qubit GHZ state the accumulated phase is Nφ, so the parity oscillates as cos(Nφ) — N times faster — giving precision ∝ N (the Heisenberg limit). This experiment sweeps φ and measures both signals, extracting the N-fold frequency gain.

*Hardware:* Sweeps N; each point is an N-qubit GHZ parity measurement. GHZ fragility limits useful N on hardware.

| parameter | type | default | description |
|---|---|---|---|
| `n` | int | `4` | Number of entangled probe qubits N |
| `phases` | int | `32` | Phase points sampled |
| `phase_span` | float | `1.0` | Phase sweep span in full single-qubit periods (2π) |

Default shots: 2000

## Optimization

### `qaoa_mis` — QAOA maximum independent set (scheduling / networks)

Find the largest set of mutually non-conflicting items — wireless channels, compatible jobs, non-adjacent nodes — as a QUBO solved with QAOA.

Maximum independent set: pick the most vertices of a graph with no edge between any two. It models conflict-free allocation (frequencies, time slots, non-interfering transmitters). As a QUBO we maximise the number chosen minus a penalty for every conflicting pair selected, then solve with QAOA and compare to the brute-force maximum.

*Hardware:* One qubit per vertex (default from the graph); each edge is an RZZ per layer.

| parameter | type | default | description |
|---|---|---|---|
| `edges` | str | `0-1,1-2,2-3,3-4,4-0,0-2` | Graph edges a-b, comma separated |
| `penalty` | float | `3.0` | Conflict penalty λ (≥ 2 guarantees independence) |
| `layers` | int | `2` | QAOA layers p |

Default shots: 2000

### `qaoa_portfolio` — QAOA portfolio optimization (finance)

Pick the best B of n assets to balance expected return against risk, encoded as a QUBO and solved with QAOA — the canonical quantum-finance use case.

Mean-variance portfolio selection: maximise expected return μ·x minus risk-aversion q·(xᵀΣx), subject to choosing exactly B assets (a budget penalty λ(Σxᵢ−B)²). This becomes a QUBO, maps to an Ising Hamiltonian, and QAOA samples low-'energy' (high-quality) portfolios. The report compares the sampled portfolio to the brute-force optimum and checks the budget constraint.

*Hardware:* One qubit per asset (default 6). Each asset pair contributes an RZZ per layer.

| parameter | type | default | description |
|---|---|---|---|
| `assets` | int | `6` | Number of candidate assets |
| `budget` | int | `3` | Assets to hold (budget) |
| `risk_aversion` | float | `0.5` | Risk-aversion q (higher = more cautious) |
| `penalty` | float | `2.0` | Budget-constraint penalty strength λ |
| `layers` | int | `2` | QAOA layers p |
| `seed` | int | `7` | Seed for the synthetic market (returns/covariance) |

Default shots: 2000

## Oracles

### `bernstein_vazirani` — Bernstein–Vazirani: read a hidden string in one query

Recover s from f(x) = s·x mod 2 with one query (classically n queries).

*Hardware:* n+1 qubits, popcount(s) CX gates.

| parameter | type | default | description |
|---|---|---|---|
| `secret` | bits | `101101` | Hidden bitstring s (MSB first); empty = random 6 bits |

Default shots: 2000

### `deutsch_jozsa` — Deutsch–Jozsa: constant vs balanced in one query

Decide whether f:{0,1}^n→{0,1} is constant or balanced with a single oracle call.

*Hardware:* n+1 qubits, ≤ n CX gates.

| parameter | type | default | description |
|---|---|---|---|
| `n` | int | `4` | Input bits |
| `oracle` | choice (balanced, constant0, constant1) | `balanced` | Oracle type |
| `seed` | int | `7` | Seed for the random balanced function (-1 = random) |

Default shots: 2000

### `grover` — Grover search over marked basis states

Amplitude amplification: find marked items among N = 2^n in ~π/4·√(N/M) iterations.

*Hardware:* n ≥ 4 needs multi-controlled Z gates; expect rapid decoherence beyond n = 4–5 on hardware.

| parameter | type | default | description |
|---|---|---|---|
| `n` | int | `4` | Search qubits |
| `marked` | str | `1011` | Comma-separated marked bitstrings (MSB first) or 'random' |
| `iterations` | int | `-1` | Grover iterations (-1 = optimal) |
| `seed` | int | `5` | Seed for 'random' |

Default shots: 2000

### `grover_sat` — Grover SAT solver (reversible CNF oracle)

Builds a clause-by-clause reversible oracle for a CNF formula and amplifies satisfying assignments.

Each clause OR(l1..lk) is computed into an ancilla as NOT(AND(¬l_i)) with one multi-controlled X (mixed-polarity controls), the phase is applied when all clause ancillas are 1, then everything is uncomputed. The classical solution count is used only to choose the iteration number (it is reported, not hidden).

*Hardware:* variables + clauses qubits; deep for >3 variables on current hardware.

| parameter | type | default | description |
|---|---|---|---|
| `formula` | str | `(a \| b \| ~c) & (~a \| c) & (b \| ~d) & (~b \| ~c \| d)` | CNF formula |
| `iterations` | int | `-1` | Iterations (-1 = optimal from classical count) |

Default shots: 2000

### `simon` — Simon's algorithm: find the hidden period s

f(x) = f(x ⊕ s): each run yields y with y·s = 0; GF(2) post-processing recovers s.

Exponential query separation (vs. classical Θ(2^{n/2})). On noisy hardware we score every candidate s by the fraction of shots satisfying y·s = 0 and pick the best non-zero one.

*Hardware:* 2n qubits, ≤ 2n CX gates.

| parameter | type | default | description |
|---|---|---|---|
| `secret` | bits | `1011` | Hidden period s ≠ 0 (MSB first) |

Default shots: 2000

## Protocols

### `bb84` — Quantum key distribution (BB84 / BBM92) with an eavesdropper

Distil a secret key; an intercept-resend eavesdropper shows up as ~25 % QBER.

BB84: Alice prepares random bits in random Z/X bases (one shot per round); Bob measures in random bases. BBM92: Bell pairs, both parties measure in random bases (many shots). Eve intercepts a fraction of qubits in a random basis. Post-processing: sifting, QBER estimation on a public sample, abort above 11 %, simplified Cascade error correction, Toeplitz privacy amplification with the asymptotic BB84 rate 1 − 2h(QBER).

*Hardware:* BB84 uses shots=1 circuits (rounds × qubits); BBM92 uses fewer circuits with many shots.

| parameter | type | default | description |
|---|---|---|---|
| `protocol` | choice (bb84, bbm92) | `bb84` | Protocol |
| `qubits` | int | `12` | Qubits (BB84) or Bell pairs (BBM92) per circuit |
| `rounds` | int | `24` | Circuits |
| `eve` | float | `0.0` | Fraction of qubits intercepted by Eve |
| `pairs_shots` | int | `64` | Shots per circuit (BBM92 only) |
| `seed` | int | `2024` | Seed for Alice/Bob/Eve basis choices (-1 = random) |

Default shots: 1

### `e91_qkd` — E91 entanglement-based QKD with a Bell-test security certificate

Ekert's protocol: Alice and Bob build a shared key from entangled pairs, and a CHSH Bell test on the leftover rounds CERTIFIES no one is listening — security from physics, not assumptions.

Bell pairs are shared; Alice measures at angles {0°,45°,90°} and Bob at {45°,90°,135°}, chosen at random. Rounds where they picked the same angle (45° or 90°) are perfectly correlated and become the key. The remaining angle combinations feed a CHSH estimate: a genuine entangled channel gives S ≈ 2√2, but an intercept-resend eavesdropper breaks the entanglement and drags S toward 2 while injecting key errors. If S ≤ 2, the parties abort.

*Hardware:* 2 qubits per pair per circuit; many rounds. Shares the CHSH and BB84 machinery.

| parameter | type | default | description |
|---|---|---|---|
| `rounds` | int | `60` | Measurement rounds (circuits) |
| `pairs` | int | `4` | Entangled pairs per round |
| `eve` | float | `0.0` | Fraction of pairs an eavesdropper intercepts |
| `seed` | int | `91` | Seed for angle choices (-1 = random) |

Default shots: 1

### `qrng` — Quantum random number generator + randomness tests

Measure |+⟩ states, test the bits (NIST-style monobit/runs, χ²) and extract with Toeplitz hashing.

*Hardware:* 1 circuit; bits = qubits × shots. Hardware bias per qubit is visible in the table.

| parameter | type | default | description |
|---|---|---|---|
| `qubits` | int | `8` | Qubits measured in parallel |
| `extractor` | choice (none, von_neumann, toeplitz) | `toeplitz` | Randomness extractor |

Default shots: 1024

### `superdense` — Superdense coding: 2 classical bits in 1 qubit

Alice encodes 00/01/10/11 with I/X/Z/XZ on her half of a Bell pair; Bob decodes all 4.

*Hardware:* 4 circuits × 2 qubits.

Default shots: 2000

### `teleportation` — Quantum teleportation with state tomography

Teleport RY(θ)RZ(φ)|0⟩ from q0 to q2 and reconstruct it on Bob's side.

`dynamic` mode uses real mid-circuit measurements and classically-conditioned X/Z corrections (IBM dynamic circuits). `deferred` mode replaces them with controlled gates (principle of deferred measurement) for devices without feed-forward. Bob's qubit is measured in X, Y and Z to reconstruct its Bloch vector and the teleportation fidelity.

*Hardware:* 3 circuits × 3 qubits. Dynamic mode needs a backend with feed-forward (IBM Heron: yes).

| parameter | type | default | description |
|---|---|---|---|
| `theta` | float | `1.0` | Polar angle θ (rad) |
| `phi` | float | `0.7` | Azimuth φ (rad) |
| `mode` | choice (dynamic, deferred) | `dynamic` | Correction style |

Default shots: 2000

## Security

### `grover_key_search` — Grover key search: a quantum known-plaintext attack (toy cipher)

Encrypt a message with a secret key on a tiny toy cipher, then let Grover recover the key from known plaintext/ciphertext pairs — and see the quadratic speedup that halves symmetric-key strength.

A SYNTHETIC demonstration of why quantum computers worry symmetric cryptography. A small public toy cipher E_key encrypts chosen plaintext blocks under a secret key. Grover's algorithm searches the key space: a reversible oracle encrypts the known plaintext(s) under every candidate key in superposition, marks the key(s) that reproduce the known ciphertext(s), and amplitude amplification concentrates the measurement on the real key in ≈(π/4)√N steps instead of ≈N/2 classical trials. The report then extrapolates this √ speedup to real key lengths (why AES-128 has ~64-bit quantum security and AES-256 restores safety). It cannot attack any real cipher — the only secret is the one this experiment chose.

*Hardware:* key+block qubits (2×width) + one flag per pair. Deep for width>4 due to the S-box permutation; start on the simulator, then try width=3 on ibm:fake_fez.

| parameter | type | default | description |
|---|---|---|---|
| `width` | int | `4` | Key and block size in bits |
| `pairs` | int | `2` | Known plaintext/ciphertext pairs the attacker has |
| `rounds` | int | `3` | Toy-cipher rounds |
| `secret_key` | int | `-1` | Secret key to recover (-1 = pick one for you) |
| `iterations` | int | `-1` | Grover iterations (-1 = optimal for the solution count) |

Default shots: 2000

### `qday_estimator` — Q-Day resource estimator: is my encryption quantum-safe?

Factor 15 with Shor as a live proof the quantum attack is real, then estimate what breaking RSA/ECC would actually take — and whether 'harvest now, decrypt later' threatens your data.

The public-key counterpart to Grover key search. It runs a genuine Shor order-finding circuit to factor 15, then presents published resource estimates for breaking real RSA/ECC: logical and physical qubit counts and runtimes (Gidney–Ekerå 2019: ~20M physical qubits for RSA-2048; 2025 improvements: <1M). A 'harvest now, decrypt later' calculator flags whether data with a given secrecy lifetime is at risk before an estimated Q-Day, and a symmetric-key table shows Grover's gentler (quadratic) threat. The estimates are order-of-magnitude teaching figures from the cited literature, not predictions.

*Hardware:* Reuses the Shor N=15 circuit (12 qubits). The estimates themselves use no qubits.

| parameter | type | default | description |
|---|---|---|---|
| `rsa_bits` | int | `2048` | RSA modulus size to estimate (bits) |
| `secret_lifetime_years` | int | `15` | How long your data must stay secret |
| `q_day_year` | int | `2035` | Assumed year a cryptographically-relevant quantum computer arrives |
| `today_year` | int | `2026` | Current year (for the harvest-now-decrypt-later clock) |

Default shots: 2000

## Simulation

### `quantum_walk` — Discrete-time quantum walk on a line

A quantum walker spreads BALLISTICALLY (distance ∝ steps), quadratically faster than a classical random walk (distance ∝ √steps) — the engine behind several quantum algorithms.

A coined quantum walk: a coin qubit is flipped by a Hadamard each step, and the walker moves right or left on a position register depending on the coin, in superposition. Interference makes the probability spread much faster than a classical random walk. The report measures the standard deviation of position after T steps and compares it to the classical √T scaling.

*Hardware:* 1 coin + m position qubits (default 5 → 32 sites); the shift is a controlled increment/decrement.

| parameter | type | default | description |
|---|---|---|---|
| `position_qubits` | int | `5` | Position register size (2^m sites) |
| `steps` | int | `8` | Walk steps |
| `coin` | choice (symmetric, right, left) | `symmetric` | Initial coin state |

Default shots: 2000

### `tfim_dynamics` — Trotterized spin dynamics (quantum simulation)

Watch a quantum magnet evolve in real time: Trotterize e^{-iHt} for the transverse-field Ising model and track the magnetization, the task quantum computers are naturally suited to.

Simulating how a quantum system changes in time is the original motivation for quantum computers (Feynman). Here the transverse-field Ising chain H = −J Σ ZᵢZᵢ₊₁ − h Σ Xᵢ is evolved from the all-up state by Trotterization: each small time step applies the ZZ couplings (RZZ) then the transverse field (RX). The magnetization ⟨Σ Zᵢ⟩/n is measured over time and compared to the exact evolution, exposing Trotter error.

*Hardware:* n qubits (default 6); depth grows with Trotter steps — a core NISQ-era benchmark.

| parameter | type | default | description |
|---|---|---|---|
| `spins` | int | `6` | Spins (qubits) |
| `coupling` | float | `1.0` | Ising coupling J |
| `field` | float | `1.0` | Transverse field h |
| `total_time` | float | `3.0` | Total evolution time |
| `points` | int | `10` | Time points sampled |
| `trotter_steps` | int | `6` | Trotter steps per time point |

Default shots: 2000

## Variational

### `qaoa_maxcut` — QAOA for MaxCut

Optimise QAOA angles exactly, sample cuts on the backend, compare with brute force.

*Hardware:* Qubits = vertices; 2 CX per edge per layer after RZZ decomposition.

| parameter | type | default | description |
|---|---|---|---|
| `edges` | str | `0-1,1-2,2-3,3-0,0-2,3-4,4-1` | Graph edges a-b, comma separated |
| `p` | int | `2` | QAOA layers |

Default shots: 2000

### `vqe_h2` — VQE: ground-state energy of H₂

Optimise an ansatz classically, then measure ⟨H⟩ on the chosen backend (Z and X groups).

Two-qubit H₂ Hamiltonian (0.735 Å, STO-3G, parity-reduced). Parameters are optimised against an exact simulator (Nelder–Mead or SPSA), then the energy is *measured* on the backend from two commuting groups: {II, IZ, ZI, ZZ} in the Z basis and {XX} in the X basis. Combine with --mitigate-readout on hardware to approach chemical accuracy.

*Hardware:* 2 circuits × 2 qubits, ≤ 1 CX — excellent hardware demo.

| parameter | type | default | description |
|---|---|---|---|
| `ansatz` | choice (ucc1, hardware_efficient) | `ucc1` | Ansatz |
| `optimizer` | choice (nelder_mead, spsa) | `nelder_mead` | Optimiser |

Default shots: 8000
