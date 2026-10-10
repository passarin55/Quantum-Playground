# Enigma lab

## Machines

* **Enigma I / M3** — rotors I–VIII, reflectors A/B/C, ring settings, plugboard (up to 13 pairs), ratchet stepping
  including the middle-rotor double step.
* **M4** — Greek rotor BETA/GAMMA (never steps) with thin reflectors B-THIN/C-THIN.
* **Mini-Enigma** — four-letter alphabet ABCD, three rotors, reflector and double stepping, designed for small QPUs.

Validation (tests/test_enigma.py): `AAAAA → BDZGO`, `HELLOWORLD → ILBDAAMTAZ`, the 1941 *Operation Barbarossa*
M3 message (II IV V, rings BUL, plugboard AV BS CG DL FU HZ IN KM OW RX, start BLA) and the *U-534* M4 message
(BETA II IV I, rings AAAV, B-THIN, start VJNA) decrypt to the published German plaintexts.

```bash
qplay enigma encode "HELLO WORLD"
qplay enigma trace "HI" --plugboard "HX"          # signal path through every stage
qplay enigma scan ILBDAAMTAZ --crib HELLOWORLD     # all 17 576 start windows, other settings known
qplay enigma keysheet --days 31
```

## Quantum key search

The unknown is one rotor's start window among 2^b candidates (b = 1–4; Mini-Enigma: 4 candidates). A b-qubit key
register is put in uniform superposition; each crib letter gets a 5-qubit symbol register (2 for Mini).

### Oracle

Direct-phase (v8 idea): load the known plaintext letters, apply the key-controlled Enigma permutation to each symbol
register, phase-flip when *all* registers equal the known ciphertext letters (one multi-controlled Z), then
uncompute. The legacy flag oracle (compute/compare/uncompute into flag qubits) is kept for comparison.

### Synthesis strategies

| strategy | idea | keyed parts |
|---|---|---|
| `staged` | plugboard, each rotor, reflector, inverse rotors as separate permutations | stages that differ between candidates |
| `factored` | v7 algebra: `S(r) W_R S(m−r) W_M …` — wirings unkeyed, merged modular shifts keyed with affine one-bit controls | shifts only |
| `compiled` | whole keypress permutation per candidate | everything (base + controlled corrections) |
| `auto` | smallest decomposition-aware cost (NCV model) | |

### Oracle modes

| oracle | what it does | runs on hardware? |
|---|---|---|
| `phase` | v8 direct-phase: encrypt all crib letters on quantum data, one collective phase, uncompute | mini only |
| `flag` | compute/compare/uncompute into per-letter flag qubits (v6/v7 style) | mini only |
| `compact` | **classical crib check, phase-mark the matching keys** — a handful of gates | **yes, any backend** |

The genuine reversible oracle (`phase`/`flag`) encrypts in superposition and is the honest "no lookup table"
construction — but for 26 letters it compiles to ~10⁵ native two-qubit gates, far beyond any real QPU (the preflight
blocks it). The `compact` oracle is the only way to run the 26-letter search on real hardware: it does the crib check
classically and uses Grover purely to *amplify* the keys already found, so it is tiny (≈2 two-qubit gates for a
2-qubit key) and clearly provides **no quantum speedup** over the classical scan. It exists to demonstrate amplitude
amplification itself on a QPU.

```bash
# The 26-letter genuine oracle is blocked on hardware (honest resource wall):
qplay run enigma_grover -p secret_window=AAC -b ibm:ibm_marrakesh --dry-run         # BLOCKED: ~10^5 native 2q gates
# The compact oracle runs the same key search on hardware (no speedup claimed):
qplay run enigma_grover -p secret_window=AAC -p oracle=compact -b ibm:ibm_marrakesh --dry-run   # OK: ~2 native 2q gates
qplay run enigma_grover -p secret_window=AAC -p oracle=compact -b ibm:ibm_marrakesh --yes
```

All strategies act on **all 32 basis states** of the symbol register (codes 26–31 are fixed points), never on a
table of crib answers, and `verify_keyed_encryption` checks every key × every input exhaustively.

### Resource reality (1 Grover iteration, transpiled for `fake_fez`, optimisation level 3)

| problem | strategy / oracle | qubits | raw ops | native 2q | depth |
|---|---|---:|---:|---:|---:|
| Mini A→C | compiled / phase | 4 | 24 | 98 | 336 |
| Mini A→C | staged / phase | 4 | 72 | 515 | 1 999 |
| Mini A→C | staged / flag | 5 | 134 | 990 | 3 677 |
| 26-letter H, 2 key bits | factored / phase | 7 | 1 022 | 26 273 | 73 834 |
| 26-letter H, 2 key bits | compiled / phase | 7 | 456 | 29 754 | 78 602 |
| 26-letter H, 2 key bits | staged / phase | 7 | 1 366 | 71 684 | 189 771 |

For comparison, the v8 notes recorded 8 469 CZ for a v7 staged Mini-Enigma circuit on `ibm_fez`. The Mini
direct-phase compiled oracle is the realistic hardware demo; the 26-letter oracle is a correctness and
resource-estimation exercise.

```bash
qplay run enigma_grover -p model=mini -p message=ABCDDCBA -p secret_window=2 -b ibm:fake_fez
qplay run enigma_grover -p message=ANGRIFFBEIMORGENGRAUEN -p secret_window=QEC -p crib_length=2
qplay run enigma_grover -b ibm:ibm_fez --dry-run          # see why the 26-letter oracle is not hardware-ready
```

## Quantum-random key sheets

`qplay run enigma_keysheet -b ibm:ibm_fez --yes` measures |+⟩ states, feeds the bits through rejection sampling
(no modulo bias) into rotor order, rings, plugboard and start windows, and reports how many bits were quantum vs.
CSPRNG fallback.
