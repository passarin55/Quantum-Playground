"""``qplay`` command-line interface.

Examples
--------
  qplay experiments
  qplay run chsh                                   # exact local simulation
  qplay run chsh -b local-noisy:heron_like         # density-matrix noise
  qplay run chsh -b ibm:fake_fez                   # IBM Runtime local testing mode
  qplay run chsh -b ibm:ibm_fez --dry-run          # transpile + preflight only
  qplay run chsh -b ibm:ibm_fez --yes              # real QPU submission
  qplay jobs refresh <job-id>
  qplay enigma encode "HELLO WORLD" --rotors "I II III" --positions AAA
  qplay serve --open
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import warnings
from typing import Optional

from .. import __version__


def _params(items: Optional[list[str]]) -> dict:
    out = {}
    for it in items or []:
        if "=" not in it:
            raise SystemExit(f"parameter {it!r} must look like name=value")
        k, v = it.split("=", 1)
        out[k.strip()] = v
    return out


def _ibm_options(a) -> dict:
    d = {}
    if getattr(a, "opt_level", None) is not None:
        d["optimization_level"] = a.opt_level
    if getattr(a, "seeds", None):
        d["seeds"] = a.seeds
    if getattr(a, "max_2q", None):
        d["max_two_qubit"] = a.max_2q
    if getattr(a, "dd", False):
        d["dynamical_decoupling"] = True
    if getattr(a, "twirl", False):
        d["twirling"] = True
        d["measure_twirling"] = True
    if getattr(a, "override_caps", False):
        d["override_caps"] = True
    if getattr(a, "batch", False):
        d["execution_mode"] = "batch"
    return d


def _print_json(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


# ------------------------------------------------------------------ commands
def cmd_experiments(a) -> int:
    from ..experiments import list_experiments
    cat = None
    for e in list_experiments():
        if e["category"] != cat:
            cat = e["category"]
            print(f"\n{cat}")
        print(f"  {e['id']:<20} {e['summary']}")
    print("\nDetails: qplay describe <id>   Run: qplay run <id> [-p name=value] [-b backend]")
    return 0


def cmd_describe(a) -> int:
    from ..experiments import get_experiment
    e = get_experiment(a.experiment).describe()
    print(f"{e['title']}  [{e['id']}, {e['category']}]\n")
    print(e["summary"])
    if e["description"]:
        print("\n" + e["description"])
    if e["hardware_notes"]:
        print("\nHardware: " + e["hardware_notes"])
    print(f"\nDefault shots: {e['default_shots']}\nParameters:")
    for p in e["params"]:
        rng = ""
        if p["choices"]:
            rng = f" choices={p['choices']}"
        elif p["min"] is not None:
            rng = f" range=[{p['min']}, {p['max']}]"
        print(f"  {p['name']:<16} {p['kind']:<7} default={p['default']!r}{rng}\n      {p['help']}")
    exp = get_experiment(a.experiment)
    if getattr(a, "tutor", False) and exp.tutor and exp.tutor.concept:
        print("\n" + exp.tutor.to_text(exp.title))
    elif exp.tutor and exp.tutor.concept:
        print(f"\nTutor available: qplay learn {a.experiment}")
    return 0


def cmd_learn(a) -> int:
    from ..experiments import get_experiment
    from ..tutor import CURRICULUM, GLOSSARY, format_lesson, lesson_by_id
    if a.topic in (None, "", "curriculum", "index"):
        print("Quantum Playground Tutor — curriculum\n")
        level = None
        for lsn in CURRICULUM:
            if lsn.level != level:
                level = lsn.level
                print(f"\n[{level.upper()}]")
            print(f"  {lsn.id:<22} {lsn.title}")
        print("\nRead a lesson:  qplay learn <lesson-id>")
        print("An experiment:  qplay learn exp:<experiment-id>   (or: qplay describe <id> --tutor)")
        print("Glossary term:  qplay learn term:<word>")
        return 0
    topic = a.topic
    if topic == "glossary":
        for term, definition in sorted(GLOSSARY.items()):
            print(f"{term}\n    {definition}\n")
        return 0
    if topic.startswith("term:"):
        key = topic[5:].strip().lower()
        hit = next((f"{t}: {d}" for t, d in GLOSSARY.items() if t.lower() == key), None)
        print(hit or f"No glossary entry for {key!r}. Try: qplay learn glossary")
        return 0 if hit else 1
    if topic.startswith("exp:"):
        exp = get_experiment(topic[4:])
        if not (exp.tutor and exp.tutor.concept):
            print(f"No tutor for {exp.id}.")
            return 1
        print(exp.tutor.to_text(exp.title))
        return 0
    lsn = lesson_by_id(topic)
    if lsn is None:
        from ..tutor import CURRICULUM
        print(f"Unknown topic {topic!r}. Lessons: {', '.join(l.id for l in CURRICULUM)}")
        return 1
    print(format_lesson(lsn))
    return 0


def cmd_circuit(a) -> int:
    from ..core import to_qasm2, to_qasm3
    from ..runner import Runner
    circuits = Runner().circuits(a.experiment, _params(a.param))
    for qc in circuits:
        if a.format == "json":
            print(qc.to_json(indent=1))
        elif a.format == "qasm3":
            print(to_qasm3(qc))
        elif a.format == "qasm2":
            print(to_qasm2(qc))
        else:
            print(f"# {qc.name}: {qc.gate_profile()}")
            print(qc.draw())
        print()
    return 0


def cmd_run(a) -> int:
    from ..backends import SubmissionBlocked
    from ..runner import Runner
    runner = Runner()
    params = _params(a.param)
    opts = _ibm_options(a)
    if a.dry_run:
        rep = runner.preflight(a.experiment, params, a.backend, a.shots, opts)
        if a.json:
            _print_json(rep.to_dict())
        else:
            print(f"Preflight on {rep.backend}: {'BLOCKED' if rep.blocked else 'OK'}")
            for c in rep.circuits:
                print(f"  {c.get('name', '')}: depth {c.get('depth')}, 2q {c.get('two_qubit')}, "
                      f"multi {c.get('multi_qubit')}, size {c.get('size')}"
                      + (f", seed {c['best_seed']}" if "best_seed" in c else "")
                      + (f", error product ≈ {c['error_estimate']:.3g}" if c.get("error_estimate") else ""))
            for w in rep.warnings:
                print("  warning:", w)
            for r in rep.reasons:
                print("  blocked:", r)
        return 1 if rep.blocked else 0
    confirm = a.yes
    if a.backend.startswith(("ibm", "braket:arn")) and not a.backend.startswith("ibm:fake") and not confirm:
        if sys.stdin.isatty():
            ans = input(f"Submit '{a.experiment}' to the real device {a.backend}? This uses your quota. [y/N] ")
            confirm = ans.strip().lower() in ("y", "yes")
        if not confirm:
            print("Not submitted. Use --yes to confirm, or --dry-run to inspect the transpiled circuits.")
            return 2
    try:
        out = runner.run(a.experiment, params, a.backend, a.shots, confirm=confirm,
                         mitigate_readout=a.mitigate_readout, ibm_options=opts, seed=a.seed)
    except SubmissionBlocked as exc:
        print("Submission blocked by preflight:")
        for r in exc.report.reasons:
            print("  -", r)
        print("Raise the cap (--max-2q) or pass --override-caps if you really want to run it.")
        return 3
    if a.json:
        _print_json(out.to_dict())
    else:
        print(f"job {out.job_id} on {out.backend}: {out.status}")
        print(out.report_text if out.report else out.message)
    return 0


def cmd_backends(a) -> int:
    from ..backends import available_backends, get_backend
    for b in available_backends():
        flag = "✓" if b["available"] else "✗ (SDK missing)"
        print(f"  {b['spec']:<28} {b['label']:<52} {flag}{'  [cloud]' if b['remote'] else ''}")
    if a.ibm:
        be = get_backend("ibm")
        print("\nIBM Quantum devices visible to your account:")
        for d in be.devices():
            print(f"  {d.name:<20} {d.num_qubits:>4} qubits  operational={d.operational}  pending={d.pending_jobs}")
    return 0


def cmd_jobs(a) -> int:
    from ..runner import Runner
    r = Runner()
    if a.action == "list":
        import datetime as dt
        for j in r.store.list(a.limit):
            when = dt.datetime.fromtimestamp(j["created_at"]).strftime("%Y-%m-%d %H:%M")
            print(f"  {when}  {j['status']:<9} {j['backend']:<24} {j.get('experiment') or '':<18} {j['job_id']}")
        return 0
    if not a.job_id:
        raise SystemExit("job id required")
    if a.action == "delete":
        print("deleted" if r.store.delete(a.job_id) else "not found")
        return 0
    out = r.refresh(a.job_id) if a.action == "refresh" else r._outcome(r.store.get(a.job_id) or {})
    if a.json:
        _print_json(out.to_dict())
    else:
        print(f"job {out.job_id} on {out.backend}: {out.status}")
        print(out.report_text if out.report else out.message)
    return 0


def cmd_ibm(a) -> int:
    from .. import config
    if a.action == "login":
        token = a.token or os.environ.get("QP_IBM_TOKEN") or getpass.getpass("IBM Cloud API key: ")
        if a.save:
            from ..backends.ibm import save_account
            save_account(token, a.instance)
            print("Saved with QiskitRuntimeService.save_account (stored in ~/.qiskit, not in this project).")
        else:
            config.set_session_ibm_credentials(token, a.instance)
        from ..backends import get_backend
        be = get_backend("ibm")
        print("Authenticated. Devices:")
        for d in be.devices():
            print(f"  {d.name:<20} {d.num_qubits:>4} qubits  pending={d.pending_jobs}")
        return 0
    if a.action == "status":
        _print_json(config.ibm_credentials().describe())
        return 0
    from ..backends import get_backend
    be = get_backend("ibm")
    if a.action == "devices":
        for d in be.devices():
            print(f"  {d.name:<20} {d.num_qubits:>4} qubits  operational={d.operational}  pending={d.pending_jobs}")
    elif a.action == "usage":
        _print_json(be.usage())
    return 0


def cmd_enigma(a) -> int:
    from ..enigma import Enigma, EnigmaConfig, encrypt, generate_keysheet, groups, window_scan
    cfg = EnigmaConfig.create(a.rotors, a.rings, a.positions, a.reflector, a.plugboard)
    if a.action in ("encode", "decode"):
        out = encrypt(a.text, cfg, keep_nonletters=a.keep)
        print(out if a.keep else groups(out))
    elif a.action == "trace":
        e = Enigma(cfg)
        for ch in a.text.upper():
            if "A" <= ch <= "Z":
                t = e.keypress_trace(ch)
                path = " → ".join(f"{s['letter']}" for s in t["path"])
                print(f"{t['window_before']}→{t['window_after']}  {ch}: {path}")
    elif a.action == "scan":
        if not a.crib:
            raise SystemExit("--crib required")
        res = window_scan(cfg, a.text, a.crib)
        print(f"Tested {res['tested']} start windows, {res['matches']} consistent with the crib")
        for r in res["results"]:
            print(f"  {r['positions']}: {groups(r['plaintext'])}")
    elif a.action == "keysheet":
        print(generate_keysheet(a.days).to_text())
    return 0


def cmd_serve(a) -> int:
    from ..web.server import serve
    serve(a.host, a.port, open_browser=a.open)
    return 0


# ------------------------------------------------------------------ parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="qplay", description="Quantum Playground Studio v9")
    p.add_argument("--version", action="version", version=f"qplay {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("experiments", help="list experiments").set_defaults(fn=cmd_experiments)
    d = sub.add_parser("describe", help="describe an experiment")
    d.add_argument("experiment")
    d.add_argument("--tutor", action="store_true", help="also print the experiment's tutor lesson")
    d.set_defaults(fn=cmd_describe)

    lrn = sub.add_parser("learn", help="built-in quantum tutor (curriculum, lessons, glossary)")
    lrn.add_argument("topic", nargs="?", help="lesson id, 'glossary', 'term:<word>', or 'exp:<experiment-id>'")
    lrn.set_defaults(fn=cmd_learn)

    c = sub.add_parser("circuit", help="print an experiment's circuits")
    c.add_argument("experiment")
    c.add_argument("-p", "--param", action="append")
    c.add_argument("--format", choices=["text", "qasm2", "qasm3", "json"], default="text")
    c.set_defaults(fn=cmd_circuit)

    r = sub.add_parser("run", help="run an experiment")
    r.add_argument("experiment")
    r.add_argument("-p", "--param", action="append", help="name=value (repeatable)")
    r.add_argument("-b", "--backend", default="local")
    r.add_argument("--shots", type=int)
    r.add_argument("--seed", type=int)
    r.add_argument("--yes", action="store_true", help="confirm real-QPU submission")
    r.add_argument("--dry-run", action="store_true", help="transpile + preflight only")
    r.add_argument("--mitigate-readout", action="store_true")
    r.add_argument("--json", action="store_true")
    g = r.add_argument_group("IBM options")
    g.add_argument("--opt-level", type=int, choices=[0, 1, 2, 3])
    g.add_argument("--seeds", type=int, help="number of transpiler seeds to try (1-5)")
    g.add_argument("--max-2q", type=int, help="native two-qubit gate cap per circuit")
    g.add_argument("--override-caps", action="store_true")
    g.add_argument("--dd", action="store_true", help="dynamical decoupling")
    g.add_argument("--twirl", action="store_true", help="gate + measurement twirling")
    g.add_argument("--batch", action="store_true", help="IBM batch execution mode")
    r.set_defaults(fn=cmd_run)

    b = sub.add_parser("backends", help="list backends")
    b.add_argument("--ibm", action="store_true", help="also list IBM devices (needs credentials)")
    b.set_defaults(fn=cmd_backends)

    j = sub.add_parser("jobs", help="job store")
    j.add_argument("action", choices=["list", "show", "refresh", "delete"])
    j.add_argument("job_id", nargs="?")
    j.add_argument("--limit", type=int, default=30)
    j.add_argument("--json", action="store_true")
    j.set_defaults(fn=cmd_jobs)

    i = sub.add_parser("ibm", help="IBM Quantum account helpers")
    i.add_argument("action", choices=["login", "status", "devices", "usage"])
    i.add_argument("--token", help="IBM Cloud API key (prompted if omitted; avoid shell history)")
    i.add_argument("--instance", help="service instance CRN (optional)")
    i.add_argument("--save", action="store_true", help="persist via Qiskit's account store (~/.qiskit)")
    i.set_defaults(fn=cmd_ibm)

    e = sub.add_parser("enigma", help="classical Enigma tools")
    e.add_argument("action", choices=["encode", "decode", "trace", "scan", "keysheet"])
    e.add_argument("text", nargs="?", default="")
    e.add_argument("--rotors", default="I II III")
    e.add_argument("--rings", default="1 1 1")
    e.add_argument("--positions", default="AAA")
    e.add_argument("--reflector", default="B")
    e.add_argument("--plugboard", default="")
    e.add_argument("--crib", default="")
    e.add_argument("--days", type=int, default=7)
    e.add_argument("--keep", action="store_true", help="keep spaces/punctuation")
    e.set_defaults(fn=cmd_enigma)

    s = sub.add_parser("serve", help="start the web studio")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--open", action="store_true", help="open a browser tab")
    s.set_defaults(fn=cmd_serve)
    return p


def main(argv: Optional[list[str]] = None) -> int:
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    args = build_parser().parse_args(argv)
    try:
        return int(args.fn(args) or 0)
    except (ValueError, KeyError, RuntimeError, PermissionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
