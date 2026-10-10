from quantum_playground.cli.main import main


def test_cli_experiments_and_describe(capsys):
    assert main(["experiments"]) == 0
    assert "enigma_grover" in capsys.readouterr().out
    assert main(["describe", "shor"]) == 0
    assert "Parameters" in capsys.readouterr().out


def test_cli_run_and_jobs(capsys):
    assert main(["run", "bernstein_vazirani", "-p", "secret=1101", "--seed", "1"]) == 0
    out = capsys.readouterr().out
    assert "verdict: PASS" in out and "1101" in out
    assert main(["jobs", "list"]) == 0
    assert "bernstein_vazirani" in capsys.readouterr().out


def test_cli_circuit_formats(capsys):
    assert main(["circuit", "bell_states", "--format", "qasm3"]) == 0
    assert "OPENQASM 3.0" in capsys.readouterr().out
    assert main(["circuit", "grover", "-p", "n=3", "-p", "marked=101"]) == 0
    assert "q[0]" in capsys.readouterr().out


def test_cli_enigma(capsys):
    assert main(["enigma", "encode", "HELLO WORLD"]) == 0
    assert "ILBDA AMTAZ" in capsys.readouterr().out
    assert main(["enigma", "scan", "ILBDAAMTAZ", "--crib", "HELLOWORLD"]) == 0
    assert "AAA" in capsys.readouterr().out


def test_cli_real_qpu_requires_yes(capsys):
    # no tty in tests -> must refuse without --yes (and never touch the network)
    assert main(["run", "chsh", "-b", "ibm:ibm_fez"]) == 2
    assert "Not submitted" in capsys.readouterr().out


def test_cli_bad_param(capsys):
    assert main(["run", "grover", "-p", "n=99"]) == 1
