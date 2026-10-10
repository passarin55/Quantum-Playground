import math

import numpy as np
import pytest

from quantum_playground.core import Circuit, unitary_matrix
from quantum_playground.experiments import REGISTRY, get_experiment, list_experiments
from quantum_playground.experiments.library import continued_fraction_candidates, fit_exponential, qft
from quantum_playground.experiments.variational import h2_exact
from quantum_playground.runner import Runner

EXPECT_WARN_ON_IDEAL = {"coherence"}   # an ideal simulator has no decoherence to measure


def test_registry_complete():
    ids = set(REGISTRY)
    assert len(ids) >= 21
    for e in list_experiments():
        assert e["title"] and e["category"] and e["summary"]


@pytest.mark.parametrize("exp_id", sorted(REGISTRY))
def test_every_experiment_passes_on_ideal_simulator(exp_id):
    out = Runner().run(exp_id, {}, backend="local", seed=11)
    assert out.status == "DONE", out.message
    assert out.report is not None, out.message
    expected = "warn" if exp_id in EXPECT_WARN_ON_IDEAL else "pass"
    assert out.report["verdict"] == expected, out.report_text


def test_param_validation():
    exp = get_experiment("grover")
    with pytest.raises(ValueError):
        exp.resolve({"n": 99})
    with pytest.raises(ValueError):
        exp.resolve({"nope": 1})
    assert exp.resolve({"n": "3"})["n"] == 3


def test_qft_matches_dft():
    n = 3
    qc = Circuit(n)
    qft(qc, list(range(n)))
    N = 1 << n
    dft = np.array([[np.exp(2j * np.pi * x * y / N) for x in range(N)] for y in range(N)]) / math.sqrt(N)
    np.testing.assert_allclose(unitary_matrix(qc), dft, atol=1e-10)
    inv = Circuit(n)
    qft(inv, list(range(n)), inverse=True)
    np.testing.assert_allclose(unitary_matrix(inv), dft.conj().T, atol=1e-10)


def test_shor_finds_factors_of_15_and_21():
    r = Runner()
    out = r.run("shor", {"N": 15, "a": 7}, backend="local", seed=1)
    assert out.report["metrics"]["factors"] == [3, 5]
    out = r.run("shor", {"N": 21, "a": 2, "t": 8}, backend="local", seed=1)
    assert set(out.report["metrics"]["factors"]) <= {3, 7} and out.report["metrics"]["factors"]


def test_shor_rejects_bad_inputs():
    with pytest.raises(ValueError):
        Runner().run("shor", {"N": 15, "a": 5}, backend="local")
    with pytest.raises(ValueError):
        Runner().run("shor", {"N": 17, "a": 3}, backend="local")


def test_continued_fractions():
    assert 4 in continued_fraction_candidates(64, 8, 15)


def test_vqe_reference_energy():
    assert h2_exact() == pytest.approx(-1.857275, abs=1e-5)


def test_chsh_violation_disappears_with_rotation():
    out = Runner().run("chsh", {"bob_offset_deg": 45}, backend="local", seed=1)
    assert abs(out.report["metrics"]["ideal_S"]) == pytest.approx(2.0, abs=1e-9)


def test_bb84_detects_eve():
    out = Runner().run("bb84", {"eve": 1.0, "rounds": 60}, backend="local", seed=1)
    assert out.report["metrics"]["qber"] > 0.11
    assert out.report["verdict"] == "warn"
    out = Runner().run("bb84", {"protocol": "bbm92", "rounds": 6, "eve": 0.0}, backend="local", seed=2)
    assert out.report["metrics"]["keys_agree"] is True


def test_enigma_grover_historical_recovers_message():
    out = Runner().run("enigma_grover", {"message": "ANGRIFFBEIMORGENGRAUEN", "secret_window": "QEC",
                                         "first": "A", "key_bits": 2, "crib_length": 2, "plugboard": "AB CD"},
                       backend="local", seed=1)
    assert out.report["metrics"]["recovered"] is True
    assert any("ANGRI FFBEI" in s for s in out.report["summary"])


def test_repetition_code_suppresses_errors():
    out = Runner().run("repetition_code", {"distance": 5, "p": 0.1}, backend="local", seed=3)
    m = out.report["metrics"]
    assert m["logical_error"] < m["unencoded_error"]
    out = Runner().run("repetition_code", {"distance": 3, "p": 0.1, "flip": "phase", "logical": 0},
                       backend="local", seed=3)
    assert out.report["metrics"]["logical_error"] < 0.1


def test_coherence_fit_on_noisy_simulator():
    out = Runner().run("coherence", {}, backend="local-noisy:heron_like", seed=5)
    assert out.report["metrics"]["T1_us"] == pytest.approx(180, rel=0.25)


def test_fit_exponential():
    t = np.linspace(0, 300, 12)
    T, A, B = fit_exponential(t, 0.9 * np.exp(-t / 120) + 0.05)
    assert T == pytest.approx(120, rel=0.02)
