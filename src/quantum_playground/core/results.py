"""Uniform measurement-result container shared by every backend.

Bitstring convention (same as Qiskit): the right-most character is clbit 0.
``counts`` are over *all* classical bits of the circuit; ``register_counts``
are the per-register marginals (exactly what IBM SamplerV2 returns per
``DataBin`` field).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

import numpy as np


@dataclass
class CircuitResult:
    counts: dict[str, int]
    shots: int
    num_clbits: int
    registers: list[tuple[str, int, int]] = field(default_factory=list)  # (name, start, size)
    memory: Optional[list[str]] = None
    metadata: dict = field(default_factory=dict)

    # ---------------------------------------------------------------- views
    @property
    def register_counts(self) -> dict[str, dict[str, int]]:
        return {name: self.marginal(range(start, start + size)) for name, start, size in self.registers}

    def register(self, name: str) -> dict[str, int]:
        for n, start, size in self.registers:
            if n == name:
                return self.marginal(range(start, start + size))
        raise KeyError(f"No classical register {name!r}; have {[r[0] for r in self.registers]}")

    def register_memory(self, name: str) -> list[str]:
        if self.memory is None:
            raise ValueError("Per-shot memory was not recorded for this result")
        for n, start, size in self.registers:
            if n == name:
                return [_extract(m, list(range(start, start + size)), self.num_clbits) for m in self.memory]
        raise KeyError(name)

    def marginal(self, clbits: Iterable[int]) -> dict[str, int]:
        bits = list(clbits)
        out: dict[str, int] = {}
        for key, c in self.counts.items():
            k = _extract(key, bits, self.num_clbits)
            out[k] = out.get(k, 0) + c
        return dict(sorted(out.items()))

    def probabilities(self, clbits: Optional[Iterable[int]] = None) -> dict[str, float]:
        counts = self.counts if clbits is None else self.marginal(clbits)
        total = sum(counts.values()) or 1
        return {k: v / total for k, v in counts.items()}

    def most_frequent(self, clbits: Optional[Iterable[int]] = None) -> str:
        counts = self.counts if clbits is None else self.marginal(clbits)
        return max(counts.items(), key=lambda kv: kv[1])[0]

    def expectation_parity(self, clbits: Sequence[int]) -> float:
        """<Z...Z> over the given clbits: P(even parity) - P(odd parity)."""
        total = 0
        acc = 0
        for key, c in self.marginal(clbits).items():
            acc += c * (1 if key.count("1") % 2 == 0 else -1)
            total += c
        return acc / total if total else 0.0

    def to_dict(self) -> dict:
        return {"counts": self.counts, "shots": self.shots, "num_clbits": self.num_clbits,
                "registers": [list(r) for r in self.registers],
                "memory": self.memory, "metadata": self.metadata}

    @staticmethod
    def from_dict(d: dict) -> "CircuitResult":
        return CircuitResult(counts={str(k): int(v) for k, v in d["counts"].items()},
                             shots=int(d["shots"]), num_clbits=int(d["num_clbits"]),
                             registers=[tuple(r) for r in d.get("registers", [])],
                             memory=d.get("memory"), metadata=d.get("metadata") or {})


def _extract(key: str, bits: Sequence[int], width: int) -> str:
    key = key.replace(" ", "")
    if len(key) != width:
        key = key.zfill(width)
    return "".join(key[width - 1 - b] for b in reversed(list(bits)))


def counts_from_samples(samples: np.ndarray, width: int) -> dict[str, int]:
    vals, freq = np.unique(samples, return_counts=True)
    return {format(int(v), f"0{width}b"): int(f) for v, f in zip(vals, freq)}


# ---------------------------------------------------------------- statistics
def hellinger_fidelity(p: dict[str, float], q: dict[str, float]) -> float:
    pt, qt = sum(p.values()) or 1, sum(q.values()) or 1
    bc = sum(math.sqrt((p.get(k, 0) / pt) * (q.get(k, 0) / qt)) for k in set(p) | set(q))
    return bc ** 2


def total_variation(p: dict[str, float], q: dict[str, float]) -> float:
    pt, qt = sum(p.values()) or 1, sum(q.values()) or 1
    return 0.5 * sum(abs(p.get(k, 0) / pt - q.get(k, 0) / qt) for k in set(p) | set(q))


def shannon_entropy(counts: dict[str, int]) -> float:
    total = sum(counts.values())
    return -sum((c / total) * math.log2(c / total) for c in counts.values() if c) if total else 0.0


def wilson_interval(successes: int, trials: int, z: float = 1.96) -> tuple[float, float]:
    if trials == 0:
        return (0.0, 1.0)
    p = successes / trials
    denom = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denom
    half = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))
