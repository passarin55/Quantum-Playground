import math
import warnings

import pytest

from quantum_playground import config
from quantum_playground.backends import available_backends, get_backend
from quantum_playground.backends.jobstore import JobStore
from quantum_playground.core import Circuit, exact_distribution, hellinger_fidelity
from quantum_playground.runner import Runner


def test_backend_specs():
    assert get_backend("local").name == "local"
    assert get_backend("local-noisy:noisy").name == "local-noisy:noisy"
    with pytest.raises(ValueError):
        get_backend("nonsense")
    assert any(b["spec"] == "ibm:fake_fez" for b in available_backends())


def test_jobstore_round_trip(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite")
    store.add("abc", "ibm", "ibm:ibm_fez", experiment="chsh", params={"x": 1}, context={"y": [1, 2]})
    store.update("abc", status="RUNNING")
    rec = store.get("abc")
    assert rec["params"] == {"x": 1} and rec["context"] == {"y": [1, 2]} and rec["status"] == "RUNNING"
    assert [r["job_id"] for r in store.list()] == ["abc"]
    assert store.delete("abc") and store.get("abc") is None


def test_runner_persists_and_reanalyzes():
    r = Runner()
    out = r.run("bell_states", {}, backend="local", seed=1)
    rec = r.store.get(out.job_id)
    assert rec["status"] == "DONE" and rec["report"]["verdict"] == "pass"
    again = r.reanalyze(out.job_id)
    assert again.report["metrics"]["fidelity"] == pytest.approx(out.report["metrics"]["fidelity"])
    # a fresh Runner (new "session") can still read it
    assert Runner().refresh(out.job_id).report["title"].startswith("Bell")


def test_readout_mitigation_improves_local_noisy():
    r = Runner()
    raw = r.run("bell_states", {}, backend="local-noisy:noisy", seed=4, shots=20000)
    mit = r.run("bell_states", {}, backend="local-noisy:noisy", seed=4, shots=20000, mitigate_readout=True)
    assert mit.report["metrics"]["fidelity"] > raw.report["metrics"]["fidelity"] + 0.05
    assert any("readout-error mitigation" in n for n in mit.report["notes"])


def test_credentials_never_leak_in_describe(monkeypatch):
    monkeypatch.setenv("QP_IBM_TOKEN", "SECRET-TOKEN-1234567890")
    creds = config.ibm_credentials()
    assert creds.source == "env:QP_IBM_TOKEN"
    assert "SECRET" not in str(creds.describe())
    config.set_session_ibm_credentials("SESSIONTOKEN-abcdef")
    assert config.ibm_credentials().source == "session"
    config.clear_session_ibm_credentials()


# ------------------------------------------------------------------ optional SDKs
def _teleport_like() -> Circuit:
    qc = Circuit(3)
    m = qc.add_creg("m", 2)
    o = qc.add_creg("out", 1)
    qc.ry(1.2, 0).h(1).cx(1, 2).cx(0, 1).h(0)
    qc.measure([0, 1], m)
    with qc.if_test(m[1], 1):
        qc.x(2)
    with qc.if_test(m[0], 1):
        qc.z(2)
    qc.measure(2, o[0])
    return qc


def test_qiskit_bridge_matches_unitary():
    pytest.importorskip("qiskit")
    from qiskit.quantum_info import Operator
    from quantum_playground.backends.qiskit_bridge import from_qiskit, to_qiskit
    from quantum_playground.core import unitary_matrix
    from test_core import random_circuit
    import numpy as np
    for seed in range(6):
        qc = random_circuit(4, 40, seed)
        np.testing.assert_allclose(Operator(to_qiskit(qc)).data, unitary_matrix(qc), atol=1e-9)
    back = from_qiskit(to_qiskit(random_circuit(3, 20, 1).remove_final_measurements()))
    assert back.num_qubits == 3


def test_aer_dynamic_circuit():
    pytest.importorskip("qiskit_aer")
    res = get_backend("aer", seed=3).run([_teleport_like()], shots=4000).results()[0]
    ideal = exact_distribution(_teleport_like())
    assert hellinger_fidelity(res.counts, ideal) > 0.99


@pytest.mark.ibm
def test_ibm_local_testing_mode_end_to_end():
    pytest.importorskip("qiskit_ibm_runtime")
    pytest.importorskip("qiskit_aer")
    warnings.filterwarnings("ignore")
    r = Runner()
    out = r.run("chsh", {}, backend="ibm:fake_fez", seed=1, shots=2000)
    assert out.status == "DONE"
    assert out.report["metrics"]["S"] > 2.3
    pf = out.preflight
    assert pf["settings"]["local_testing"] is True
    assert pf["circuits"][0]["two_qubit"] >= 1 and "measured_physical" in pf["circuits"][0]


@pytest.mark.ibm
def test_ibm_preflight_blocks_over_cap():
    pytest.importorskip("qiskit_ibm_runtime")
    pytest.importorskip("qiskit_aer")
    from quantum_playground.backends import SubmissionBlocked
    r = Runner()
    with pytest.raises(SubmissionBlocked):
        r.run("enigma_grover", {"synthesis": "staged"}, backend="ibm:fake_fez",
              ibm_options={"max_two_qubit": 50, "seeds": 1, "optimization_level": 1})


def test_ibm_real_device_requires_confirmation():
    pytest.importorskip("qiskit_ibm_runtime")
    be = get_backend("ibm:ibm_fez")
    with pytest.raises(PermissionError):
        be.run([Circuit(1, 1)], shots=10, confirm=False)


def test_braket_local_simulator():
    pytest.importorskip("braket")
    pytest.importorskip("qiskit")
    qc = Circuit(3, 2)
    qc.h(0).cx(0, 1).mcx([0, 1], 2).measure([0, 2], [0, 1])
    res = get_backend("braket:local").run([qc], shots=2000).results()[0]
    assert set(res.counts) <= {"00", "11"}
    with pytest.raises(RuntimeError):
        get_backend("braket:local").run([_teleport_like()], shots=10)
