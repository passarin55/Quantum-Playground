"""Reusable circuit fragments and classical post-processing for the experiments."""
from __future__ import annotations

import math
from fractions import Fraction
from typing import Iterable, Optional, Sequence

import numpy as np

from ..core.circuit import Circuit


# ---------------------------------------------------------------- QFT
def qft(qc: Circuit, qubits: Sequence[int], inverse: bool = False, swaps: bool = True) -> None:
    """QFT|x> = N^-1/2 sum_y exp(2 pi i x y / N)|y>, qubits[0] = least significant bit."""
    q = list(qubits)
    n = len(q)
    ops: list[tuple] = []
    for j in reversed(range(n)):
        ops.append(("h", q[j]))
        for k in reversed(range(j)):
            ops.append(("cp", math.pi / (1 << (j - k)), q[k], q[j]))
    if swaps:
        for i in range(n // 2):
            ops.append(("swap", q[i], q[n - 1 - i]))
    if inverse:
        ops = list(reversed(ops))
    for op in ops:
        if op[0] == "h":
            qc.h(op[1])
        elif op[0] == "cp":
            qc.cp(-op[1] if inverse else op[1], op[2], op[3])
        else:
            qc.swap(op[1], op[2])


def fourier_state(qc: Circuit, qubits: Sequence[int], y: int) -> None:
    """Prepare QFT|y> directly with H + phase gates (used for QFT round trips)."""
    n = len(qubits)
    N = 1 << n
    for j, q in enumerate(qubits):
        qc.h(q)
        qc.p(2 * math.pi * y * (1 << j) / N, q)


# ---------------------------------------------------------------- number theory
def continued_fraction_candidates(y: int, t: int, n_max: int) -> list[int]:
    """Denominators of the convergents of y / 2^t that are <= n_max."""
    if y == 0:
        return []
    frac = Fraction(y, 1 << t)
    out = []
    for d in range(1, n_max + 1):
        approx = frac.limit_denominator(d)
        if approx.denominator not in out and approx.denominator > 1:
            out.append(approx.denominator)
    return out


def multiplicative_order(a: int, n: int) -> Optional[int]:
    if math.gcd(a, n) != 1:
        return None
    x = 1
    for r in range(1, n + 1):
        x = (x * a) % n
        if x == 1:
            return r
    return None


# ---------------------------------------------------------------- GF(2)
def dot2(a: int, b: int) -> int:
    return bin(a & b).count("1") & 1


# ---------------------------------------------------------------- statistics
def erfc(x: float) -> float:
    return math.erfc(x)


def monobit_pvalue(bits: Sequence[int]) -> float:
    n = len(bits)
    if n == 0:
        return float("nan")
    s = sum(1 if b else -1 for b in bits)
    return math.erfc(abs(s) / math.sqrt(2 * n))


def runs_pvalue(bits: Sequence[int]) -> float:
    n = len(bits)
    if n < 2:
        return float("nan")
    pi = sum(bits) / n
    if abs(pi - 0.5) >= 2 / math.sqrt(n):
        return 0.0
    runs = 1 + sum(1 for i in range(1, n) if bits[i] != bits[i - 1])
    num = abs(runs - 2 * n * pi * (1 - pi))
    den = 2 * math.sqrt(2 * n) * pi * (1 - pi)
    return math.erfc(num / den)


def chi_square_bytes(data: bytes) -> tuple[float, float]:
    """Chi-square statistic over byte values and an approximate p-value (Wilson–Hilferty)."""
    n = len(data)
    if n < 256:
        return float("nan"), float("nan")
    counts = np.bincount(np.frombuffer(data, dtype=np.uint8), minlength=256)
    exp = n / 256
    chi = float(((counts - exp) ** 2 / exp).sum())
    k = 255
    z = ((chi / k) ** (1 / 3) - (1 - 2 / (9 * k))) / math.sqrt(2 / (9 * k))
    p = 0.5 * math.erfc(z / math.sqrt(2))
    return chi, p


def von_neumann(bits: Sequence[int]) -> list[int]:
    out = []
    for i in range(0, len(bits) - 1, 2):
        a, b = bits[i], bits[i + 1]
        if a != b:
            out.append(a)
    return out


def toeplitz_extract(bits: Sequence[int], out_len: int, seed_bits: Sequence[int]) -> list[int]:
    """Two-universal Toeplitz hashing: out = T x over GF(2), T defined by n+m-1 seed bits."""
    n = len(bits)
    if out_len <= 0 or n == 0:
        return []
    if len(seed_bits) < n + out_len - 1:
        raise ValueError("Toeplitz seed too short")
    x = np.array(bits, dtype=np.uint8)
    seed = np.array(seed_bits[: n + out_len - 1], dtype=np.uint8)
    out = []
    for i in range(out_len):
        row = seed[i: i + n][::-1]
        out.append(int((row & x).sum() & 1))
    return out


def binary_entropy(p: float) -> float:
    if p <= 0 or p >= 1:
        return 0.0
    return -p * math.log2(p) - (1 - p) * math.log2(1 - p)


def bits_to_hex(bits: Sequence[int]) -> str:
    out = []
    for i in range(0, len(bits) - len(bits) % 8, 8):
        v = 0
        for b in bits[i:i + 8]:
            v = (v << 1) | int(b)
        out.append(f"{v:02x}")
    return "".join(out)


def bits_to_bytes(bits: Sequence[int]) -> bytes:
    return bytes.fromhex(bits_to_hex(bits)) if len(bits) >= 8 else b""


def fit_exponential(t: Sequence[float], y: Sequence[float]) -> tuple[float, float, float]:
    """Fit y = A exp(-t/T) + B by scanning T and solving (A, B) by least squares."""
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    span = max(t.max() - t.min(), 1e-12)
    best = (np.inf, 0.0, 0.0, span)
    for T in np.geomspace(span / 50, span * 50, 600):
        M = np.vstack([np.exp(-t / T), np.ones_like(t)]).T
        coef, *_ = np.linalg.lstsq(M, y, rcond=None)
        err = float(((M @ coef - y) ** 2).sum())
        if err < best[0]:
            best = (err, float(coef[0]), float(coef[1]), float(T))
    return best[3], best[1], best[2]


def fit_damped_cosine(t: Sequence[float], y: Sequence[float], freq: float) -> tuple[float, float, float, float]:
    """Fit y = exp(-t/T) (C cos 2πft + S sin 2πft) + B; returns (T, amplitude, phase, B)."""
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    span = max(t.max() - t.min(), 1e-12)
    best = (np.inf, span, 0.0, 0.0, 0.0)
    for T in np.geomspace(span / 50, span * 50, 600):
        env = np.exp(-t / T)
        M = np.vstack([env * np.cos(2 * np.pi * freq * t), env * np.sin(2 * np.pi * freq * t), np.ones_like(t)]).T
        coef, *_ = np.linalg.lstsq(M, y, rcond=None)
        err = float(((M @ coef - y) ** 2).sum())
        if err < best[0]:
            amp = math.hypot(coef[0], coef[1])
            best = (err, float(T), float(amp), float(math.atan2(-coef[1], coef[0])), float(coef[2]))
    return best[1], best[2], best[3], best[4]


def parse_bitstring_list(text: str, n: int) -> list[int]:
    out = []
    for tok in text.replace(";", ",").split(","):
        tok = tok.strip()
        if not tok:
            continue
        if any(ch not in "01" for ch in tok) or len(tok) != n:
            raise ValueError(f"marked state {tok!r} must be {n} bits of 0/1")
        out.append(int(tok, 2))
    return out


def rng_from(seed: Optional[int]) -> np.random.Generator:
    return np.random.default_rng(None if seed is None or seed < 0 else seed)
