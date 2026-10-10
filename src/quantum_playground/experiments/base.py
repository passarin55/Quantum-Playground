"""Experiment plug-in framework.

An experiment declares typed parameters, builds one or more circuits plus a
JSON-serialisable *context*, and analyses the measured results into a
``Report`` (summary lines, metrics, tables, charts, verdict).  Because the
context is stored with the job, cloud results can be analysed in a later
session.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional, Sequence

from ..core.circuit import Circuit
from ..core.results import CircuitResult


@dataclass
class Param:
    name: str
    kind: str                     # int | float | str | bool | choice | bits
    default: Any
    help: str = ""
    min: Optional[float] = None
    max: Optional[float] = None
    choices: Optional[Sequence[str]] = None

    def parse(self, value: Any) -> Any:
        if value is None or value == "":
            return self.default
        k = self.kind
        try:
            if k == "int":
                v = int(float(value))
            elif k == "float":
                v = float(value)
            elif k == "bool":
                v = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "on")
            elif k == "bits":
                v = str(value).strip().replace(" ", "")
                if v and any(ch not in "01" for ch in v):
                    raise ValueError
            elif k == "choice":
                v = str(value)
                if self.choices and v not in self.choices:
                    raise ValueError
            else:
                v = str(value)
        except (TypeError, ValueError):
            raise ValueError(f"Parameter {self.name!r}: invalid {k} value {value!r}"
                             + (f" (choose from {list(self.choices)})" if self.choices else "")) from None
        if k in ("int", "float"):
            if self.min is not None and v < self.min:
                raise ValueError(f"Parameter {self.name!r} must be >= {self.min}")
            if self.max is not None and v > self.max:
                raise ValueError(f"Parameter {self.name!r} must be <= {self.max}")
        return v

    def to_dict(self) -> dict:
        d = asdict(self)
        d["choices"] = list(self.choices) if self.choices else None
        return d


@dataclass
class Plan:
    circuits: list[Circuit]
    context: dict = field(default_factory=dict)
    memory: bool = False
    shots: Optional[int] = None   # experiment-imposed shots (e.g. 1 per BB84 round)


@dataclass
class Table:
    title: str
    columns: list[str]
    rows: list[list[Any]]


@dataclass
class Chart:
    title: str
    labels: list[str]
    series: dict[str, list[float]]
    kind: str = "bar"            # bar | line
    x_label: str = ""
    y_label: str = ""


@dataclass
class Report:
    title: str
    summary: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    tables: list[Table] = field(default_factory=list)
    charts: list[Chart] = field(default_factory=list)
    verdict: Optional[str] = None   # pass | warn | fail
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return json.loads(json.dumps(asdict(self), default=_json_default))

    def to_text(self) -> str:
        out = [f"=== {self.title} ==="]
        if self.verdict:
            out.append(f"verdict: {self.verdict.upper()}")
        out += self.summary
        if self.metrics:
            out.append("")
            w = max(len(k) for k in self.metrics)
            for k, v in self.metrics.items():
                out.append(f"  {k:<{w}} : {_fmt(v)}")
        for t in self.tables:
            out.append("")
            out.append(f"-- {t.title} --")
            out.extend(_table_text(t))
        for c in self.charts:
            out.append("")
            out.append(f"-- {c.title} --")
            out.extend(_chart_text(c))
        if self.notes:
            out.append("")
            out += [f"note: {n}" for n in self.notes]
        return "\n".join(out)


def _json_default(o):
    try:
        import numpy as np
        if isinstance(o, np.generic):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
    except ImportError:  # pragma: no cover
        pass
    return str(o)


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        if v != 0 and (abs(v) < 1e-3 or abs(v) >= 1e6):
            return f"{v:.3e}"
        return f"{v:.4f}"
    return str(v)


def _table_text(t: Table, max_rows: int = 40) -> list[str]:
    rows = [[_fmt(c) for c in r] for r in t.rows[:max_rows]]
    widths = [max([len(c)] + [len(r[i]) for r in rows]) for i, c in enumerate(t.columns)]
    lines = ["  " + " | ".join(c.ljust(w) for c, w in zip(t.columns, widths)),
             "  " + "-+-".join("-" * w for w in widths)]
    lines += ["  " + " | ".join(c.ljust(w) for c, w in zip(r, widths)) for r in rows]
    if len(t.rows) > max_rows:
        lines.append(f"  … {len(t.rows) - max_rows} more rows")
    return lines


def _chart_text(c: Chart, width: int = 40, max_rows: int = 32) -> list[str]:
    lines = []
    name, values = next(iter(c.series.items()))
    top = max([abs(v) for v in values] + [1e-12])
    lw = max((len(l) for l in c.labels[:max_rows]), default=1)
    for lab, v in list(zip(c.labels, values))[:max_rows]:
        bar = "█" * int(round(width * abs(v) / top))
        lines.append(f"  {lab:>{lw}} {bar} {_fmt(float(v))}")
    return lines


@dataclass
class Tutor:
    """A self-contained mini-lesson attached to an experiment.

    Every field is plain prose aimed at a curious beginner; the goal is that a
    learner can read the tutor, run the experiment, and understand what they are
    looking at and why it matters in the real world.
    """

    concept: str = ""                 # the one big idea, in a sentence or two
    how_it_works: str = ""            # what the circuit does, step by step
    intuition: str = ""              # the mental model that makes it click
    misconception: str = ""          # the wrong idea to unlearn
    what_to_look_for: str = ""       # how to read the report / what "success" looks like
    try_this: list[str] = field(default_factory=list)   # concrete parameter experiments
    real_world_use: str = ""         # where this matters outside the playground
    going_deeper: str = ""           # the next concept / where to read more
    references: list[dict] = field(default_factory=list)  # [{title, url}]
    prerequisites: list[str] = field(default_factory=list)  # lesson/experiment ids

    def to_dict(self) -> dict:
        return {"concept": self.concept, "how_it_works": self.how_it_works, "intuition": self.intuition,
                "misconception": self.misconception, "what_to_look_for": self.what_to_look_for,
                "try_this": list(self.try_this), "real_world_use": self.real_world_use,
                "going_deeper": self.going_deeper, "references": list(self.references),
                "prerequisites": list(self.prerequisites)}

    def to_text(self, title: str = "") -> str:
        out = [f"=== Tutor: {title} ===" if title else "=== Tutor ==="]
        pairs = [("The idea", self.concept), ("How it works", self.how_it_works),
                 ("Intuition", self.intuition), ("Common misconception", self.misconception),
                 ("What to look for", self.what_to_look_for), ("Why it matters", self.real_world_use),
                 ("Going deeper", self.going_deeper)]
        for label, body in pairs:
            if body:
                out += ["", label + ":", _wrap(body)]
        if self.try_this:
            out += ["", "Try this:"] + [f"  • {t}" for t in self.try_this]
        if self.references:
            out += ["", "References:"] + [f"  - {r.get('title', '')}: {r.get('url', '')}" for r in self.references]
        return "\n".join(out)


def _wrap(text: str, width: int = 96) -> str:
    import textwrap
    return "\n".join(textwrap.fill(p, width) for p in text.split("\n"))


class Experiment:
    id: str = ""
    title: str = ""
    category: str = ""
    summary: str = ""
    description: str = ""
    params: list[Param] = []
    hardware_notes: str = ""
    default_shots: int = 2000
    tutor: Tutor = Tutor()

    def resolve(self, raw: Optional[dict] = None) -> dict:
        raw = dict(raw or {})
        known = {p.name for p in self.params}
        unknown = set(raw) - known
        if unknown:
            raise ValueError(f"Unknown parameter(s) for {self.id}: {sorted(unknown)}; known: {sorted(known)}")
        return {p.name: p.parse(raw.get(p.name)) for p in self.params}

    def build(self, params: dict) -> Plan:
        raise NotImplementedError

    def analyze(self, params: dict, context: dict, results: list[CircuitResult]) -> Report:
        raise NotImplementedError

    def describe(self, include_tutor: bool = False) -> dict:
        d = {"id": self.id, "title": self.title, "category": self.category, "summary": self.summary,
             "description": self.description, "hardware_notes": self.hardware_notes,
             "default_shots": self.default_shots, "params": [p.to_dict() for p in self.params],
             "has_tutor": bool(self.tutor and self.tutor.concept)}
        if include_tutor:
            d["tutor"] = self.tutor.to_dict() if self.tutor else None
        return d


REGISTRY: dict[str, Experiment] = {}


def register(cls):
    inst = cls()
    if not inst.id:
        raise ValueError("experiment needs an id")
    REGISTRY[inst.id] = inst
    return cls


def get_experiment(exp_id: str) -> Experiment:
    from . import _load_all  # noqa: F401  (ensures registration)
    try:
        return REGISTRY[exp_id]
    except KeyError:
        raise KeyError(f"Unknown experiment {exp_id!r}. Available: {', '.join(sorted(REGISTRY))}") from None


def counts_chart(title: str, counts: dict[str, float], top: int = 32, ideal: Optional[dict] = None) -> Chart:
    total = sum(counts.values()) or 1
    keys = sorted(set(counts) | set(ideal or {}), key=lambda k: -(counts.get(k, 0)))[:top]
    keys = sorted(keys)
    series = {"measured": [counts.get(k, 0) / total for k in keys]}
    if ideal:
        series["ideal"] = [ideal.get(k, 0.0) for k in keys]
    return Chart(title, keys, series, "bar", "outcome", "probability")


def binomial_sigma(p: float, n: int) -> float:
    return math.sqrt(max(p * (1 - p), 1e-12) / max(n, 1))
