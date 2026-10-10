# Changelog

## 9.0.0 — complete redesign

Rebuilt from *Quantum Playground Studio v8 — Direct-Phase Enigma* (Windows/PySide6) as a cross-platform package.

### Added
- Backend-neutral circuit IR with JSON serialisation, OpenQASM 2/3 export (incl. Braket dialect) and a text drawer.
- Vectorised statevector simulator with mid-circuit measurement, reset and classical feed-forward (shot-batched branching).
- Density-matrix simulator with depolarizing, T1/T2 relaxation (on `delay`) and readout noise; four presets.
- Exhaustive reversible-logic simulator; bidirectional Miller–Maslov–Dueck permutation synthesis; peephole optimiser.
- Tensored readout-error mitigation, pinned to the physical qubits each IBM circuit actually measured.
- Backends: local, local-noisy, Qiskit Aer (ideal / fake-device noise), IBM Quantum SamplerV2 (devices, least busy,
  local testing mode on fake devices), Amazon Braket (local simulator / managed devices).
- Multi-seed transpilation, preflight with native two-qubit/depth/shot caps, explicit real-QPU confirmation,
  dynamical decoupling and twirling switches, batch mode.
- Persistent SQLite job store; results from previous sessions are re-analysed automatically.
- 21 experiments (+ custom circuits): CHSH, Bell fidelity, GHZ parity, teleportation (dynamic/deferred),
  superdense coding, BB84/BBM92 with eavesdropper + Cascade-style correction + Toeplitz privacy amplification,
  QRNG with statistical tests and extractors, Deutsch–Jozsa, Bernstein–Vazirani, Simon, Grover, Grover-SAT, QFT,
  QPE, Shor (exact modular multipliers), VQE H₂, QAOA MaxCut, repetition code, T1/Ramsey, Enigma Grover,
  quantum-random Enigma key sheet.
- Enigma M4 (Greek rotors, thin reflectors); validation against the Barbarossa (1941) and U-534 messages;
  numpy-vectorised start-window scan; key-sheet generator with bias-free rejection sampling.
- Enigma Grover oracles on the IR in three strategies (staged, factored, compiled) with exhaustive verification and
  decomposition-aware automatic selection.
- `qplay` CLI and a zero-dependency local web studio (composer with live amplitudes/Bloch spheres, experiment
  runner, interactive Enigma with lampboard and signal path, job monitor, IBM settings).
- pytest suite and GitHub Actions CI.

### Changed
- Mini-Enigma direct-phase Grover circuit: 178 → 24 raw instructions (98 native two-qubit gates on `fake_fez`).
- 26-letter one-letter oracle: ~35 000 → 456 raw instructions (compiled) / 1 022 (factored).

### Kept
- The direct-phase oracle architecture and its honest-scope statements from v8, the register-name-independent
  SamplerV2 parsing introduced in v4.2, and the classical full-window scan baseline.
