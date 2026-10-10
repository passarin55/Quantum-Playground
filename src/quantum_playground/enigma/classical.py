"""Classical companions to the quantum Enigma lab.

* ``window_scan`` — the v6–v8 "classical full 26^3 search" of rotor start
  windows (all other settings known), now vectorised with numpy so every
  window is tested in one pass (M4: 26^4 windows).  This is the honest
  baseline the Grover demo is compared against.
* ``KeySheet`` — generate a random daily key sheet from any bit source
  (OS randomness or measured quantum random bits from the QRNG experiment),
  using rejection sampling so no modulo bias is introduced.
"""
from __future__ import annotations

import itertools
import secrets
from dataclasses import dataclass
from typing import Callable, Iterable, Iterator, Optional

import numpy as np

from .machine import ABC, M3_ROTORS, REFLECTORS, ROTORS, EnigmaConfig, encrypt, letters


def _vector_tables(cfg: EnigmaConfig):
    fwd = [np.array([ABC.index(c) for c in ROTORS[r][0]]) for r in cfg.rotors]
    notch = [np.array([ABC[i] in ROTORS[r][1] for i in range(26)]) for r in cfg.rotors]
    inv = []
    for f in fwd:
        x = np.zeros(26, dtype=int)
        x[f] = np.arange(26)
        inv.append(x)
    refl = np.array([ABC.index(c) for c in REFLECTORS[cfg.reflector]])
    plug = np.arange(26)
    for a, b in cfg.plugboard:
        ia, ib = ABC.index(a), ABC.index(b)
        plug[ia], plug[ib] = ib, ia
    return fwd, inv, notch, refl, plug


def window_scan(config: EnigmaConfig, ciphertext: str, crib: str, max_results: int = 50) -> dict:
    """Test every rotor start window against a known plaintext prefix (crib)."""
    config.validate()
    ct, crib = letters(ciphertext), letters(crib)
    if not crib or len(crib) > len(ct):
        raise ValueError("Provide ciphertext and a known-plaintext prefix no longer than it")
    k = len(config.rotors)
    fwd, inv, notch, refl, plug = _vector_tables(config)
    rings = np.array([r - 1 for r in config.rings])
    grid = np.array(list(itertools.product(range(26), repeat=k)), dtype=int)
    pos = grid.copy()
    alive = np.ones(len(pos), dtype=bool)
    L, M, R = k - 3, k - 2, k - 1
    for p_ch, c_ch in zip(crib, ct):
        mid = notch[M][pos[:, M]]
        right = notch[R][pos[:, R]]
        pos[:, L] = np.where(mid, (pos[:, L] + 1) % 26, pos[:, L])
        pos[:, M] = np.where(mid | right, (pos[:, M] + 1) % 26, pos[:, M])
        pos[:, R] = (pos[:, R] + 1) % 26
        c = np.full(len(pos), plug[ABC.index(p_ch)])
        for r in range(k - 1, -1, -1):
            off = (pos[:, r] - rings[r]) % 26
            c = (fwd[r][(c + off) % 26] - off) % 26
        c = refl[c]
        for r in range(k):
            off = (pos[:, r] - rings[r]) % 26
            c = (inv[r][(c + off) % 26] - off) % 26
        c = plug[c]
        alive &= c == ABC.index(c_ch)
    idx = np.nonzero(alive)[0]
    results = []
    for i in idx[:max_results]:
        window = "".join(ABC[v] for v in grid[i])
        cfg = config.with_positions(window)
        results.append({"positions": window, "plaintext": encrypt(ct, cfg)})
    return {"tested": int(len(grid)), "matches": int(len(idx)), "results": results,
            "truncated": bool(len(idx) > max_results), "crib_length": len(crib)}


# ---------------------------------------------------------------- key sheets
class BitSource:
    """Wraps an iterator of bits; falls back to the OS CSPRNG when exhausted if allowed."""

    def __init__(self, bits: Optional[Iterable[int]] = None, fallback: bool = True):
        self._it: Iterator[int] = iter(bits) if bits is not None else iter(())
        self.fallback = fallback
        self.used_quantum = 0
        self.used_fallback = 0

    def bit(self) -> int:
        try:
            b = int(next(self._it)) & 1
            self.used_quantum += 1
            return b
        except StopIteration:
            if not self.fallback:
                raise RuntimeError("Quantum random bits exhausted") from None
            self.used_fallback += 1
            return secrets.randbits(1)

    def below(self, n: int) -> int:
        """Uniform integer in [0, n) by rejection sampling (no modulo bias)."""
        if n <= 1:
            return 0
        bits = (n - 1).bit_length()
        while True:
            v = 0
            for _ in range(bits):
                v = (v << 1) | self.bit()
            if v < n:
                return v

    def shuffle(self, items: list) -> list:
        items = list(items)
        for i in range(len(items) - 1, 0, -1):
            j = self.below(i + 1)
            items[i], items[j] = items[j], items[i]
        return items


@dataclass
class KeySheet:
    days: list[dict]
    source: dict

    def to_text(self) -> str:
        lines = ["Tag | Walzenlage   | Ringstellung | Steckerverbindungen            | Grund",
                 "----+-------------+--------------+--------------------------------+------"]
        for d in self.days:
            lines.append(f"{d['day']:>3} | {' '.join(d['rotors']):<11} | {' '.join(f'{r:02d}' for r in d['rings']):<12} | "
                         f"{' '.join(d['plugboard']):<30} | {d['positions']}")
        return "\n".join(lines)


def generate_keysheet(days: int = 7, source: Optional[BitSource] = None, plug_pairs: int = 10,
                      reflector: str = "B") -> KeySheet:
    src = source or BitSource()
    out = []
    for day in range(1, days + 1):
        rotors = src.shuffle(list(M3_ROTORS[:5]))[:3]
        rings = [src.below(26) + 1 for _ in range(3)]
        letters_ = src.shuffle(list(ABC))
        pairs = sorted("".join(sorted(letters_[2 * i:2 * i + 2])) for i in range(plug_pairs))
        positions = "".join(ABC[src.below(26)] for _ in range(3))
        cfg = EnigmaConfig.create(" ".join(rotors), rings, positions, reflector, " ".join(pairs))
        out.append({"day": day, "rotors": list(cfg.rotors), "rings": list(cfg.rings),
                    "plugboard": list(cfg.plugboard), "positions": cfg.positions, "reflector": reflector})
    return KeySheet(out, {"quantum_bits_used": src.used_quantum, "fallback_bits_used": src.used_fallback})
