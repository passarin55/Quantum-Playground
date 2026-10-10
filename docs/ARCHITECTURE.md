# Architecture

```
            ┌──────────── qplay CLI ────────────┐   ┌──── web studio (stdlib HTTP + SPA) ────┐
            └─────────────────┬─────────────────┘   └───────────────────┬────────────────────┘
                              ▼                                         ▼
                     ┌──────────────────────── runner.Runner ────────────────────────┐
                     │ plan → preflight → (readout calibration) → submit → store → analyse │
                     └───────┬──────────────────────┬──────────────────────┬─────────┘
                             ▼                      ▼                      ▼
                  experiments/ (plug-ins)     backends/ (registry)     backends/jobstore (SQLite)
                             │                      │
                             ▼                      ├─ local: statevector / density (core)
                        core/ IR + sims             ├─ aer[:fake_device]
                        enigma/ oracles             ├─ ibm[:device|least_busy|fake_*]  (SamplerV2)
                                                    └─ braket[:local|ARN]              (OpenQASM 3)
```

## Core (`quantum_playground.core`)

* **IR** (`circuit.py`): named quantum/classical registers; instructions carry qubits, params, clbits, an optional
  classical condition `((clbits…), value)` and an optional `ctrl_state` for mixed-polarity controls. Qubit 0 is
  the least-significant bit, matching Qiskit, so translation is 1:1. JSON round-trips losslessly (`qplay-circuit/1`).
* **Statevector** (`statevector.py`): gates act on strided views of the 2ⁿ tensor; permutation and diagonal gates
  have dedicated fast paths. Non-terminal measurements, resets and conditioned gates use *shot-batched branching*:
  each branch (state, shot count, classical bits) splits binomially at a measurement, so the number of branches is
  bounded by the shot count. Terminal measurements are deferred and sampled in one draw. `exact_distribution` does the
  same branching with probabilities for exact references.
* **Density matrix** (`density.py`): the 2n-axis tensor reuses the statevector kernels (ket half at offset n, bra
  half conjugated). Noise: 1q/2q depolarizing after gates, amplitude + phase damping from T1/T2 on `delay` (and on
  gates with `idle_noise`), readout flips. Presets: `heron_like`, `eagle_like`, `trapped_ion_like`, `noisy`.
* **Reversible simulator** (`reversible.py`): pushes all 2ⁿ basis states through X/CX/MCX/SWAP circuits at once
  to obtain truth tables; `permutation_of` also checks that ancilla/key qubits come back clean.
* **Synthesis** (`synthesis.py`): Gray-code transposition networks (v6–v8 method), bidirectional
  Miller–Maslov–Dueck transformation-based synthesis, BFS-optimal ≤2-bit networks; the cheapest by NCV cost is
  chosen, and every network is re-verified before use. A peephole pass cancels adjacent inverse pairs.
* **Mitigation** (`mitigation.py`): tensored assignment matrices from |0…0⟩/|1…1⟩ calibration circuits, inverse
  applied per bit, projection to the nearest probability vector (Smolin–Gambetta–Smith).

## Experiments

An `Experiment` declares typed `Param`s, `build()`s a `Plan` (circuits + JSON context + memory/shots needs) and
`analyze()`s results into a `Report` (summary, metrics, tables, charts, verdict). The context is stored with the job,
which is what makes cloud results analysable in a later session.

## Backends

All backends implement `run(circuits, shots, memory=…, confirm=…) -> Job` and `preflight()`. The IBM backend
transpiles with `generate_preset_pass_manager` for several seeds and keeps the one with the fewest native two-qubit
gates; preflight records native metrics, the measured physical qubits and an illustrative calibration error product,
then enforces caps. SamplerV2 results are parsed per classical-register name with per-shot bitstrings
(`qiskit_bridge.pub_to_result`).

## Readout mitigation across physical layouts

For IBM, the runner reads which physical qubit each classical bit was measured from in every transpiled circuit,
takes the union, and transpiles two calibration circuits with `initial_layout` pinned to exactly those physical
qubits. Mitigation then maps each experiment's clbits to the right per-qubit assignment matrix.

## Web studio security

Loopback bind by default, `Host` allow-list (DNS-rebinding defence), mandatory `X-QPlay` header on state-changing
requests (cross-site requests cannot add it without a CORS pre-flight, which is never granted), strict CSP, static
path containment, masked tokens in every response.
