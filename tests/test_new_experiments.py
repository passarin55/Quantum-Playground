"""Tests for the v9.1 practical experiments (security, optimization, chemistry/ML, dynamics, QEC, E91)."""
import itertools

import numpy as np
import pytest

from quantum_playground.experiments.security import toy_decrypt, toy_encrypt
from quantum_playground.runner import Runner


# --------------------------------------------------------------- security
def test_toy_cipher_round_trip():
    for width in (2, 3, 4):
        for key in range(1 << width):
            for pt in range(1 << width):
                ct = toy_encrypt(pt, key, width)
                assert toy_decrypt(ct, key, width) == pt


def test_grover_key_search_recovers_key():
    r = Runner()
    out = r.run("grover_key_search", {"width": 4, "pairs": 2, "secret_key": 11}, backend="local", seed=1)
    m = out.report["metrics"]
    assert m["recovered_ok"] and m["decrypt_ok"]
    assert m["recovered_key"] == 11 or m["consistent_keys"] > 1
    assert m["p_success"] > 0.8
    # the key-length cost table is present
    assert any("symmetric keys" in t["title"].lower() for t in out.report["tables"])


def test_grover_key_search_is_toy_scale():
    # two pairs pin the key; one pair may leave several — both must still "recover" a consistent key
    r = Runner()
    for pairs in (1, 2):
        out = r.run("grover_key_search", {"width": 3, "pairs": pairs}, backend="local", seed=2)
        assert out.report["metrics"]["recovered_ok"]


def test_qday_estimator_factors_15_and_flags_risk():
    r = Runner()
    out = r.run("qday_estimator", {"secret_lifetime_years": 30}, backend="local", seed=1)
    m = out.report["metrics"]
    assert set(m["factors"]) == {3, 5}
    assert m["harvest_now_decrypt_later_risk"] is True
    out2 = r.run("qday_estimator", {"secret_lifetime_years": 1, "q_day_year": 2060, "today_year": 2026},
                 backend="local", seed=1)
    assert out2.report["metrics"]["harvest_now_decrypt_later_risk"] is False


# --------------------------------------------------------------- optimization
def test_qaoa_portfolio_respects_budget():
    out = Runner().run("qaoa_portfolio", {"assets": 6, "budget": 3}, backend="local", seed=3)
    assert out.report["metrics"]["held"] == 3
    assert out.report["metrics"]["feasible"]


def test_qaoa_mis_finds_independent_set():
    out = Runner().run("qaoa_mis", {"edges": "0-1,1-2,2-3,3-4,4-0", "layers": 2}, backend="local", seed=3)
    m = out.report["metrics"]
    assert m["max_size"] == 2        # a 5-cycle has MIS size 2
    assert m["valid"]


# --------------------------------------------------------------- chemistry / ML
def test_vqe_ising_phases():
    r = Runner()
    ordered = r.run("vqe_ising", {"spins": 6, "field": 0.2}, backend="local", seed=1)
    disordered = r.run("vqe_ising", {"spins": 6, "field": 2.5}, backend="local", seed=1)
    assert ordered.report["metrics"]["order_parameter"] > 0.6
    assert disordered.report["metrics"]["order_parameter"] < 0.4
    assert abs(ordered.report["metrics"]["error"]) < 0.1 * abs(ordered.report["metrics"]["exact"])


def test_vqe_ising_exact_reference():
    from quantum_playground.experiments.applications import tfim_ground_energy
    # 2-spin TFIM ground energy: eigenvalues of -J ZZ - h(X0+X1)
    assert tfim_ground_energy(2, 1.0, 0.0) == pytest.approx(-1.0)
    assert tfim_ground_energy(1, 0.0, 1.0) == pytest.approx(-1.0)


def test_qkernel_beats_linear_on_nonlinear_data():
    out = Runner().run("qkernel", {"dataset": "circles", "train": 12, "test": 8, "seed": 1}, backend="local", seed=1)
    m = out.report["metrics"]
    assert m["quantum_accuracy"] >= m["classical_linear_accuracy"]
    assert m["quantum_accuracy"] >= 0.6


# --------------------------------------------------------------- dynamics / metrology
def test_tfim_dynamics_tracks_exact():
    out = Runner().run("tfim_dynamics", {"spins": 5, "trotter_steps": 8}, backend="local", seed=1)
    assert out.report["metrics"]["max_deviation"] < 0.1


def test_quantum_walk_is_ballistic():
    r = Runner()
    s8 = r.run("quantum_walk", {"steps": 8}, backend="local", seed=1).report["metrics"]
    s14 = r.run("quantum_walk", {"steps": 14}, backend="local", seed=1).report["metrics"]
    assert s8["std"] > s8["classical_std"]          # faster than classical √T
    assert s14["std"] > s8["std"]                   # keeps spreading


@pytest.mark.parametrize("n", [2, 4, 6])
def test_ghz_metrology_heisenberg_scaling(n):
    out = Runner().run("ghz_metrology", {"n": n}, backend="local", seed=1)
    assert out.report["metrics"]["frequency_gain"] == pytest.approx(n, abs=0.5)


# --------------------------------------------------------------- E91
def test_e91_secure_and_detects_eve():
    r = Runner()
    clean = r.run("e91_qkd", {"eve": 0.0, "rounds": 150, "pairs": 4}, backend="local", seed=5)
    assert clean.report["metrics"]["chsh_S"] > 2.3
    assert clean.report["metrics"]["qber"] < 0.05
    assert clean.report["metrics"]["secure"]
    spied = r.run("e91_qkd", {"eve": 1.0, "rounds": 150, "pairs": 4}, backend="local", seed=5)
    assert spied.report["metrics"]["chsh_S"] < 2.0
    assert spied.report["metrics"]["qber"] > 0.15


# --------------------------------------------------------------- Shor code
@pytest.mark.parametrize("logical", [0, 1])
@pytest.mark.parametrize("error", ["I", "X", "Y", "Z"])
def test_shor_code_corrects_every_single_qubit_error(logical, error):
    r = Runner()
    for q in range(9):
        out = r.run("shor_code", {"logical": logical, "error_type": error, "error_qubit": q, "correct": True},
                    backend="local", seed=1, shots=32)
        assert out.report["metrics"]["recovered_fraction"] > 0.99, (logical, error, q)


def test_shor_code_uncorrected_phase_error_corrupts_logical():
    out = Runner().run("shor_code", {"logical": 0, "error_type": "Z", "error_qubit": 0, "correct": False},
                       backend="local", seed=1, shots=64)
    assert out.report["metrics"]["recovered_fraction"] < 0.5
