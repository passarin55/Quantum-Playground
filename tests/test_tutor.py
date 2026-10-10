"""Tests for the tutor subsystem: per-experiment tutors, the curriculum, the glossary, CLI and web."""
import json
import threading
import urllib.request

import pytest

from quantum_playground.cli.main import main
from quantum_playground.experiments import REGISTRY, get_experiment
from quantum_playground.tutor import CURRICULUM, GLOSSARY, LEVELS, curriculum_dict, format_lesson, lesson_by_id
from quantum_playground.web.server import make_server


def test_every_experiment_has_a_complete_tutor():
    for exp in REGISTRY.values():
        t = exp.tutor
        assert t and t.concept, exp.id
        for field in ("concept", "how_it_works", "intuition", "what_to_look_for", "real_world_use"):
            assert getattr(t, field).strip(), f"{exp.id}: empty {field}"
        assert t.try_this, f"{exp.id}: no 'try this'"
        # round-trips through dict and renders to text
        assert t.to_dict()["concept"] == t.concept
        assert exp.title in t.to_text(exp.title)


def test_curriculum_is_ordered_and_points_to_real_experiments():
    assert len(CURRICULUM) >= 12
    seen_level = {lvl: i for i, lvl in enumerate(LEVELS)}
    order = [seen_level[l.level] for l in CURRICULUM]
    assert order == sorted(order), "lessons must be grouped by increasing level"
    ids = set()
    for lsn in CURRICULUM:
        get_experiment(lsn.try_experiment)              # raises if the experiment is gone
        assert lsn.big_idea and lsn.key_intuition and lsn.try_what_to_look_for
        assert lsn.id not in ids
        ids.add(lsn.id)


def test_curriculum_covers_new_application_experiments():
    referenced = {l.try_experiment for l in CURRICULUM}
    referenced |= {s.split()[1] for l in CURRICULUM for s in l.steps if s.startswith("Run ")}
    for must in ("grover_key_search", "qday_estimator", "qaoa_portfolio", "vqe_ising", "qkernel",
                 "tfim_dynamics", "ghz_metrology", "shor_code"):
        assert must in referenced, must


def test_glossary_and_lesson_helpers():
    assert len(GLOSSARY) >= 25
    assert "superposition" in GLOSSARY and "QUBO" in GLOSSARY
    assert lesson_by_id("grover").title.startswith("Grover")
    assert lesson_by_id("nope") is None
    text = format_lesson(lesson_by_id("entanglement"))
    assert "Big idea" in text and "qplay run chsh" in text
    assert len(curriculum_dict()) == len(CURRICULUM)


def test_cli_learn_commands(capsys):
    assert main(["learn"]) == 0
    out = capsys.readouterr().out
    assert "Grover" in out and "FOUNDATIONS" in out
    assert main(["learn", "grover"]) == 0
    assert "amplitude" in capsys.readouterr().out.lower()
    assert main(["learn", "exp:shor_code"]) == 0
    assert "error" in capsys.readouterr().out.lower()
    assert main(["learn", "term:qubit"]) == 0
    assert "quantum information" in capsys.readouterr().out.lower()
    assert main(["learn", "glossary"]) == 0
    assert "entanglement" in capsys.readouterr().out.lower()
    assert main(["describe", "grover", "--tutor"]) == 0
    assert "Tutor" in capsys.readouterr().out


@pytest.fixture()
def server():
    srv = make_server("127.0.0.1", 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _get(base, path):
    req = urllib.request.Request(base + path, headers={"X-QPlay": "1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, json.loads(r.read())


def test_web_tutor_endpoints(server):
    code, idx = _get(server, "/api/tutor")
    assert code == 200 and len(idx["curriculum"]) >= 12 and len(idx["glossary"]) >= 25
    code, lsn = _get(server, "/api/tutor/lesson/grover")
    assert lsn["try_experiment"] == "grover"
    code, et = _get(server, "/api/experiments/grover_key_search/tutor")
    assert "quadratic" in et["tutor"]["intuition"].lower()
    # experiment listing exposes has_tutor
    code, exps = _get(server, "/api/experiments")
    assert all(e["has_tutor"] for e in exps["experiments"])
