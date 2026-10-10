"""Materials & machine-learning experiments: VQE for a quantum magnet, and a quantum-kernel classifier."""
from __future__ import annotations

import math

import numpy as np

from ..core.circuit import Circuit
from ..core.statevector import Statevector
from ..optim import multistart, spsa
from .base import Chart, Experiment, Param, Plan, Report, Table, Tutor, counts_chart, register


# =============================================================================
def tfim_ground_energy(n: int, J: float, h: float) -> float:
    """Exact ground energy of H = -J Σ Z_i Z_{i+1} - h Σ X_i (open chain) by dense diagonalisation."""
    dim = 1 << n
    X = np.array([[0, 1], [1, 0]], float)
    Z = np.array([[1, 0], [0, -1]], float)
    H = np.zeros((dim, dim))

    def op(single, site):
        m = np.array([[1.0]])
        for s in range(n):
            m = np.kron(m, single if s == site else np.eye(2))
        return m

    for i in range(n - 1):
        H -= J * op(Z, i) @ op(Z, i + 1)
    for i in range(n):
        H -= h * op(X, i)
    return float(np.linalg.eigvalsh(H)[0])


def _tfim_ansatz(qc: Circuit, n: int, theta, layers: int) -> None:
    """Hardware-efficient ansatz respecting the chain: RY layer + linear CX entangler."""
    t = iter(theta)
    for q in range(n):
        qc.ry(next(t), q)
    for _ in range(layers):
        for q in range(n - 1):
            qc.cx(q, q + 1)
        for q in range(n):
            qc.ry(next(t), q)


def _tfim_nparams(n, layers):
    return n * (layers + 1)


@register
class VQEIsing(Experiment):
    id = "vqe_ising"
    title = "VQE: quantum magnet ground state & phase transition"
    category = "Chemistry & Materials"
    summary = ("Find the ground state of a transverse-field Ising spin chain with VQE, and sweep the field to watch a "
               "quantum phase transition — the kind of materials problem quantum computers target.")
    description = (
        "The transverse-field Ising model H = −J Σ ZᵢZᵢ₊₁ − h Σ Xᵢ is the textbook quantum magnet: at small field h "
        "the spins order (ferromagnet); at large h they align with the field (paramagnet), with a quantum phase "
        "transition between. VQE optimises a hardware-efficient ansatz to approximate the ground energy, measured on "
        "the backend from Z- and X-basis groups. The report compares to exact diagonalisation and reports the "
        "magnetisation order parameter.")
    hardware_notes = "n qubits (default 6), a linear CX entangler — a realistic condensed-matter demo on hardware."
    params = [Param("spins", "int", 6, "Number of spins (qubits)", 2, 12),
              Param("coupling", "float", 1.0, "Ising coupling J", 0, 5),
              Param("field", "float", 0.5, "Transverse field h (h≈J is near the transition)", 0, 5),
              Param("layers", "int", 2, "Ansatz entangling layers", 1, 4),
              Param("optimizer", "choice", "nelder_mead", "Optimiser", choices=["nelder_mead", "spsa"])]
    tutor = Tutor(
        concept="Simulating quantum materials is where quantum computers may help first, because the hardware is itself "
                "a quantum system. This finds the ground state of a quantum magnet and sees its phase transition.",
        how_it_works="A classical optimiser tunes a short circuit so the state it prepares minimises the magnet's "
                     "energy. The energy is measured on the device from commuting groups: ZZ couplings in the Z basis, "
                     "the transverse field in the X basis. Sweeping the field h moves the system through its phase transition.",
        intuition="At small field the spins lock together (order); at large field they follow the field (disorder). The "
                  "variational principle guarantees the trial energy is an upper bound on the true ground energy.",
        misconception="VQE is a heuristic hybrid loop, not exact: the answer depends on the ansatz and can hit local "
                      "minima. Classical methods still handle chains this small easily — the point is the method and its "
                      "scaling, not beating classical here.",
        what_to_look_for="VQE energy close to the exact diagonalisation value, and the magnetisation ⟨ZZ⟩ order "
                         "parameter: high at small h (ordered), low at large h (disordered).",
        try_this=["Sweep field from 0.2 (ordered) to 2.0 (disordered) and watch the magnetisation collapse near h≈J.",
                  "Switch optimizer to spsa for noisy backends.",
                  "Increase spins and ansatz layers and watch the energy error shrink."],
        real_world_use="Quantum simulation of magnetism, superconductors and catalysts is a leading near-term "
                       "application; the TFIM is the canonical benchmark model.",
        going_deeper="The Trotterized Ising dynamics experiment evolves the SAME Hamiltonian in time instead of finding "
                     "its ground state.",
        references=[{"title": "Transverse-field Ising model", "url": "https://en.wikipedia.org/wiki/Transverse-field_Ising_model"},
                    {"title": "VQE", "url": "https://en.wikipedia.org/wiki/Variational_quantum_eigensolver"}],
        prerequisites=["vqe_h2"],
    )

    def _optimise(self, p):
        n, J, h, L = p["spins"], p["coupling"], p["field"], p["layers"]
        dim = 1 << n

        def energy(theta):
            qc = Circuit(n)
            _tfim_ansatz(qc, n, theta, L)
            sv = Statevector.from_circuit(qc)
            e = 0.0
            for i in range(n - 1):
                e -= J * sv.expectation_pauli(_pauli_str(n, {i: "Z", i + 1: "Z"}))
            for i in range(n):
                e -= h * sv.expectation_pauli(_pauli_str(n, {i: "X"}))
            return e

        res = spsa(energy, [0.1] * _tfim_nparams(n, L), iterations=250) if p["optimizer"] == "spsa" \
            else multistart(energy, _tfim_nparams(n, L), starts=5, seed=4)
        return res

    def build(self, p):
        res = self._optimise(p)
        n, L = p["spins"], p["layers"]
        circuits = []
        for basis in ("Z", "X"):
            qc = Circuit(n, name=f"vqe_ising_{basis}")
            c = qc.add_creg("c", n)
            _tfim_ansatz(qc, n, res.x, L)
            if basis == "X":
                qc.h(list(range(n)))
            qc.measure(list(range(n)), c)
            circuits.append(qc)
        return Plan(circuits, {"theta": list(res.x), "opt_energy": res.fun})

    def analyze(self, p, ctx, results):
        n, J, h = p["spins"], p["coupling"], p["field"]
        rz, rx = results
        zz = sum(rz.expectation_parity([i, i + 1]) for i in range(n - 1))
        xx = sum(rx.expectation_parity([i]) for i in range(n))
        energy = -J * zz - h * xx
        exact = tfim_ground_energy(n, J, h)
        err = energy - exact
        order = abs(zz) / max(1, n - 1)       # magnetisation order parameter
        th = np.linspace(0.05, 3.0, 25)
        curve = [abs(_order_param(n, J, float(x))) for x in th]
        return Report(
            "VQE — transverse-field Ising magnet",
            [f"{n}-spin chain, J={J}, h={h}. VQE energy {energy:.4f} vs exact {exact:.4f} (error {err:.4f}).",
             f"Magnetisation order parameter ⟨ZZ⟩/(n−1) = {order:.3f} "
             f"({'ordered/ferromagnetic' if order > 0.5 else 'disordered/paramagnetic'}).",
             f"The phase-transition curve shows order collapsing near h ≈ J."],
            {"energy": energy, "exact": exact, "error": err, "order_parameter": order,
             "phase": "ordered" if order > 0.5 else "disordered"},
            [Table("Energy", ["quantity", "value"], [["VQE energy", round(energy, 5)], ["exact", round(exact, 5)],
                                                     ["error", round(err, 5)], ["optimiser energy", round(ctx["opt_energy"], 5)]])],
            [Chart("Order parameter vs transverse field", [f"{x:.2f}" for x in th],
                   {"⟨ZZ⟩ (exact ground state)": curve}, "line", "h / J", "order")],
            "pass" if abs(err) < 0.05 * max(1, abs(exact)) else "warn")


def _pauli_str(n, ops: dict) -> str:
    return "".join(ops.get(q, "I") for q in range(n - 1, -1, -1))


def _order_param(n, J, h) -> float:
    """Exact ⟨ZZ⟩/(n-1) nearest-neighbour correlation in the ground state."""
    X = np.array([[0, 1], [1, 0]], float)
    Z = np.array([[1, 0], [0, -1]], float)
    dim = 1 << n

    def op(single, site):
        m = np.array([[1.0]])
        for s in range(n):
            m = np.kron(m, single if s == site else np.eye(2))
        return m

    H = np.zeros((dim, dim))
    for i in range(n - 1):
        H -= J * op(Z, i) @ op(Z, i + 1)
    for i in range(n):
        H -= h * op(X, i)
    w, v = np.linalg.eigh(H)
    gs = v[:, 0]
    corr = sum(gs @ (op(Z, i) @ op(Z, i + 1)) @ gs for i in range(n - 1))
    return float(corr) / max(1, n - 1)


# =============================================================================
def _feature_map(x: np.ndarray, reps: int = 2) -> Circuit:
    """ZZ-feature-map-style embedding of a 2D point into a 2-qubit state."""
    n = len(x)
    qc = Circuit(n, name="feature_map")
    for _ in range(reps):
        for i in range(n):
            qc.h(i)
            qc.rz(2.0 * x[i], i)
        for i in range(n):
            for j in range(i + 1, n):
                qc.cx(i, j)
                qc.rz(2.0 * (math.pi - x[i]) * (math.pi - x[j]), j)
                qc.cx(i, j)
    return qc


def _overlap_circuit(xa: np.ndarray, xb: np.ndarray, reps: int) -> Circuit:
    """|⟨φ(xb)|φ(xa)⟩|² = P(all zeros) of U(xb)† U(xa)|0⟩."""
    fa = _feature_map(xa, reps)
    fb = _feature_map(xb, reps)
    qc = Circuit(len(xa), name="kernel_overlap")
    c = qc.add_creg("c", len(xa))
    qc.compose(fa)
    qc.compose(fb.inverse())
    qc.measure(list(range(len(xa))), c)
    return qc


@register
class QuantumKernel(Experiment):
    id = "qkernel"
    title = "Quantum-kernel classifier (machine learning)"
    category = "Machine Learning"
    summary = ("Embed data into quantum states, estimate a quantum kernel on the backend, and classify a 2D dataset — "
               "then compare the decision boundary to a classical kernel.")
    description = (
        "Quantum machine learning via kernels. Each 2D point is embedded by a feature-map circuit into a 2-qubit state; "
        "the kernel K(x,x') = |⟨φ(x')|φ(x)⟩|² is estimated on the backend by running U(x')†U(x) and measuring the "
        "all-zeros probability. A kernel classifier (nearest class by mean kernel) then labels test points. The report "
        "compares quantum-kernel accuracy to a classical RBF kernel on the same split.")
    hardware_notes = "2 qubits; one overlap circuit per (train,point) pair — many shallow circuits, ideal for batching."
    params = [Param("dataset", "choice", "circles", "Synthetic dataset", choices=["circles", "xor", "linear"]),
              Param("train", "int", 12, "Training points", 4, 16),
              Param("test", "int", 6, "Test points", 2, 12),
              Param("reps", "int", 2, "Feature-map repetitions (depth/expressibility)", 1, 4),
              Param("seed", "int", 1, "Dataset seed", 0, 2**31)]
    default_shots = 2048
    tutor = Tutor(
        concept="Quantum machine learning asks whether embedding data into quantum states lets us separate patterns a "
                "classical model finds hard. A quantum kernel measures similarity between data points via quantum-state "
                "overlaps.",
        how_it_works="A feature-map circuit turns each data point into a quantum state. The kernel between two points is "
                     "the overlap of their states, estimated by running one state-prep followed by the inverse of the "
                     "other and measuring how often you get all zeros. A classical algorithm then classifies using that "
                     "kernel.",
        intuition="The quantum computer isn't the whole model — it's a similarity (kernel) evaluator feeding a classical "
                  "classifier. The hope is that the quantum feature space makes some datasets linearly separable.",
        misconception="A quantum kernel is NOT automatically better: for many datasets a classical kernel matches or "
                      "beats it, and a provable advantage on real data is unproven. Expressive feature maps can even "
                      "hurt (kernel concentration). This shows the mechanism, not a guaranteed win.",
        what_to_look_for="Quantum-kernel test accuracy, compared to a classical RBF kernel on the same split. On the XOR "
                         "dataset the quantum kernel typically separates what a linear model cannot.",
        try_this=["Switch dataset between xor, circles and linear and compare quantum vs classical accuracy.",
                  "Change reps (feature-map depth) and watch accuracy change — more isn't always better.",
                  "Run on ibm:fake_fez to see shot noise in the kernel estimates."],
        real_world_use="Quantum kernels are explored for classification in finance, chemistry and high-energy physics; "
                       "they're one of the most studied near-term quantum-ML approaches.",
        going_deeper="The variational experiments (VQE, QAOA) use the same parameterised-circuit toolbox for a different goal.",
        references=[{"title": "Havlíček et al., Supervised learning with quantum feature spaces", "url": "https://arxiv.org/abs/1804.11326"},
                    {"title": "Qiskit Machine Learning", "url": "https://qiskit-community.github.io/qiskit-machine-learning/"}],
        prerequisites=["bell_states"],
    )

    def _data(self, p):
        rng = np.random.default_rng(p["seed"])
        n = p["train"] + p["test"]
        X = rng.uniform(0, math.pi, (n, 2))
        if p["dataset"] == "xor":
            y = ((X[:, 0] > math.pi / 2) ^ (X[:, 1] > math.pi / 2)).astype(int)
        elif p["dataset"] == "circles":
            r = np.hypot(X[:, 0] - math.pi / 2, X[:, 1] - math.pi / 2)
            y = (r < math.pi / 4).astype(int)
        else:
            y = (X[:, 0] + X[:, 1] > math.pi).astype(int)
        return X, y

    def build(self, p):
        X, y = self._data(p)
        tr, te = p["train"], p["test"]
        Xtr, Xte = X[:tr], X[tr:tr + te]
        ytr = y[:tr]
        circuits, pairs = [], []
        # train-train (upper triangle) and test-train overlaps
        for i in range(tr):
            for j in range(i + 1, tr):
                circuits.append(_overlap_circuit(Xtr[i], Xtr[j], p["reps"]))
                pairs.append(("tt", i, j))
        for i in range(te):
            for j in range(tr):
                circuits.append(_overlap_circuit(Xte[i], Xtr[j], p["reps"]))
                pairs.append(("et", i, j))
        return Plan(circuits, {"Xtr": Xtr.tolist(), "Xte": Xte.tolist(), "ytr": ytr.tolist(),
                               "yte": y[tr:tr + te].tolist(), "pairs": pairs})

    def analyze(self, p, ctx, results):
        tr, te = p["train"], p["test"]
        ytr = np.array(ctx["ytr"]); yte = np.array(ctx["yte"])
        Ktt = np.eye(tr); Ket = np.zeros((te, tr))
        for (kind, i, j), res in zip(ctx["pairs"], results):
            k = res.register("c").get("0" * p_qubits(res), 0) / res.shots
            if kind == "tt":
                Ktt[i, j] = Ktt[j, i] = k
            else:
                Ket[i, j] = k
        preds = _kernel_ridge_predict(Ktt, ytr, Ket)
        qacc = float((preds == yte).mean())
        Xtr, Xte = np.array(ctx["Xtr"]), np.array(ctx["Xte"])
        lin_acc = _classical_kernel_accuracy(Xtr, ytr, Xte, yte, kind="linear")
        rbf_acc = _classical_kernel_accuracy(Xtr, ytr, Xte, yte, kind="rbf")
        rows = [[f"test {i}", int(yte[i]), int(preds[i]), "✓" if preds[i] == yte[i] else "✗"] for i in range(te)]
        beats_linear = qacc > lin_acc + 1e-9
        return Report(
            "Quantum-kernel classifier",
            [f"Dataset '{p['dataset']}': {tr} train, {te} test points, depth-{p['reps']} feature map, kernel ridge classifier.",
             f"Quantum-kernel accuracy {qacc:.2f}; classical linear kernel {lin_acc:.2f}; classical RBF {rbf_acc:.2f}.",
             ("The quantum feature map separates what a LINEAR classifier cannot — the point of a feature map."
              if beats_linear else "Here the quantum kernel does not beat the linear baseline; feature maps don't always help.")],
            {"quantum_accuracy": qacc, "classical_linear_accuracy": lin_acc, "classical_rbf_accuracy": rbf_acc,
             "beats_linear": beats_linear, "train": tr, "test": te},
            [Table("Predictions", ["point", "true", "predicted", ""], rows),
             Table("Training kernel matrix (rounded)", [f"x{j}" for j in range(tr)],
                   [[round(Ktt[i, j], 2) for j in range(tr)] for i in range(tr)])],
            [Chart("Test accuracy", ["quantum kernel", "classical linear", "classical RBF"],
                   {"accuracy": [qacc, lin_acc, rbf_acc]})],
            "pass" if beats_linear or qacc >= 0.75 else "warn")


def p_qubits(res) -> int:
    for name, start, size in res.registers:
        if name == "c":
            return size
    return res.num_clbits


def _kernel_ridge_predict(Ktt, ytr, Ket, lam=1e-3) -> np.ndarray:
    """Kernel ridge regression classifier: α = (K + λI)^{-1} y, predict sign(K_test α)."""
    y = np.where(np.asarray(ytr) == 1, 1.0, -1.0)
    alpha = np.linalg.solve(Ktt + lam * np.eye(len(ytr)), y)
    scores = Ket @ alpha
    return (scores > 0).astype(int)


def _classical_kernel_accuracy(Xtr, ytr, Xte, yte, kind="rbf", gamma=1.0) -> float:
    if kind == "rbf":
        Ktt = np.exp(-gamma * ((Xtr[:, None, :] - Xtr[None, :, :]) ** 2).sum(-1))
        Ket = np.exp(-gamma * ((Xte[:, None, :] - Xtr[None, :, :]) ** 2).sum(-1))
    else:  # linear kernel (centred) — fails on XOR, the instructive baseline
        Xc = Xtr - Xtr.mean(0)
        Ktt = Xc @ Xc.T
        Ket = (Xte - Xtr.mean(0)) @ Xc.T
    preds = _kernel_ridge_predict(Ktt, ytr, Ket)
    return float((preds == yte).mean())
