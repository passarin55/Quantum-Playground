import pytest

from quantum_playground.core import exact_distribution
from quantum_playground.enigma import (BitSource, Enigma, EnigmaConfig, build_grover_circuit, encrypt,
                                       generate_keysheet, historical_problem, keyed_encryption, letter_permutations,
                                       mini_encrypt, mini_problem, optimal_iterations, success_probability,
                                       verify_keyed_encryption, window_scan)
from quantum_playground.enigma.machine import parse_plugboard

# Public historical test messages.
BARBAROSSA_CT = ("EDPUDNRGYSZRCXNUYTPOMRMBOFKTBZREZKMLXLVEFGUEYSIOZVEQMIKUBPMMYLKLTTDEISMDICAGYKUACTCDOMOHWX"
                 "MUUIAUBSTSLRNBZSZWNRFXWFYSSXJZVIJHIDISHPRKLKAYUPADTXQSPINQMATLPIFSVKDASCTACDPBOPVHJK")
U534_CT = ("NCZWVUSXPNYMINHZXMQXSFWXWLKJAHSHNMCOCCAKUQPMKCSMHKSEINJUSBLKIOSXCKUBHMLLXCSJUSRRDVKOHULXWCCBGVL"
           "IYXEOAHXRHKKFVDREWEZLXOBAFGYUJQUKGRTVUKAMEURBVEKSUHHVOYHABCJWMAKLFKLMYFVNRIZRVVRTKOFDANJMOLBGFFLE"
           "OPRGTFLVRHOWOPBEKVWMUQFMPWPARMFHAGKXIIBG")


def test_reference_vectors():
    cfg = EnigmaConfig.create()
    assert encrypt("AAAAA", cfg) == "BDZGO"
    assert encrypt("HELLO WORLD", cfg) == "ILBDAAMTAZ"


def test_barbarossa_1941_m3():
    cfg = EnigmaConfig.create("II IV V", "B U L", "BLA", "B", "AV BS CG DL FU HZ IN KM OW RX")
    pt = encrypt(BARBAROSSA_CT, cfg)
    assert pt.startswith("AUFKLXABTEILUNGXVONXKURTINOWAXKURTINOWAXNORDWESTL")


def test_u534_m4():
    cfg = EnigmaConfig.create("BETA II IV I", "A A A V", "VJNA", "B-THIN", "AT BL DF GJ HM NW OP QY RZ VX")
    pt = encrypt(U534_CT, cfg)
    assert pt.startswith("VONVONJLOOKSJHFFTTTEINSEINSDREIZWOYYQNNSNEUNINHALT")
    assert pt.endswith("EINSNULL")


def test_involution_and_no_self_encryption():
    cfg = EnigmaConfig.create("IV I V", "5 12 22", "QEV", "C", "AQ BW EZ")
    msg = "THEQUICKBROWNFOXJUMPSOVERTHELAZYDOG" * 3
    ct = encrypt(msg, cfg)
    assert encrypt(ct, cfg) == msg
    assert all(a != b for a, b in zip(msg, ct))


def test_double_stepping():
    cfg = EnigmaConfig.create("I II III", "1 1 1", "ADU")
    e = Enigma(cfg)
    windows = []
    for _ in range(4):
        e.keypress("A")
        windows.append(e.window())
    assert windows == ["ADV", "AEW", "BFX", "BFY"]


def test_keypress_trace_matches_output():
    e = Enigma(EnigmaConfig.create(plugboard="HX"))
    tr = e.keypress_trace("H")
    assert tr["path"][-1]["letter"] == tr["output"]
    assert tr["path"][0]["stage"] == "plugboard" and tr["path"][0]["letter"] == "X"


def test_config_validation():
    with pytest.raises(ValueError):
        EnigmaConfig.create("I I III")
    with pytest.raises(ValueError):
        EnigmaConfig.create("BETA I II III", "1 1 1 1", "AAAA", "B")
    with pytest.raises(ValueError):
        parse_plugboard("AB BC")
    assert EnigmaConfig.create(rings="B U L").rings == (2, 21, 12)


def test_letter_permutations_are_fixed_point_free_involutions():
    for perm in letter_permutations(EnigmaConfig.create(plugboard="AB CD"), 30):
        assert all(perm[perm[i]] == i and perm[i] != i for i in range(26))


def test_window_scan_recovers_start():
    cfg = EnigmaConfig.create("III I II", "3 7 19", "QXR", "B", "AZ BY")
    ct = encrypt("WETTERVORHERSAGEBISKAYA", cfg)
    res = window_scan(cfg.with_positions("AAA"), ct, "WETTERVORHERSAGE")
    assert res["tested"] == 26 ** 3
    assert any(r["positions"] == "QXR" for r in res["results"])
    assert res["matches"] == 1


def test_mini_enigma_involution():
    for k in range(4):
        ct = mini_encrypt("ABCDDCBA", k)
        assert mini_encrypt(ct, k) == "ABCDDCBA"


@pytest.mark.parametrize("mode", ["compiled", "staged", "factored"])
def test_historical_oracle_exhaustive(mode):
    cfg = EnigmaConfig.create("II V III", "4 1 22", "KDU", "B", "AE FT")
    p = historical_problem(cfg, "HE", "QQ", key_bits=2, first="S")
    verify_keyed_encryption(p, mode)


def test_historical_oracle_across_notch_nonaffine():
    # right rotor III turns over at V: windows U..X straddle the notch -> non-affine shifts
    cfg = EnigmaConfig.create("I II III", "1 1 1", "ADU")
    p = historical_problem(cfg, "AB", "CD", key_bits=2, first="U")
    for mode in ("compiled", "staged", "factored"):
        verify_keyed_encryption(p, mode)


def test_m4_oracle():
    cfg = EnigmaConfig.create("GAMMA I II III", "1 1 1 1", "AAAA", "C-THIN")
    p = historical_problem(cfg, "Q", "Q", key_bits=1)
    verify_keyed_encryption(p, "compiled")
    verify_keyed_encryption(p, "factored")


def test_compact_oracle_is_tiny_and_hardware_runnable():
    # The genuine 26-letter oracle is ~10^5 two-qubit gates; the compact oracle marks the
    # classically-identified keys and compiles to a handful of gates, so it clears QPU caps.
    from quantum_playground.core import synthesize_permutation  # noqa: F401 (ensure package import)
    cfg = EnigmaConfig.create()
    secret = cfg.with_positions("AAC")
    p = historical_problem(cfg, "H", encrypt("H", secret), key_bits=2)
    compact = build_grover_circuit(p, synthesis="auto", oracle="compact")
    assert compact.num_qubits == p.key_bits                 # no symbol/flag registers at all
    assert compact.gate_profile()["two_qubit"] + compact.gate_profile()["multi_qubit"] < 20
    dist = exact_distribution(compact)
    assert dist["10"] == pytest.approx(1.0, abs=1e-9)        # still finds the key
    # vastly smaller than the genuine reversible oracle
    genuine = build_grover_circuit(p, synthesis="factored", oracle="phase")
    assert compact.size() * 50 < genuine.size()


@pytest.mark.parametrize("oracle", ["phase", "flag"])
def test_grover_finds_historical_key(oracle):
    cfg = EnigmaConfig.create()
    secret = cfg.with_positions("AAC")
    p = historical_problem(cfg, "H", encrypt("H", secret), key_bits=2)
    assert p.classical_matches() == [2]
    qc = build_grover_circuit(p, synthesis="compiled", oracle=oracle)
    dist = exact_distribution(qc)
    assert dist["10"] == pytest.approx(1.0, abs=1e-9)
    assert p.decode(2, encrypt("HELLO", secret)) == "HELLO"


def test_grover_two_letter_crib_three_bits():
    cfg = EnigmaConfig.create("I II III", "1 1 1", "AAA")
    secret = cfg.with_positions("AAF")
    p = historical_problem(cfg, "HI", encrypt("HI", secret), key_bits=3)
    sols = p.classical_matches()
    assert 5 in sols
    qc = build_grover_circuit(p, synthesis="compiled")
    dist = exact_distribution(qc)
    expected = success_probability(8, len(sols), optimal_iterations(8, 1))
    assert sum(dist.get(format(s, "03b"), 0) for s in sols) == pytest.approx(expected, abs=1e-9)


@pytest.mark.parametrize("synthesis", ["compiled", "staged"])
@pytest.mark.parametrize("oracle", ["phase", "flag"])
def test_mini_grover(synthesis, oracle):
    for key in range(4):
        p = mini_problem("AB", mini_encrypt("AB", key))
        qc = build_grover_circuit(p, synthesis=synthesis, oracle=oracle, iterations=1)
        dist = exact_distribution(qc)
        sols = p.classical_matches()
        assert key in sols
        assert sum(dist.get(format(s, "02b"), 0) for s in sols) > 0.99 or len(sols) > 1


def test_mini_direct_phase_is_small():
    p = mini_problem("A", "C")
    qc = build_grover_circuit(p, synthesis="compiled", oracle="phase", iterations=1)
    assert qc.num_qubits == 4
    assert qc.size() < 60   # v8 fully staged direct-phase: 178 raw instructions


def test_keysheet_uses_quantum_bits_and_is_valid():
    bits = [int(b) for b in "1011001110001111000010110101" * 40]
    src = BitSource(bits, fallback=True)
    sheet = generate_keysheet(5, src)
    assert src.used_quantum > 0
    for day in sheet.days:
        EnigmaConfig.create(" ".join(day["rotors"]), day["rings"], day["positions"], "B", " ".join(day["plugboard"]))
        assert len(day["plugboard"]) == 10
    assert "Walzenlage" in sheet.to_text()
    with pytest.raises(RuntimeError):
        generate_keysheet(1, BitSource([1, 0], fallback=False))
