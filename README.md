# Quantum Playground Studio v9

An over-engineered quantum computing lab that runs on your laptop and on real cloud quantum computers.
It is a ground-up redesign of *Quantum Playground Studio v8 — Direct-Phase Enigma* (a Windows-only PySide6 desktop app),
rebuilt as a tested Python package with a CLI, a local web studio and one execution pipeline for every backend.

| | |
|---|---|
| **Engine** | Own circuit IR · vectorised statevector simulator with mid-circuit measurement and feed-forward · density-matrix simulator with T1/T2, depolarizing and readout noise · exhaustive reversible-logic simulator · MMD permutation synthesis · OpenQASM 2/3 export |
| **Experiments** | 21 self-checking experiments: CHSH, Bell fidelity, GHZ, teleportation (dynamic circuits), superdense coding, BB84/BBM92 QKD with an eavesdropper, QRNG, Deutsch–Jozsa, Bernstein–Vazirani, Simon, Grover, Grover-SAT, QFT, phase estimation, Shor, VQE (H₂), QAOA MaxCut, repetition code, T1/Ramsey coherence, Enigma Grover key search, quantum-random Enigma key sheet |
| **Enigma lab** | Historical Enigma I / M3 / M4 (validated against the 1941 *Barbarossa* and *U-534* messages), Mini-Enigma, vectorised crib scan, key-sheet generator, reversible Grover oracles in three synthesis strategies |
| **Backends** | `local`, `local-noisy:<preset>`, Qiskit Aer, **IBM Quantum** (SamplerV2, real devices), **IBM local testing mode** on calibrated fake devices, **Amazon Braket** (local simulator or managed devices) |
| **Operations** | Multi-seed transpilation, preflight with native two-qubit caps, explicit real-QPU confirmation, dynamical decoupling / twirling switches, tensored readout mitigation pinned to physical qubits, persistent SQLite job store with re-analysis across sessions |
| **Interfaces** | `qplay` CLI · zero-dependency web studio (`qplay serve`) · Python API |

---

## Install

Python 3.10+.

```bash
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[all]"          # numpy + qiskit + qiskit-aer + qiskit-ibm-runtime + pytest
# minimal (local simulators only):   pip install -e .
# AWS Braket support:                pip install -e ".[braket]"
```

Windows users can double-click `scripts/windows/INSTALL.bat` and then `scripts/windows/RUN_STUDIO.bat`.
On macOS/Linux: `scripts/install.sh` and `scripts/run_studio.sh`.

## Thirty-second tour

```bash
qplay experiments                                  # list everything
qplay run chsh                                     # exact simulation
qplay run chsh -b local-noisy:heron_like           # density-matrix noise model
qplay run chsh -b ibm:fake_fez                     # identical IBM pipeline, offline, with ibm_fez calibration noise
qplay run shor -p N=21 -p a=2                      # factor 21
qplay run enigma_grover -p message="WETTERBERICHT" -p secret_window=AAC
qplay enigma encode "HELLO WORLD" --rotors "I II III" --positions AAA      # -> ILBDA AMTAZ
qplay serve --open                                 # web studio on http://127.0.0.1:8765
```

## Using IBM Quantum

1. Create an API key at <https://quantum.cloud.ibm.com> (IBM Cloud API key; the Open plan includes free monthly QPU time).
2. Give it to the program **without putting it in the repository** — any of:
   * `qplay ibm login` (prompts for the key; add `--save` to store it in Qiskit's own `~/.qiskit` account file),
   * environment variable `QP_IBM_TOKEN` (optionally `QP_IBM_INSTANCE` with your instance CRN),
   * a `.env` file copied from `.env.example` (git-ignored),
   * the **IBM & Cloud** tab of the web studio ("use for this session" keeps it in memory only).
3. Rehearse offline, inspect the native circuit, then submit:

```bash
qplay run vqe_h2 -b ibm:fake_fez --mitigate-readout     # offline rehearsal with real calibration noise
qplay run vqe_h2 -b ibm:ibm_fez --dry-run               # transpile + preflight: native 2q gates, depth, error product
qplay run vqe_h2 -b ibm:ibm_fez --mitigate-readout --yes
qplay jobs refresh <job-id>                             # results are analysed automatically, even days later
```

Real-QPU submissions always require `--yes` (or the "confirm real QPU" checkbox), and circuits whose
transpiled native two-qubit count exceeds the cap (default 3 000) are blocked unless you pass `--override-caps`.
See [docs/IBM_QUANTUM.md](docs/IBM_QUANTUM.md) for transpiler options, error suppression and troubleshooting.

## What the IBM device models predict

Measured in this repository's test environment on the `ibm:fake_fez` local testing backend (156-qubit Heron r2 model,
calibration noise, opt. level 2–3) — these are simulations, not hardware runs:

| Experiment | Native 2q gates | Result |
|---|---:|---|
| CHSH | 1 per circuit | S = 2.80 ± 0.03 (25 σ violation; ideal 2.83) |
| Teleportation, dynamic circuit | 2 | fidelity 0.98 |
| VQE H₂ + readout mitigation | 1 | E = −1.8511 Ha (exact −1.8573; 6.2 mHa off, within 3σ of shot noise at 8 000 shots) |
| Mini-Enigma Grover, direct-phase oracle | 98 | correct key 73 % of shots (random 25 %) |
| Shor N = 15, a = 7 | 457 | 44 % of shots yield 3 × 5 (ideal 50 %) |
| 26-letter Enigma Grover, 2 key bits | 26 273 (factored) | not runnable on today's hardware (error product ≈ 10⁻³⁷) |

## Architecture

```
src/quantum_playground/
  core/         circuit IR, statevector / density / reversible simulators, synthesis, noise, QASM, mitigation
  enigma/       machine models, classical crib scan + key sheets, reversible Grover oracles
  backends/     local, Aer, IBM Runtime, Braket, Qiskit bridge, SQLite job store
  experiments/  plug-in experiments (build circuits -> analyse results -> Report)
  runner.py     one pipeline: plan -> preflight -> (mitigation) -> submit -> store -> analyse
  cli/          `qplay`
  web/          stdlib HTTP server + vanilla-JS single-page studio (no CDN, works offline)
```

Details in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md); every experiment is documented in
[docs/EXPERIMENTS.md](docs/EXPERIMENTS.md); the Enigma work in [docs/ENIGMA.md](docs/ENIGMA.md).

## What changed versus v8

* **Platform**: Windows-only Qt GUI → cross-platform package + CLI + browser studio; no PySide6/matplotlib dependency.
* **Simulators**: per-amplitude Python loops → vectorised kernels; added density matrices, noise presets, T1/T2,
  dynamic circuits (mid-circuit measurement, reset, feed-forward), exact outcome distributions.
* **Enigma oracles**: reimplemented on a backend-neutral IR and verified *exhaustively* (every key × all 32 symbol
  states); Gray-code synthesis replaced by bidirectional Miller–Maslov–Dueck synthesis (~7× lower NCV cost on random
  5-bit permutations); new *compiled* strategy and decomposition-aware automatic choice. Mini-Enigma direct-phase
  Grover: 178 → 24 raw instructions; 26-letter one-letter oracle: ~35 000 → 456 raw instructions.
* **Machines**: M4 with Greek rotors and thin reflectors; validated against two historical messages.
* **IBM**: the job context is persisted, so a job from a previous session is decoded and analysed (v5–v8 could not);
  DataBin parsing by register name with per-shot memory (the v4.1/v4.2 `meas` bug class is gone); local testing mode;
  readout mitigation pinned to the physical qubits actually measured.
* **Breadth**: 21 experiments instead of a handful of demos, each with a pass/warn/fail verdict and ideal reference.
* **Quality**: 116 pytest tests (core numerics against an independent dense-matrix reference, Qiskit operator
  equivalence, IBM fake-device end-to-end, Braket, web API security guards), GitHub Actions CI.

## Honest boundaries (kept from v5–v8, and still true)

* The Grover Enigma search is a *restricted, educational* key search over 2–16 candidates. A classical scan of all
  17 576 start windows takes milliseconds; no speed-up is claimed and the 26-letter oracle is far beyond present
  hardware.
* The ideal simulators show amplitudes no real QPU exposes; hardware results are statistics from repeated shots.
* The calibration "error product" in preflight assumes independent errors — an illustration, not a fidelity forecast.
* No real IBM hardware job was run while building this release (the build sandbox had no network route to IBM);
  every IBM code path was exercised with qiskit-ibm-runtime's local testing mode on calibrated fake devices.

## Tests

```bash
pip install -e ".[all]"
pytest            # ~2 minutes; tests that need optional SDKs skip automatically when they are missing
```
