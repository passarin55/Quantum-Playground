"""JSON API handlers for the web studio. Each returns (status, payload)."""
from __future__ import annotations

import math
import threading
from typing import Any

from .. import __version__, config
from ..backends import SubmissionBlocked, available_backends, get_backend
from ..core import Circuit, Statevector, exact_distribution, simulate, to_qasm3
from ..core.statevector import MAX_QUBITS
from ..enigma import (Enigma, EnigmaConfig, encrypt, generate_keysheet, groups, historical_problem,
                      keyed_encryption, mini_problem, window_scan)
from ..enigma.machine import M3_ROTORS, M4_GREEK, REFLECTORS
from ..experiments import get_experiment, list_experiments
from ..runner import Runner

_RUNNER_LOCK = threading.Lock()
_RUNNER: Runner | None = None


def runner() -> Runner:
    global _RUNNER
    with _RUNNER_LOCK:
        if _RUNNER is None:
            _RUNNER = Runner()
        return _RUNNER


# ------------------------------------------------------------------ info
def info(_body):
    creds = config.ibm_credentials()
    return 200, {"version": __version__, "backends": available_backends(), "ibm": creds.describe(),
                 "has_ibm_token": bool(creds.token),
                 "experiments": sum(1 for e in list_experiments() if e["id"] != "custom"),
                 "enigma": {"rotors": list(M3_ROTORS), "greek": list(M4_GREEK), "reflectors": list(REFLECTORS)}}


def experiments(_body):
    return 200, {"experiments": list_experiments()}


def tutor_index(_body):
    from ..tutor import GLOSSARY, curriculum_dict
    return 200, {"curriculum": curriculum_dict(), "glossary": GLOSSARY}


def tutor_lesson(_body, lesson_id):
    from ..tutor import lesson_by_id
    lsn = lesson_by_id(lesson_id)
    if lsn is None:
        return 404, {"error": f"unknown lesson {lesson_id!r}"}
    return 200, lsn.to_dict()


def experiment_tutor(_body, exp_id):
    exp = get_experiment(exp_id)
    if not (exp.tutor and exp.tutor.concept):
        return 404, {"error": f"no tutor for {exp_id}"}
    return 200, {"id": exp.id, "title": exp.title, "tutor": exp.tutor.to_dict()}


def experiment_circuits(body, exp_id):
    exp = get_experiment(exp_id)
    plan = exp.build(exp.resolve(body.get("params")))
    out = []
    for qc in plan.circuits[:12]:
        out.append({"name": qc.name, "profile": qc.gate_profile(), "drawing": qc.draw(max_columns=60),
                    "qasm3": to_qasm3(qc) if qc.size() < 4000 else None})
    return 200, {"circuits": out, "total": len(plan.circuits)}


def _run_kwargs(body: dict) -> dict:
    return {"shots": int(body["shots"]) if body.get("shots") else None,
            "ibm_options": body.get("ibm_options") or {}}


def run(body):
    try:
        out = runner().run(body["experiment"], body.get("params") or {}, body.get("backend", "local"),
                           confirm=bool(body.get("confirm")), mitigate_readout=bool(body.get("mitigate_readout")),
                           seed=body.get("seed"), **_run_kwargs(body))
    except SubmissionBlocked as exc:
        return 409, {"error": "blocked by preflight", "preflight": exc.report.to_dict()}
    return 200, out.to_dict()


def preflight(body):
    kw = _run_kwargs(body)
    rep = runner().preflight(body["experiment"], body.get("params") or {}, body.get("backend", "local"),
                             kw["shots"], kw["ibm_options"])
    return 200, rep.to_dict()


def jobs(_body):
    return 200, {"jobs": runner().store.list(100)}


def job(_body, job_id):
    rec = runner().store.get(job_id)
    if rec is None:
        return 404, {"error": "unknown job"}
    return 200, runner()._outcome(rec).to_dict()


def job_refresh(_body, job_id):
    return 200, runner().refresh(job_id).to_dict()


def job_delete(_body, job_id):
    return 200, {"deleted": runner().store.delete(job_id)}


# ------------------------------------------------------------------ circuit lab
def simulate_circuit(body):
    qc = Circuit.from_dict(body["circuit"])
    if qc.num_qubits > 16:
        return 400, {"error": "the live composer is limited to 16 qubits"}
    shots = int(body.get("shots") or 1024)
    unitary_part = qc.remove_final_measurements()
    payload: dict[str, Any] = {"profile": qc.gate_profile(), "drawing": qc.draw(), "qasm3": to_qasm3(qc)}
    if unitary_part.is_unitary() and not unitary_part.has_dynamic_features():
        sv = Statevector.from_circuit(unitary_part)
        n = qc.num_qubits
        probs = sv.probabilities()
        payload["probabilities"] = {format(i, f"0{n}b"): float(p) for i, p in enumerate(probs) if p > 1e-10}
        if n <= 6:
            payload["amplitudes"] = [{"basis": format(i, f"0{n}b"), "re": float(a.real), "im": float(a.imag),
                                      "p": float(abs(a) ** 2), "phase": float(math.atan2(a.imag, a.real))}
                                     for i, a in enumerate(sv.data)]
        payload["bloch"] = [list(sv.bloch_vector(q)) + [sv.purity(q)] for q in range(n)]
        payload["entropy"] = [sv.entanglement_entropy(q) for q in range(n)]
    meas = qc if any(i.name == "measure" for i in qc.instructions) else _with_measure(qc)
    res = simulate(meas, shots=shots, seed=body.get("seed"))
    payload["counts"] = res.counts
    payload["exact"] = exact_distribution(meas) if meas.num_qubits <= 14 else None
    return 200, payload


def _with_measure(qc: Circuit) -> Circuit:
    out = qc.copy()
    out.measure_all()
    return out


# ------------------------------------------------------------------ enigma
def _cfg(body: dict) -> EnigmaConfig:
    c = body.get("config") or {}
    return EnigmaConfig.create(c.get("rotors", "I II III"), c.get("rings", "1 1 1"), c.get("positions", "AAA"),
                               c.get("reflector", "B"), c.get("plugboard", ""))


def enigma_encrypt(body):
    cfg = _cfg(body)
    text = str(body.get("text", ""))[:20000]
    keep = bool(body.get("keep"))
    e = Enigma(cfg)
    trace = None
    if body.get("trace"):
        trace = [e.keypress_trace(ch) for ch in text.upper() if "A" <= ch <= "Z"][:200]
    out = encrypt(text, cfg, keep_nonletters=keep)
    end = Enigma(cfg)
    end.transform(text)
    return 200, {"output": out, "grouped": groups(out) if not keep else out, "final_window": end.window(),
                 "trace": trace, "describe": cfg.describe()}


def enigma_scan(body):
    res = window_scan(_cfg(body), body.get("ciphertext", ""), body.get("crib", ""))
    for r in res["results"]:
        r["grouped"] = groups(r["plaintext"])
    return 200, res


def enigma_keysheet(body):
    sheet = generate_keysheet(int(body.get("days", 7)))
    return 200, {"days": sheet.days, "text": sheet.to_text()}


def enigma_oracle_compare(body):
    """Raw circuit cost of each synthesis strategy for the same key-search problem."""
    model = body.get("model", "historical")
    plain = str(body.get("crib", "H")).upper()
    if model == "mini":
        prob = mini_problem(plain, str(body.get("cipher", "C")).upper())
        modes = ["compiled", "staged"]
    else:
        cfg = _cfg(body)
        cipher = encrypt(plain, cfg)
        prob = historical_problem(cfg, plain, cipher, key_bits=int(body.get("key_bits", 2)),
                                  first=body.get("first", "A"))
        modes = ["compiled", "staged", "factored"]
    rows = []
    for m in modes:
        size = depth = multi = 0
        for i in range(len(prob.plaintext)):
            qc = keyed_encryption(prob, i, m)
            prof = qc.gate_profile()
            size += prof["size"]
            depth += prof["depth"]
            multi += prof["multi_qubit"]
        rows.append({"synthesis": m, "size": size, "depth": depth, "multi_qubit": multi})
    return 200, {"rows": rows, "candidates": prob.candidate_labels, "matches": prob.classical_matches()}


# ------------------------------------------------------------------ IBM
def ibm_status(_body):
    creds = config.ibm_credentials()
    return 200, {"credentials": creds.describe(), "has_token": bool(creds.token)}


def ibm_set_credentials(body):
    token = (body.get("token") or "").strip()
    if not token:
        return 400, {"error": "token required"}
    instance = (body.get("instance") or "").strip() or None
    if body.get("save"):
        from ..backends.ibm import save_account
        save_account(token, instance)
        config.clear_session_ibm_credentials()
        return 200, {"saved": True, "credentials": config.ibm_credentials().describe()}
    config.set_session_ibm_credentials(token, instance)
    return 200, {"saved": False, "credentials": config.ibm_credentials().describe()}


def ibm_clear_credentials(_body):
    config.clear_session_ibm_credentials()
    return 200, {"credentials": config.ibm_credentials().describe()}


def ibm_devices(_body):
    be = get_backend("ibm")
    return 200, {"devices": [d.to_dict() for d in be.devices()]}


ROUTES = [
    ("GET", "/api/info", info),
    ("GET", "/api/experiments", experiments),
    ("GET", "/api/tutor", tutor_index),
    ("GET", "/api/tutor/lesson/{id}", tutor_lesson),
    ("GET", "/api/experiments/{id}/tutor", experiment_tutor),
    ("POST", "/api/experiments/{id}/circuits", experiment_circuits),
    ("POST", "/api/run", run),
    ("POST", "/api/preflight", preflight),
    ("GET", "/api/jobs", jobs),
    ("GET", "/api/jobs/{id}", job),
    ("POST", "/api/jobs/{id}/refresh", job_refresh),
    ("DELETE", "/api/jobs/{id}", job_delete),
    ("POST", "/api/circuit/simulate", simulate_circuit),
    ("POST", "/api/enigma/encrypt", enigma_encrypt),
    ("POST", "/api/enigma/scan", enigma_scan),
    ("POST", "/api/enigma/keysheet", enigma_keysheet),
    ("POST", "/api/enigma/oracle-compare", enigma_oracle_compare),
    ("GET", "/api/ibm/status", ibm_status),
    ("POST", "/api/ibm/credentials", ibm_set_credentials),
    ("DELETE", "/api/ibm/credentials", ibm_clear_credentials),
    ("GET", "/api/ibm/devices", ibm_devices),
]
