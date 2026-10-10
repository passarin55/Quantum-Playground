# IBM Quantum guide

## Credentials

The IBM Quantum Platform uses an **IBM Cloud API key** (channel `ibm_quantum_platform`). Resolution order:

1. session key set in the web studio or by `qplay ibm login` without `--save` (memory only),
2. `QP_IBM_TOKEN` (also `QISKIT_IBM_TOKEN`, `IBM_QUANTUM_TOKEN`) plus optional `QP_IBM_INSTANCE`,
3. `.env` in the working directory or in `$QP_HOME` (default `~/.qplay`) — both git-ignored patterns,
4. a Qiskit saved account (`qplay ibm login --save` → `QiskitRuntimeService.save_account`, file `~/.qiskit/qiskit-ibm.json`).

Never commit a key. If a key has been shared somewhere it should not have been (chat logs, screenshots, commits),
revoke it in the IBM Cloud console and create a new one.

```bash
qplay ibm login            # prompts for the key, lists devices
qplay ibm status           # shows where credentials come from (masked)
qplay ibm devices          # operational devices and queue lengths
qplay ibm usage            # plan usage
qplay backends --ibm
```

## Backend specs

| spec | meaning |
|---|---|
| `ibm` / `ibm:least_busy` | least busy operational device with enough qubits |
| `ibm:ibm_fez` (any name) | that device |
| `ibm:fake_fez`, `ibm:fake_marrakesh`, `ibm:fake_torino`, … | local testing mode: same transpile → SamplerV2 → parsing path on Aer with the fake device's calibration noise |
| `aer:fake_fez` | plain Aer with that noise model (no runtime primitives) |

## Workflow

```bash
qplay run ghz -p n=8 -b ibm:fake_fez                      # rehearse
qplay run ghz -p n=8 -b ibm:ibm_fez --dry-run --opt-level 3 --seeds 5
qplay run ghz -p n=8 -b ibm:ibm_fez --yes --dd --mitigate-readout
qplay jobs list
qplay jobs refresh <job-id>
```

### Options

| flag | effect |
|---|---|
| `--opt-level 0-3` | preset pass-manager optimisation level (default 2) |
| `--seeds N` | try N transpiler seeds (11, 23, 37, 41, 53) and keep the fewest native 2q gates |
| `--max-2q N` | per-circuit native two-qubit cap (default 3000) |
| `--override-caps` | submit anyway (warnings recorded in the job) |
| `--dd` | dynamical decoupling (`XpXm`) |
| `--twirl` | Pauli gate twirling + measurement twirling |
| `--batch` | Batch execution mode (several jobs scheduled together) |
| `--mitigate-readout` | adds two calibration circuits pinned to the measured physical qubits |

### Dynamic circuits

Teleportation (`-p mode=dynamic`) and the repetition code use mid-circuit measurement; teleportation also uses
classically-conditioned gates (`if_test`). Heron devices support both. Use `-p mode=deferred` elsewhere.

## Troubleshooting

* `InvalidAccountError: Unable to retrieve instances` — wrong key, wrong channel, or the network cannot reach
  `iam.cloud.ibm.com` / `quantum.cloud.ibm.com` (corporate proxies and sandboxes often block them).
* `Submission blocked by preflight` — the transpiled circuit exceeds a cap; inspect with `--dry-run`.
* Near-uniform results — compare the preflight error product; deep oracles (Enigma 26-letter, Shor) are expected
  to decohere on current devices. Start with the Mini-Enigma or CHSH.
