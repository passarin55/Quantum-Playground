"""Regenerate docs/EXPERIMENTS.md from the experiment registry: python scripts/gen_experiment_docs.py"""
from pathlib import Path

from quantum_playground.experiments import list_experiments


def main() -> None:
    out = ["# Experiments", "",
           "Generated from the registry (`python scripts/gen_experiment_docs.py`). Run any of them with",
           "`qplay run <id> [-p name=value ...] [-b backend]`; every report carries a pass/warn/fail verdict.", ""]
    cat = None
    for e in list_experiments():
        if e["category"] != cat:
            cat = e["category"]
            out += [f"## {cat}", ""]
        out += [f"### `{e['id']}` — {e['title']}", "", e["summary"], ""]
        if e["description"]:
            out += [e["description"], ""]
        if e["hardware_notes"]:
            out += [f"*Hardware:* {e['hardware_notes']}", ""]
        if e["params"]:
            out += ["| parameter | type | default | description |", "|---|---|---|---|"]
            for p in e["params"]:
                kind = p["kind"] + (f" ({', '.join(p['choices'])})" if p["choices"] else "")
                default = str(p["default"]).replace("|", "\\|") if p["default"] != "" else "—"
                out.append(f"| `{p['name']}` | {kind} | `{default}` | {p['help'].replace('|', '/')} |")
            out.append("")
        out += [f"Default shots: {e['default_shots']}", ""]
    Path(__file__).resolve().parents[1].joinpath("docs", "EXPERIMENTS.md").write_text("\n".join(out), encoding="utf-8")


if __name__ == "__main__":
    main()
