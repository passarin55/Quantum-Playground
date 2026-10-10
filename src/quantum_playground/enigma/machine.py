"""Historical Enigma machines (Enigma I / M3, Kriegsmarine M4) and the 4-letter Mini-Enigma.

Everything is data-driven: rotors, reflectors and the stepping mechanism are
public historical specifications.  The machine exposes both the classical
keypress interface and *per-keypress permutations* (``letter_permutation``)
which the quantum oracle builders compile into reversible circuits.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional, Sequence

ABC = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# name: (wiring, turnover letters).  Turnover = window letter *before* the step
# that carries the next rotor.
ROTORS: dict[str, tuple[str, str]] = {
    "I": ("EKMFLGDQVZNTOWYHXUSPAIBRCJ", "Q"),
    "II": ("AJDKSIRUXBLHWTMCQGZNPYFVOE", "E"),
    "III": ("BDFHJLCPRTXVZNYEIWGAKMUSQO", "V"),
    "IV": ("ESOVPZJAYQUIRHXLNFTGKDCMWB", "J"),
    "V": ("VZBRGITYUPSDNHLXAWMJQOFECK", "Z"),
    "VI": ("JPGVOUMFYQBENHZRDKASXLICTW", "ZM"),
    "VII": ("NZJHGRCXMYSWBOUFAIVLPEKQDT", "ZM"),
    "VIII": ("FKQHTLXOCBJSPDZRAMEWNIUYGV", "ZM"),
    # M4 thin "Zusatzwalzen" — never step
    "BETA": ("LEYJVCNIXWPBQMDRTAKZGFUHOS", ""),
    "GAMMA": ("FSOKANUERHMBTIYCWLQPZXVGJD", ""),
}
REFLECTORS: dict[str, str] = {
    "A": "EJMZALYXVBWFCRQUONTSPIKHGD",
    "B": "YRUHQSLDPXNGOKMIEBFZCWVJAT",
    "C": "FVPJIAOYEDRZXWGCTKUQSBNMHL",
    "B-THIN": "ENKQAUYWJICOPBLMDXZVFTHRGS",
    "C-THIN": "RDOBJNTKVEHMLFCWZAXGYIPSUQ",
}
M3_ROTORS = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII")
M4_GREEK = ("BETA", "GAMMA")


def letters(text: str) -> str:
    """Upper-case A–Z only (spaces, digits and punctuation are not transmitted)."""
    return "".join(c for c in text.upper() if "A" <= c <= "Z")


def groups(text: str, size: int = 5) -> str:
    return " ".join(text[i:i + size] for i in range(0, len(text), size))


def parse_plugboard(spec: str | Sequence[str], max_pairs: int = 13) -> tuple[str, ...]:
    if isinstance(spec, str):
        pairs = tuple(x.upper() for x in spec.replace("-", " ").replace(",", " ").split() if x)
    else:
        pairs = tuple(x.upper() for x in spec)
    if len(pairs) > max_pairs:
        raise ValueError(f"At most {max_pairs} plugboard pairs")
    used: set[str] = set()
    for pair in pairs:
        if len(pair) != 2 or pair[0] == pair[1] or any(ch not in ABC for ch in pair):
            raise ValueError(f"Invalid plugboard pair {pair!r}; use e.g. 'AB CD EF'")
        if pair[0] in used or pair[1] in used:
            raise ValueError(f"Plugboard letter reused in {pair!r}")
        used.update(pair)
    return pairs


def _parse_rotors(spec) -> tuple[str, ...]:
    if isinstance(spec, str):
        spec = spec.replace(",", " ").split()
    return tuple(s.upper() for s in spec)


def _parse_rings(spec) -> tuple[int, ...]:
    if isinstance(spec, str):
        items = spec.replace(",", " ").split()
        if len(items) == 1 and items[0].isalpha():
            items = list(items[0])
        out = []
        for it in items:
            out.append(ABC.index(it.upper()) + 1 if it.isalpha() else int(it))
        return tuple(out)
    return tuple(int(x) for x in spec)


@dataclass(frozen=True)
class EnigmaConfig:
    """Machine settings.  Rotors/rings/positions are listed left → right.

    M3: 3 rotors from I–VIII, reflector A/B/C.
    M4: 4 rotors — a Greek rotor (BETA/GAMMA) then 3 from I–VIII, thin reflector.
    """

    rotors: tuple[str, ...] = ("I", "II", "III")
    rings: tuple[int, ...] = (1, 1, 1)
    positions: str = "AAA"
    reflector: str = "B"
    plugboard: tuple[str, ...] = ()

    @staticmethod
    def create(rotors="I II III", rings="1 1 1", positions="AAA", reflector="B", plugboard="") -> "EnigmaConfig":
        cfg = EnigmaConfig(_parse_rotors(rotors), _parse_rings(rings), positions.upper().replace(" ", ""),
                           reflector.upper(), parse_plugboard(plugboard))
        cfg.validate()
        return cfg

    @property
    def model(self) -> str:
        return "M4" if len(self.rotors) == 4 else "M3"

    def validate(self) -> None:
        k = len(self.rotors)
        if k not in (3, 4):
            raise ValueError("Use 3 rotors (M3) or 4 rotors (M4)")
        if len(self.rings) != k or len(self.positions) != k:
            raise ValueError(f"Need {k} ring settings and {k} window letters")
        if any(r < 1 or r > 26 for r in self.rings):
            raise ValueError("Ring settings are 1..26 (or A..Z)")
        if any(p not in ABC for p in self.positions):
            raise ValueError("Window positions must be letters A–Z")
        moving = self.rotors[-3:]
        if any(r not in M3_ROTORS for r in moving):
            raise ValueError(f"Stepping rotors must be from {', '.join(M3_ROTORS)}")
        if len(set(moving)) != 3:
            raise ValueError("A rotor cannot be used twice")
        if k == 4:
            if self.rotors[0] not in M4_GREEK:
                raise ValueError("M4 leftmost rotor must be BETA or GAMMA")
            if self.reflector not in ("B-THIN", "C-THIN"):
                raise ValueError("M4 requires reflector B-THIN or C-THIN")
        elif self.reflector not in ("A", "B", "C"):
            raise ValueError("M3 reflector must be A, B or C")
        parse_plugboard(self.plugboard)

    def with_positions(self, positions: str) -> "EnigmaConfig":
        return replace(self, positions=positions)

    def describe(self) -> str:
        rings = " ".join(f"{r:02d}" for r in self.rings)
        return (f"{self.model} | UKW {self.reflector} | Walzen {' '.join(self.rotors)} | Ringe {rings} | "
                f"Grund {self.positions} | Stecker {' '.join(self.plugboard) or '-'}")

    def to_dict(self) -> dict:
        return {"rotors": list(self.rotors), "rings": list(self.rings), "positions": self.positions,
                "reflector": self.reflector, "plugboard": list(self.plugboard)}

    @staticmethod
    def from_dict(d: dict) -> "EnigmaConfig":
        return EnigmaConfig.create(d.get("rotors", "I II III"), d.get("rings", "1 1 1"),
                                   d.get("positions", "AAA"), d.get("reflector", "B"),
                                   " ".join(d.get("plugboard", [])) if not isinstance(d.get("plugboard"), str)
                                   else d.get("plugboard", ""))


@dataclass
class TraceStep:
    stage: str
    letter: str


class Enigma:
    def __init__(self, config: EnigmaConfig):
        config.validate()
        self.config = config
        self.names = config.rotors
        self.fwd = [[ABC.index(c) for c in ROTORS[r][0]] for r in self.names]
        self.inv = []
        for w in self.fwd:
            inv = [0] * 26
            for i, o in enumerate(w):
                inv[o] = i
            self.inv.append(inv)
        self.notches = [{ABC.index(ch) for ch in ROTORS[r][1]} for r in self.names]
        self.reflector = [ABC.index(c) for c in REFLECTORS[config.reflector]]
        self.rings = [r - 1 for r in config.rings]
        self.pos = [ABC.index(c) for c in config.positions]
        self.plug = list(range(26))
        for a, b in config.plugboard:
            ia, ib = ABC.index(a), ABC.index(b)
            self.plug[ia], self.plug[ib] = ib, ia

    # --- mechanics -----------------------------------------------------------
    def step(self) -> None:
        """Ratchet stepping incl. the middle-rotor double step (rightmost 3 rotors only)."""
        k = len(self.pos)
        L, M, R = k - 3, k - 2, k - 1
        mid_at_notch = self.pos[M] in self.notches[M]
        right_at_notch = self.pos[R] in self.notches[R]
        if mid_at_notch:
            self.pos[L] = (self.pos[L] + 1) % 26
        if mid_at_notch or right_at_notch:
            self.pos[M] = (self.pos[M] + 1) % 26
        self.pos[R] = (self.pos[R] + 1) % 26

    def window(self) -> str:
        return "".join(ABC[p] for p in self.pos)

    def _through(self, c: int, trace: Optional[list] = None) -> int:
        k = len(self.pos)
        c = self.plug[c]
        if trace is not None:
            trace.append(TraceStep("plugboard", ABC[c]))
        for i in range(k - 1, -1, -1):
            off = self.pos[i] - self.rings[i]
            c = (self.fwd[i][(c + off) % 26] - off) % 26
            if trace is not None:
                trace.append(TraceStep(f"rotor {self.names[i]} →", ABC[c]))
        c = self.reflector[c]
        if trace is not None:
            trace.append(TraceStep(f"reflector {self.config.reflector}", ABC[c]))
        for i in range(k):
            off = self.pos[i] - self.rings[i]
            c = (self.inv[i][(c + off) % 26] - off) % 26
            if trace is not None:
                trace.append(TraceStep(f"rotor {self.names[i]} ←", ABC[c]))
        c = self.plug[c]
        if trace is not None:
            trace.append(TraceStep("plugboard", ABC[c]))
        return c

    def keypress(self, ch: str, trace: Optional[list] = None) -> str:
        if ch not in ABC:
            raise ValueError("Only A–Z can be typed")
        self.step()
        return ABC[self._through(ABC.index(ch), trace)]

    def current_permutation(self) -> tuple[int, ...]:
        """Letter permutation for the *current* rotor positions (no stepping)."""
        return tuple(self._through(i) for i in range(26))

    def transform(self, text: str, keep_nonletters: bool = False) -> str:
        if not keep_nonletters:
            return "".join(self.keypress(c) for c in letters(text))
        return "".join(self.keypress(c) if c in ABC else c for c in text.upper())

    def keypress_trace(self, ch: str) -> dict:
        before = self.window()
        trace: list[TraceStep] = []
        out = self.keypress(ch, trace)
        return {"input": ch, "output": out, "window_before": before, "window_after": self.window(),
                "path": [{"stage": t.stage, "letter": t.letter} for t in trace]}


def encrypt(text: str, config: EnigmaConfig, keep_nonletters: bool = False) -> str:
    """Encrypt == decrypt (the machine is an involution for fixed settings)."""
    return Enigma(config).transform(text, keep_nonletters)


def letter_permutations(config: EnigmaConfig, length: int) -> list[tuple[int, ...]]:
    """Permutation applied at each of the first ``length`` keypresses."""
    e = Enigma(config)
    out = []
    for _ in range(length):
        e.step()
        out.append(e.current_permutation())
    return out


# =============================================================================
# Mini-Enigma: 4-letter alphabet, 3 rotors, reflector, double stepping (from v6/v8)
# =============================================================================
MINI_ABC = "ABCD"
MINI_ROTORS = ((1, 3, 2, 0), (3, 0, 2, 1), (2, 1, 3, 0))
MINI_REFLECTOR = (3, 2, 1, 0)
MINI_NOTCH = 2


def _inv(p: Sequence[int]) -> tuple[int, ...]:
    out = [0] * len(p)
    for i, v in enumerate(p):
        out[v] = i
    return tuple(out)


def mini_positions(start: int, char_index: int, left: int = 0, middle: int = 0) -> tuple[int, int, int]:
    w = [left, middle, start]
    for _ in range(char_index + 1):
        mid = w[1] == MINI_NOTCH
        right = w[2] == MINI_NOTCH
        if mid:
            w[0] = (w[0] + 1) % 4
        if mid or right:
            w[1] = (w[1] + 1) % 4
        w[2] = (w[2] + 1) % 4
    return tuple(w)


def mini_permutation(start: int, char_index: int) -> tuple[int, ...]:
    pos = mini_positions(start, char_index)
    out = []
    for c in range(4):
        for r in (2, 1, 0):
            off = pos[r]
            c = (MINI_ROTORS[r][(c + off) % 4] - off) % 4
        c = MINI_REFLECTOR[c]
        for r in (0, 1, 2):
            off = pos[r]
            c = (_inv(MINI_ROTORS[r])[(c + off) % 4] - off) % 4
        out.append(c)
    return tuple(out)


def mini_encrypt(text: str, start: int) -> str:
    if not 0 <= start <= 3:
        raise ValueError("Mini-Enigma start key is 0..3")
    if any(ch not in MINI_ABC for ch in text):
        raise ValueError("Mini-Enigma alphabet is ABCD")
    return "".join(MINI_ABC[mini_permutation(start, i)[MINI_ABC.index(ch)]] for i, ch in enumerate(text))
