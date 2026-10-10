import json
import threading
import urllib.error
import urllib.request

import pytest

from quantum_playground.web.server import make_server


@pytest.fixture()
def server():
    srv = make_server("127.0.0.1", 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def call(base, method, path, body=None, headers=None):
    h = {"X-QPlay": "1", "Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(base + path, method=method, headers=h,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_static_and_info(server):
    with urllib.request.urlopen(server + "/") as r:
        html = r.read().decode()
        assert "Quantum Playground" in html
        assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    code, info = call(server, "GET", "/api/info")
    assert code == 200 and info["experiments"] >= 21


def test_csrf_and_host_guards(server):
    code, _ = call(server, "POST", "/api/run", {"experiment": "chsh"}, headers={"X-QPlay": "0"})
    assert code == 403
    code, _ = call(server, "GET", "/api/info", headers={"Host": "attacker.example"})
    assert code == 403
    with pytest.raises(urllib.error.HTTPError):
        urllib.request.urlopen(server + "/../../etc/passwd")


def test_run_and_jobs(server):
    code, out = call(server, "POST", "/api/run", {"experiment": "bell_states", "backend": "local", "seed": 1})
    assert code == 200 and out["report"]["verdict"] == "pass"
    code, jobs = call(server, "GET", "/api/jobs")
    assert any(j["job_id"] == out["job_id"] for j in jobs["jobs"])
    code, job = call(server, "GET", f"/api/jobs/{out['job_id']}")
    assert job["report"]["title"].startswith("Bell")
    code, err = call(server, "POST", "/api/run", {"experiment": "nope"})
    assert code == 400


def test_circuit_simulate(server):
    circ = {"qregs": [{"name": "q", "size": 2}], "instructions": [{"name": "h", "qubits": [0]},
                                                                 {"name": "cx", "qubits": [0, 1]}]}
    code, d = call(server, "POST", "/api/circuit/simulate", {"circuit": circ})
    assert code == 200
    assert d["probabilities"] == pytest.approx({"00": 0.5, "11": 0.5})
    assert len(d["bloch"]) == 2 and "OPENQASM 3.0" in d["qasm3"]


def test_enigma_endpoints(server):
    cfg = {"rotors": "I II III", "rings": "1 1 1", "positions": "AAA", "reflector": "B", "plugboard": ""}
    code, d = call(server, "POST", "/api/enigma/encrypt", {"config": cfg, "text": "HELLOWORLD", "trace": True})
    assert d["output"] == "ILBDAAMTAZ" and d["trace"][0]["output"] == "I"
    code, d = call(server, "POST", "/api/enigma/scan", {"config": cfg, "ciphertext": "ILBDAAMTAZ", "crib": "HELLO"})
    assert d["results"][0]["positions"] == "AAA"
    code, d = call(server, "POST", "/api/enigma/oracle-compare", {"config": cfg, "crib": "H"})
    assert {r["synthesis"] for r in d["rows"]} == {"compiled", "staged", "factored"}


def test_ibm_credentials_are_masked(server):
    code, d = call(server, "POST", "/api/ibm/credentials", {"token": "SUPERSECRETTOKEN123456"})
    assert code == 200 and "SUPERSECRET" not in json.dumps(d)
    code, d = call(server, "GET", "/api/info")
    assert "SUPERSECRET" not in json.dumps(d)
    call(server, "DELETE", "/api/ibm/credentials")
