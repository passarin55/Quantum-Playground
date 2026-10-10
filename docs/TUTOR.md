# Learning with Quantum Playground Studio

The studio is built to teach, not just to run circuits. Learning comes in two layers.

## 1. The curriculum (global tutor)

A guided path of 14 lessons from "what is a qubit" to real-world applications. Each lesson has a big idea, the
key intuition, the common misconception to unlearn, why it matters in the real world, and a concrete experiment to
run. Lessons are grouped by level: **foundations → algorithms → applications → hardware**.

```bash
qplay learn                     # list the curriculum
qplay learn grover              # read one lesson
qplay learn glossary            # 30+ plain-language definitions
qplay learn term:entanglement   # one glossary term
```

In the web studio, open the **Tutor** tab: the curriculum on the left, the lesson on the right (with an "Open the
experiment" button), and a filterable glossary below.

### Lessons

| level | lesson | run |
|---|---|---|
| foundations | Qubits and superposition | `qrng` |
| foundations | Measurement and the Bloch sphere | `custom` (Circuit Lab) |
| foundations | Gates, circuits and interference | `deutsch_jozsa` |
| foundations | Entanglement and Bell's theorem | `chsh` |
| foundations | Moving quantum information | `teleportation` |
| algorithms | Oracle algorithms and speedups | `simon` |
| algorithms | Grover search and amplitude amplification | `grover` |
| algorithms | Period finding: QFT, phase estimation and Shor | `shor` |
| algorithms | Variational algorithms for today's hardware | `vqe_h2` |
| applications | Quantum computing and cryptography | `grover_key_search` |
| applications | Optimization, finance and logistics | `qaoa_portfolio` |
| applications | Chemistry, materials and machine learning | `vqe_ising` |
| applications | Simulation, sensing and the quantum internet | `tfim_dynamics` |
| hardware | Real hardware: noise, coherence and error correction | `coherence` |

## 2. Per-experiment tutors

Every one of the 32 experiments carries its own mini-lesson: the idea, how the circuit works, the intuition, the
common misconception, what to look for in the report, concrete "try this" parameter experiments, the real-world use,
where to go deeper, and references.

```bash
qplay describe chsh --tutor     # describe + tutor
qplay learn exp:shor_code       # just the tutor
```

In the web studio, open any experiment in the **Experiments** tab and press **📘 Learn**.

## Suggested path

1. **Foundations** — run `qrng`, build a Bell state in the Circuit Lab, run `chsh`. Read each experiment's tutor as
   you go.
2. **Algorithms** — `deutsch_jozsa` → `grover` → `shor`. Watch interference and amplitude amplification at work.
3. **Applications** — pick what interests you: `grover_key_search` / `qday_estimator` (security),
   `qaoa_portfolio` (finance), `vqe_ising` / `qkernel` (materials & ML), `tfim_dynamics` / `ghz_metrology`
   (simulation & sensing).
4. **Hardware** — run `coherence` and `repetition_code` on `local-noisy:heron_like`, then `shor_code`, then rehearse
   anything on `ibm:fake_fez` before real hardware.

Everything the tutors describe is runnable on the local simulator, and every experiment reports a pass/warn/fail
verdict against an ideal reference so you can check your understanding against the physics.
