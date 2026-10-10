"""Experiment library: 21 self-analysing experiments plus the custom-circuit runner."""
from .base import REGISTRY, Chart, Experiment, Param, Plan, Report, Table, Tutor, get_experiment, register


def _load_all():
    from . import (applications, custom, dynamics, entanglement, enigma_lab, fourier, hardware,  # noqa: F401
                   oracles, optimization, protocols, qec, security,
                   variational)


_load_all()


def list_experiments() -> list[dict]:
    return [e.describe() for e in sorted(REGISTRY.values(), key=lambda e: (e.category, e.id))]


__all__ = ["REGISTRY", "Chart", "Experiment", "Param", "Plan", "Report", "Table", "get_experiment", "register",
           "list_experiments"]
