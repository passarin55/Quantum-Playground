import math
import random

import numpy as np
import pytest

from quantum_playground.core import (Circuit, DensityMatrix, NoiseModel, ReadoutMitigator, Statevector,
                                     calibration_circuits, cancel_adjacent_inverses, density_distribution,
                                     exact_distribution, permutation_of, simulate, simulate_density,
                                     synthesize_permutation, to_qasm2, to_qasm3, truth_table, unitary_matrix)
from quantum_playground.core import gates as G
from quantum_playground.core.synthesis import apply_permutation, synth_bfs, synth_cycles, synth_mmd


def dense_reference(qc: Circuit) -> np.ndarray:
    """Independent dense-matrix construction (embeds each gate's full matrix)."""
    n = qc.num_qubits
    dim = 1 << n
    total = np.eye(dim, dtype=complex)
    for ins in qc.instructions:
        if ins.name in ("barrier", "measure"):
            continue
        m = G.full_matrix(ins.name, ins.params, len(ins.qubits), ins.ctrl_state)
        k = len(ins.qubits)
        full = np.zeros((dim, dim), dtype=complex)
        for col in range(dim):
            sub_in = sum(((col >> q) & 1) << j for j, q in enumerate(ins.qubits))
            rest = col
            for q in ins.qubits:
                rest &= ~(1 << q)
            for sub_out in range(1 << k):
                amp = m[sub_out, sub_in]
                if amp == 0:
                    continue
                row = rest
                for j, q in enumerate(ins.qubits):
                    row |= ((sub_out >> j) & 1) << q
                full[row, col] += amp
        total = full @ total
    return total


def random_circuit(n: int, depth: int, seed: int) -> Circuit:
    rng = random.Random(seed)
    qc = Circuit(n)
    one = ["x", "y", "z", "h", "s", "sdg", "t", "tdg", "sx", "sxdg"]
    rot = ["rx", "ry", "rz", "p"]
    for _ in range(depth):
        kind = rng.random()
        qs = rng.sample(range(n), min(n, 4))
        if kind < 0.3:
            qc.append(rng.choice(one), qs[:1])
        elif kind < 0.45:
            qc.append(rng.choice(rot), qs[:1], [rng.uniform(-3, 3)])
        elif kind < 0.5:
            qc.u(rng.uniform(-3, 3), rng.uniform(-3, 3), rng.uniform(-3, 3), qs[0])
        elif kind < 0.75 and n >= 2:
            g = rng.choice(["cx", "cy", "cz", "ch", "swap"])
            qc.append(g, qs[:2])
        elif kind < 0.85 and n >= 2:
            g = rng.choice(["cp", "crx", "cry", "crz", "rxx", "ryy", "rzz"])
            qc.append(g, qs[:2], [rng.uniform(-3, 3)])
        elif n >= 3:
            k = rng.randint(2, min(n - 1, 3))
            cs = qs[:k]
            choice = rng.random()
            if choice < 0.4:
                qc.mcx(cs, qs[k], ctrl_state=rng.randrange(1 << k))
            elif choice < 0.7:
                qc.mcp(rng.uniform(-3, 3), cs, qs[k], ctrl_state=rng.randrange(1 << k))
            else:
                qc.cswap(qs[0], qs[1], qs[2])
    return qc


@pytest.mark.parametrize("seed", range(12))
def test_statevector_matches_dense_reference(seed):
    qc = random_circuit(4, 40, seed)
    np.testing.assert_allclose(unitary_matrix(qc), dense_reference(qc), atol=1e-10)


def test_inverse_is_identity():
    qc = random_circuit(4, 60, 99)
    full = qc.copy()
    full.compose(qc.inverse())
    np.testing.assert_allclose(unitary_matrix(full), np.eye(16), atol=1e-10)


def test_bell_state_properties():
    qc = Circuit(2)
    qc.h(0).cx(0, 1)
    sv = Statevector.from_circuit(qc)
    assert sv.probabilities_dict() == pytest.approx({"00": 0.5, "11": 0.5})
    assert sv.expectation_pauli("ZZ") == pytest.approx(1)
    assert sv.expectation_pauli("XX") == pytest.approx(1)
    assert sv.expectation_pauli("YY") == pytest.approx(-1)
    assert sv.entanglement_entropy(0) == pytest.approx(1)
    assert sv.bloch_vector(0) == pytest.approx((0, 0, 0), abs=1e-12)


def test_bloch_vectors():
    qc = Circuit(1)
    qc.h(0).s(0)  # |+i>
    assert Statevector.from_circuit(qc).bloch_vector(0) == pytest.approx((0, 1, 0), abs=1e-12)
    qc = Circuit(1)
    qc.ry(math.pi / 3, 0)
    x, y, z = Statevector.from_circuit(qc).bloch_vector(0)
    assert (x, y, z) == pytest.approx((math.sin(math.pi / 3), 0, math.cos(math.pi / 3)), abs=1e-12)


def test_sampling_statistics_and_registers():
    qc = Circuit(3)
    a = qc.add_creg("a", 1)
    b = qc.add_creg("b", 2)
    qc.h(0).cx(0, 1).x(2)
    qc.measure(0, a[0])
    qc.measure([1, 2], b)
    res = simulate(qc, shots=4000, seed=1, memory=True)
    assert set(res.counts) <= {"100", "111"}  # b=(q2,q1) a=q0  -> "b1 b0 a0"
    assert res.register("b").keys() <= {"10", "11"}
    assert abs(res.counts.get("111", 0) / 4000 - 0.5) < 0.05
    assert len(res.memory) == 4000 and all(len(m) == 3 for m in res.memory)
    assert res.register_memory("a")[0] in ("0", "1")


def test_teleportation_with_feed_forward():
    theta, phi = 1.1, 0.7
    qc = Circuit(3)
    m = qc.add_creg("m", 2)
    out = qc.add_creg("out", 1)
    qc.ry(theta, 0).rz(phi, 0)
    qc.h(1).cx(1, 2)
    qc.cx(0, 1).h(0)
    qc.measure(0, m[0]).measure(1, m[1])
    with qc.if_test(m[1], 1):
        qc.x(2)
    with qc.if_test(m[0], 1):
        qc.z(2)
    qc.measure(2, out[0])
    dist = exact_distribution(qc)
    p1 = sum(p for k, p in dist.items() if k[0] == "1")
    assert p1 == pytest.approx(math.sin(theta / 2) ** 2, abs=1e-10)
    res = simulate(qc, shots=3000, seed=7)
    p1s = res.register("out").get("1", 0) / 3000
    assert abs(p1s - math.sin(theta / 2) ** 2) < 0.04


def test_reset_and_remeasure():
    qc = Circuit(1, 2)
    qc.h(0).measure(0, 0).reset(0).measure(0, 1)
    dist = exact_distribution(qc)
    assert dist == pytest.approx({"00": 0.5, "01": 0.5})


def test_density_matches_statevector_without_noise():
    qc = random_circuit(3, 30, 5)
    qc.add_creg("c", 3)
    qc.measure([0, 1, 2], [0, 1, 2])
    a = exact_distribution(qc)
    b = density_distribution(qc)
    for k in set(a) | set(b):
        assert a.get(k, 0) == pytest.approx(b.get(k, 0), abs=1e-9)


def test_density_noise_reduces_purity_and_readout():
    rho = DensityMatrix(1)
    rho.apply_gate("h", (0,))
    from quantum_playground.core.noise import depolarizing_kraus
    rho.apply_kraus(depolarizing_kraus(0.3), (0,))
    assert rho.purity() < 0.99
    assert rho.trace() == pytest.approx(1)
    qc = Circuit(1, 1)
    qc.measure(0, 0)
    dist = density_distribution(qc, NoiseModel(readout=(0.1, 0.2)))
    assert dist["1"] == pytest.approx(0.1)


def test_t1_decay_via_delay():
    t1 = 100e-6
    qc = Circuit(1, 1)
    qc.x(0).delay(t1, 0).measure(0, 0)
    dist = density_distribution(qc, NoiseModel(t1=t1, t2=t1))
    assert dist["1"] == pytest.approx(math.exp(-1), abs=1e-9)


def test_simulate_density_sampling():
    qc = Circuit(2, 2)
    qc.h(0).cx(0, 1).measure([0, 1], [0, 1])
    res = simulate_density(qc, 2000, NoiseModel.preset("noisy"), seed=3)
    assert res.shots == 2000
    assert res.counts.get("00", 0) + res.counts.get("11", 0) > 1500


@pytest.mark.parametrize("width", [2, 3, 4, 5])
def test_synthesizers_exact(width):
    rng = random.Random(width)
    for _ in range(6):
        perm = list(range(1 << width))
        rng.shuffle(perm)
        for fn in (synth_cycles, synth_mmd):
            gates = fn(perm)  # internally verified; re-verify through the IR
            qc = Circuit(width)
            from quantum_playground.core.synthesis import emit_network
            emit_network(qc, list(range(width)), gates)
            assert tuple(truth_table(qc)) == tuple(perm)
        if width <= 2:
            synth_bfs(perm)


def test_controlled_permutation_and_clean_ancilla():
    perm = [3, 0, 1, 2, 7, 4, 5, 6]
    qc = Circuit(5)  # q0 control, q1..q3 register, q4 untouched
    apply_permutation(qc, [1, 2, 3], perm, controls=[0])
    assert permutation_of(qc, [1, 2, 3], fixed=1) == tuple(perm)
    assert permutation_of(qc, [1, 2, 3], fixed=0) == tuple(range(8))
    # same with ctrl_state=0
    qc2 = Circuit(4)
    apply_permutation(qc2, [1, 2, 3], perm, controls=[0], ctrl_state=0)
    assert permutation_of(qc2, [1, 2, 3], fixed=0) == tuple(perm)


def test_mmd_beats_cycles_on_average():
    rng = random.Random(42)
    from quantum_playground.core.synthesis import network_cost
    tot_c = tot_m = 0
    for _ in range(10):
        perm = list(range(32))
        rng.shuffle(perm)
        tot_c += network_cost(synth_cycles(perm))
        tot_m += network_cost(synth_mmd(perm))
    assert tot_m < tot_c / 3


def test_peephole_cancellation():
    qc = Circuit(3)
    qc.h(0).x(1).cx(0, 1).cx(0, 1).x(1).t(2).tdg(2).rz(0.3, 0).rz(-0.3, 0).h(0)
    opt = cancel_adjacent_inverses(qc)
    assert opt.size() == 0
    np.testing.assert_allclose(unitary_matrix(opt), unitary_matrix(qc), atol=1e-12)


def test_phase_flip_on():
    for value in range(8):
        qc = Circuit(3)
        qc.phase_flip_on([0, 1, 2], value)
        u = unitary_matrix(qc)
        expect = np.eye(8)
        expect[value, value] = -1
        np.testing.assert_allclose(u, expect, atol=1e-12)


def test_serialisation_round_trip():
    qc = random_circuit(4, 30, 3)
    c = qc.add_creg("c", 2)
    qc.measure([0, 1], c)
    with qc.if_test(c[0], 1):
        qc.x(3)
    qc2 = Circuit.from_json(qc.to_json())
    assert qc2.to_dict() == qc.to_dict()


def test_qasm_exports():
    qc = Circuit(4, 2)
    qc.h(0).cx(0, 1).mcx([0, 1, 2], 3, ctrl_state=0b101).rzz(0.4, 0, 1).measure([0, 1], [0, 1])
    q3 = to_qasm3(qc)
    assert "negctrl" in q3 and "ctrl" in q3 and "c[0] = measure q[0];" in q3
    q2 = to_qasm2(qc)
    assert "c3x" in q2 and "measure q[0] -> c[0];" in q2
    braket = to_qasm3(qc, dialect="braket")
    assert "cnot" in braket and "zz(" in braket


def test_readout_mitigation_recovers_truth():
    noise = NoiseModel(readout=(0.05, 0.1))
    cals = calibration_circuits([0, 1], 2)
    r0 = simulate_density(cals[0], 200000, noise, seed=1)
    r1 = simulate_density(cals[1], 200000, noise, seed=2)
    mit = ReadoutMitigator.from_results([0, 1], r0, r1)
    qc = Circuit(2, 2)
    qc.h(0).cx(0, 1).measure([0, 1], [0, 1])
    noisy = simulate_density(qc, 200000, noise, seed=3)
    fixed = mit.apply(noisy.counts, [0, 1])
    assert fixed.get("00", 0) == pytest.approx(0.5, abs=0.01)
    assert fixed.get("11", 0) == pytest.approx(0.5, abs=0.01)
    assert fixed.get("01", 0) < 0.01


def test_depth_and_profile():
    qc = Circuit(3)
    qc.h(0).h(1).cx(0, 1).ccx(0, 1, 2)
    assert qc.depth() == 3
    prof = qc.gate_profile()
    assert prof["two_qubit"] == 1 and prof["multi_qubit"] == 1
    assert "X" in qc.draw()
