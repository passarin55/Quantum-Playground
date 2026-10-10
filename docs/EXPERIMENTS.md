# Experiments

Generated from the registry (`python scripts/gen_experiment_docs.py`). Run any of them with
`qplay run <id> [-p name=value ...] [-b backend]`; every report carries a pass/warn/fail verdict.

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
