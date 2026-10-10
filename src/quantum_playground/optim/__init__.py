"""Dependency-free classical optimisers for variational algorithms."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

import numpy as np


@dataclass
class OptimResult:
    x: list[float]
    fun: float
    nfev: int
    history: list[float] = field(default_factory=list)
    method: str = ""


def nelder_mead(f: Callable[[np.ndarray], float], x0: Sequence[float], step: float = 0.5,
                max_iter: int = 400, tol: float = 1e-8) -> OptimResult:
    """Classic Nelder–Mead simplex minimiser (adaptive coefficients not needed for small n)."""
    x0 = np.asarray(x0, dtype=float)
    n = len(x0)
    simplex = [x0] + [x0 + step * np.eye(n)[i] for i in range(n)]
    vals = [f(x) for x in simplex]
    nfev = n + 1
    history = [min(vals)]
    alpha, gamma, rho, sigma = 1.0, 2.0, 0.5, 0.5
    for _ in range(max_iter):
        order = np.argsort(vals)
        simplex = [simplex[i] for i in order]
        vals = [vals[i] for i in order]
        history.append(vals[0])
        if abs(vals[-1] - vals[0]) < tol and np.max(np.abs(np.array(simplex[1:]) - simplex[0])) < 1e-6:
            break
        centroid = np.mean(simplex[:-1], axis=0)
        xr = centroid + alpha * (centroid - simplex[-1])
        fr = f(xr); nfev += 1
        if vals[0] <= fr < vals[-2]:
            simplex[-1], vals[-1] = xr, fr
            continue
        if fr < vals[0]:
            xe = centroid + gamma * (xr - centroid)
            fe = f(xe); nfev += 1
            simplex[-1], vals[-1] = (xe, fe) if fe < fr else (xr, fr)
            continue
        xc = centroid + rho * (simplex[-1] - centroid)
        fc = f(xc); nfev += 1
        if fc < vals[-1]:
            simplex[-1], vals[-1] = xc, fc
            continue
        for i in range(1, n + 1):
            simplex[i] = simplex[0] + sigma * (simplex[i] - simplex[0])
            vals[i] = f(simplex[i]); nfev += 1
    i = int(np.argmin(vals))
    return OptimResult([float(v) for v in simplex[i]], float(vals[i]), nfev, history, "nelder-mead")


def spsa(f: Callable[[np.ndarray], float], x0: Sequence[float], iterations: int = 150, a: float = 0.2,
         c: float = 0.15, seed: Optional[int] = 7) -> OptimResult:
    """Simultaneous-perturbation stochastic approximation (noise-robust, 2 evaluations/step)."""
    rng = np.random.default_rng(seed)
    x = np.asarray(x0, dtype=float)
    A, alpha, gamma = 0.1 * iterations, 0.602, 0.101
    history, nfev = [], 0
    best = (f(x), x.copy()); nfev += 1
    for k in range(iterations):
        ak = a / (k + 1 + A) ** alpha
        ck = c / (k + 1) ** gamma
        delta = rng.choice([-1.0, 1.0], size=len(x))
        fp, fm = f(x + ck * delta), f(x - ck * delta)
        nfev += 2
        x = x - ak * (fp - fm) / (2 * ck) * delta
        val = min(fp, fm)
        history.append(val)
        if val < best[0]:
            best = (val, x.copy())
    final = f(x); nfev += 1
    if final < best[0]:
        best = (final, x.copy())
    return OptimResult([float(v) for v in best[1]], float(best[0]), nfev, history, "spsa")


def multistart(f: Callable[[np.ndarray], float], dim: int, starts: int = 6, seed: int = 3,
               low: float = 0.0, high: float = math.pi) -> OptimResult:
    rng = np.random.default_rng(seed)
    best: Optional[OptimResult] = None
    total = 0
    for _ in range(starts):
        r = nelder_mead(f, rng.uniform(low, high, size=dim), step=0.4)
        total += r.nfev
        if best is None or r.fun < best.fun:
            best = r
    assert best is not None
    best.nfev = total
    best.method = f"nelder-mead x{starts}"
    return best
