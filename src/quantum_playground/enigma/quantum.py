"""Reversible Enigma oracles and Grover key-search circuits (v9 redesign of v6–v8).

A *restricted* key search: 2^b candidate machine settings (by default the
right-rotor start window, as in v5–v8) are indexed by a b-qubit key register.
The oracle encrypts a coherent symbol register with the key-dependent Enigma
permutation **for every one of the 32 basis states** (26 letters + 6 fixed
unused codes), applies a phase when all crib letters match, then uncomputes.
No table of "good keys" or crib outputs is placed in the circuit.

Three synthesis strategies (all verified exhaustively by
``verify_keyed_encryption``):

``staged``    plugboard, each rotor, reflector and inverse rotors as separate
              permutations; a stage gets key controls only when it actually
              differs between candidates (v6 idea, MMD-synthesised in v9).
``factored``  v7 algebra: rotor wirings are applied *without* key controls,
              and only the merged modular shifts S(t): x -> x+t (mod 26) are
              keyed, using affine one-bit controls where possible.
``compiled``  the whole keypress permutation for each key is synthesised as a
              single 5-bit reversible function (smallest circuits; the
              classical compile cost scales with the number of candidates, so
              there is no asymptotic advantage — documented, not hidden).

Honest boundary (unchanged since v5): these are educational circuits.  Even a
4-candidate, 1-letter oracle compiles to hundreds–thousands of native
two-qubit gates on today's hardware, so expect noisy results on a real QPU and
no speed-up over a classical scan.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Optional, Sequence

from ..core.circuit import Circuit
from ..core.reversible import permutation_of
from ..core.synthesis import apply_permutation, extend_permutation, network_cost, synthesize_permutation
from .machine import (ABC, MINI_ABC, MINI_REFLECTOR, MINI_ROTORS, REFLECTORS, ROTORS, EnigmaConfig, Enigma,
                      letters, mini_permutation, mini_positions, encrypt, mini_encrypt)

SYNTHESIS_MODES = ("auto", "compiled", "staged", "factored")
ORACLE_MODES = ("phase", "flag")


def _inverse(p: Sequence[int]) -> tuple[int, ...]:
    out = [0] * len(p)
    for i, v in enumerate(p):
        out[v] = i
    return tuple(out)


def _compose(*perms: Sequence[int]) -> tuple[int, ...]:
    """Apply perms left to right: result[x] = p_last(...p_first(x))."""
    n = len(perms[0])
    out = list(range(n))
    for p in perms:
        out = [p[v] for v in out]
    return tuple(out)


def _shift(t: int, size: int) -> tuple[int, ...]:
    return tuple((x + t) % size for x in range(size))


# =============================================================================
# problem description
# =============================================================================
@dataclass
class KeySearchProblem:
    """Everything the circuit builders need — derived only from public wiring."""

    model: str                         # "historical" | "mini"
    alphabet: str
    width: int                         # symbol register bits
    key_bits: int
    plaintext: str
    ciphertext: str
    candidate_labels: list[str]
    # stages[i][k] = list of (name, permutation over alphabet) for crib letter i, key k
    stages: list[list[list[tuple[str, tuple[int, ...]]]]]
    base_config: Optional[EnigmaConfig] = None
    candidates: list = field(default_factory=list)

    @property
    def num_candidates(self) -> int:
        return 1 << self.key_bits

    def letter_permutation(self, i: int, k: int) -> tuple[int, ...]:
        return _compose(*[p for _, p in self.stages[i][k]])

    def classical_matches(self) -> list[int]:
        """Classical check of every candidate (for reporting & iteration choice only)."""
        a = self.alphabet
        out = []
        for k in range(self.num_candidates):
            if all(self.letter_permutation(i, k)[a.index(p)] == a.index(c)
                   for i, (p, c) in enumerate(zip(self.plaintext, self.ciphertext))):
                out.append(k)
        return out

    def decode(self, key_index: int, message: str) -> str:
        if self.model == "mini":
            return mini_encrypt(message, key_index)
        return encrypt(message, self.candidates[key_index])

    def describe(self) -> dict:
        return {"model": self.model, "key_bits": self.key_bits, "candidates": self.candidate_labels,
                "plaintext": self.plaintext, "ciphertext": self.ciphertext, "alphabet_size": len(self.alphabet),
                "symbol_qubits": self.width}


def _historical_stages(cfg: EnigmaConfig, length: int) -> list[list[tuple[str, tuple[int, ...]]]]:
    e = Enigma(cfg)
    out = []
    for _ in range(length):
        e.step()
        k = len(e.pos)
        st: list[tuple[str, tuple[int, ...]]] = [("plug", tuple(e.plug))]
        for r in range(k - 1, -1, -1):
            off = e.pos[r] - e.rings[r]
            st.append((f"W{e.names[r]}+", tuple((e.fwd[r][(x + off) % 26] - off) % 26 for x in range(26))))
        st.append(("UKW", tuple(e.reflector)))
        for r in range(k):
            off = e.pos[r] - e.rings[r]
            st.append((f"W{e.names[r]}-", tuple((e.inv[r][(x + off) % 26] - off) % 26 for x in range(26))))
        st.append(("plug", tuple(e.plug)))
        assert _compose(*[p for _, p in st]) == e.current_permutation()
        out.append(st)
    return out


def historical_problem(base: EnigmaConfig, plaintext: str, ciphertext: str, key_bits: int = 2,
                       vary: str = "right", first: str = "A") -> KeySearchProblem:
    """Candidates differ only in one rotor's start window: first, first+1, ..."""
    base.validate()
    plaintext, ciphertext = letters(plaintext), letters(ciphertext)
    if not 1 <= key_bits <= 4:
        raise ValueError("Historical search: 1-4 key qubits (2-16 candidates)")
    if not 1 <= len(plaintext) <= 3 or len(plaintext) != len(ciphertext):
        raise ValueError("Use a 1-3 letter crib with an equal-length ciphertext fragment")
    slot = {"right": -1, "middle": -2, "left": -3}[vary]
    start = ABC.index(first.upper())
    if start + (1 << key_bits) > 26:
        raise ValueError("Candidate windows would run past Z; choose an earlier first letter")
    cands, labels, stages = [], [], []
    for k in range(1 << key_bits):
        pos = list(base.positions)
        pos[len(pos) + slot] = ABC[start + k]
        cfg = base.with_positions("".join(pos))
        cands.append(cfg)
        labels.append(cfg.positions)
        stages.append(_historical_stages(cfg, len(plaintext)))
    per_letter = [[stages[k][i] for k in range(1 << key_bits)] for i in range(len(plaintext))]
    return KeySearchProblem("historical", ABC, 5, key_bits, plaintext, ciphertext, labels, per_letter, base, cands)


def mini_problem(plaintext: str, ciphertext: str) -> KeySearchProblem:
    plaintext, ciphertext = plaintext.upper(), ciphertext.upper()
    if any(c not in MINI_ABC for c in plaintext + ciphertext):
        raise ValueError("Mini-Enigma uses the alphabet ABCD")
    if not 1 <= len(plaintext) <= 3 or len(plaintext) != len(ciphertext):
        raise ValueError("Mini-Enigma: 1-3 crib letters")
    per_letter = []
    for i in range(len(plaintext)):
        row = []
        for k in range(4):
            pos = mini_positions(k, i)
            st = []
            for r in (2, 1, 0):
                off = pos[r]
                st.append((f"R{r}+", tuple((MINI_ROTORS[r][(x + off) % 4] - off) % 4 for x in range(4))))
            st.append(("UKW", tuple(MINI_REFLECTOR)))
            for r in (0, 1, 2):
                off = pos[r]
                inv = _inverse(MINI_ROTORS[r])
                st.append((f"R{r}-", tuple((inv[(x + off) % 4] - off) % 4 for x in range(4))))
            assert _compose(*[p for _, p in st]) == mini_permutation(k, i)
            row.append(st)
        per_letter.append(row)
    return KeySearchProblem("mini", MINI_ABC, 2, 2, plaintext, ciphertext, [str(k) for k in range(4)], per_letter)


# =============================================================================
# keyed permutation emitters
# =============================================================================
def _keyed_stage(qc: Circuit, key: Sequence[int], sym: Sequence[int], perms: Sequence[tuple[int, ...]],
                 width: int, method: str = "auto") -> None:
    """Apply perms[k] to ``sym`` when key == k (perms padded to 2^width)."""
    perms = [extend_permutation(p, width) for p in perms]
    if all(p == perms[0] for p in perms):
        apply_permutation(qc, sym, perms[0], method=method)
        return
    nb = len(key)
    # option A: every key separately controlled
    cost_a = sum(network_cost(synthesize_permutation(p, method, nb), nb) for p in perms)
    # option B: base unconditionally + controlled corrections
    base = perms[0]
    inv = _inverse(base)
    corr = [_compose(inv, p) for p in perms]  # p = base then corr
    cost_b = network_cost(synthesize_permutation(base, method)) + sum(
        network_cost(synthesize_permutation(c, method, nb), nb) for c in corr[1:] if c != tuple(range(len(c))))
    if cost_b < cost_a:
        apply_permutation(qc, sym, base, method=method)
        for k, c in enumerate(corr):
            if k and c != tuple(range(len(c))):
                apply_permutation(qc, sym, c, controls=key, ctrl_state=k, method=method)
    else:
        for k, p in enumerate(perms):
            if p != tuple(range(len(p))):
                apply_permutation(qc, sym, p, controls=key, ctrl_state=k, method=method)


def _keyed_shift(qc: Circuit, key: Sequence[int], sym: Sequence[int], shifts: Sequence[int], size: int,
                 width: int) -> None:
    """S(shifts[key]) using affine single-bit controls when the shifts allow it."""
    shifts = [s % size for s in shifts]
    nb = len(key)
    base = shifts[0]
    weights = [(shifts[1 << j] - base) % size for j in range(nb)]
    affine = all((base + sum(weights[j] for j in range(nb) if (k >> j) & 1)) % size == s
                 for k, s in enumerate(shifts))
    if base:
        apply_permutation(qc, sym, extend_permutation(_shift(base, size), width))
    if affine:
        for j, w in enumerate(weights):
            if w:
                apply_permutation(qc, sym, extend_permutation(_shift(w, size), width), controls=[key[j]])
    else:
        for k in range(1, 1 << nb):
            d = (shifts[k] - base) % size
            if d:
                apply_permutation(qc, sym, extend_permutation(_shift(d, size), width), controls=key, ctrl_state=k)


def _factored_letter(qc: Circuit, problem: KeySearchProblem, i: int, key, sym) -> None:
    if problem.model != "historical":
        raise ValueError("factored synthesis is defined for the 26-letter machine")
    cfgs = problem.candidates
    engines = []
    for cfg in cfgs:
        e = Enigma(cfg)
        for _ in range(i + 1):
            e.step()
        engines.append(e)
    e0 = engines[0]
    nrot = len(e0.pos)
    order = list(range(nrot - 1, -1, -1))     # right → left
    offs = [[(e.pos[r] - e.rings[r]) % 26 for r in order] for e in engines]   # per key
    wires = [tuple(e0.fwd[r]) for r in order]
    invs = [tuple(e0.inv[r]) for r in order]
    w = problem.width
    apply_permutation(qc, sym, extend_permutation(tuple(e0.plug), w))
    prev = [0] * len(engines)
    for j in range(nrot):
        _keyed_shift(qc, key, sym, [o[j] - p for o, p in zip(offs, prev)], 26, w)
        apply_permutation(qc, sym, extend_permutation(wires[j], w))
        prev = [o[j] for o in offs]
    _keyed_shift(qc, key, sym, [-p for p in prev], 26, w)
    apply_permutation(qc, sym, extend_permutation(tuple(e0.reflector), w))
    prev = [0] * len(engines)
    for j in range(nrot - 1, -1, -1):
        _keyed_shift(qc, key, sym, [o[j] - p for o, p in zip(offs, prev)], 26, w)
        apply_permutation(qc, sym, extend_permutation(invs[j], w))
        prev = [o[j] for o in offs]
    _keyed_shift(qc, key, sym, [-p for p in prev], 26, w)
    apply_permutation(qc, sym, extend_permutation(tuple(e0.plug), w))


def keyed_encryption(problem: KeySearchProblem, i: int, synthesis: str = "compiled") -> Circuit:
    """Circuit on (key, symbol) applying the crib-letter-i Enigma permutation of candidate |key>."""
    qc = Circuit(name=f"enigma_letter_{i}_{synthesis}")
    key = qc.add_qreg("k", problem.key_bits)
    sym = qc.add_qreg("s", problem.width)
    nk = problem.num_candidates
    if synthesis == "compiled":
        _keyed_stage(qc, list(key), list(sym), [problem.letter_permutation(i, k) for k in range(nk)], problem.width)
    elif synthesis == "staged":
        nstages = len(problem.stages[i][0])
        for s in range(nstages):
            _keyed_stage(qc, list(key), list(sym), [problem.stages[i][k][s][1] for k in range(nk)], problem.width)
    elif synthesis == "factored":
        _factored_letter(qc, problem, i, list(key), list(sym))
    else:
        raise ValueError(f"synthesis must be one of {SYNTHESIS_MODES[1:]}")
    return qc


def estimated_cost(qc: Circuit) -> int:
    """Decomposition-aware cost: an MCT gate with k controls costs ~ 2^(k+1) - 3 (NCV model).

    Raw instruction counts mislead because wide multi-controlled gates expand into many native
    two-qubit gates; this estimate tracks IBM-transpiled two-qubit counts far better.
    """
    from ..core.synthesis import ncv_cost
    return sum(ncv_cost(ins.num_controls) for ins in qc.instructions if ins.spec.unitary)


def choose_synthesis(problem: KeySearchProblem) -> str:
    modes = ["compiled", "staged"] + (["factored"] if problem.model == "historical" else [])
    return min(modes, key=lambda m: sum(estimated_cost(keyed_encryption(problem, i, m))
                                        for i in range(len(problem.plaintext))))


def verify_keyed_encryption(problem: KeySearchProblem, synthesis: str) -> None:
    """Exhaustive classical check: every key, every one of the 2^width symbol inputs."""
    for i in range(len(problem.plaintext)):
        qc = keyed_encryption(problem, i, synthesis)
        sym = list(qc.qreg("s"))
        for k in range(problem.num_candidates):
            got = permutation_of(qc, sym, fixed=k)
            want = extend_permutation(problem.letter_permutation(i, k), problem.width)
            if got != want:
                raise AssertionError(f"letter {i}, key {k}: circuit permutation differs from the machine")


# =============================================================================
# Grover circuit
# =============================================================================
def optimal_iterations(n_candidates: int, n_solutions: int = 1) -> int:
    if n_solutions <= 0 or n_solutions >= n_candidates:
        return 0
    theta = math.asin(math.sqrt(n_solutions / n_candidates))
    return max(0, round(math.pi / (4 * theta) - 0.5))


def success_probability(n_candidates: int, n_solutions: int, iterations: int) -> float:
    if n_solutions <= 0:
        return 0.0
    theta = math.asin(math.sqrt(min(1.0, n_solutions / n_candidates)))
    return math.sin((2 * iterations + 1) * theta) ** 2


def _diffuser(qc: Circuit, key: Sequence[int]) -> None:
    qc.h(list(key))
    qc.phase_flip_on(list(key), 0)
    qc.h(list(key))


def build_grover_circuit(problem: KeySearchProblem, iterations: Optional[int] = None,
                         synthesis: str = "auto", oracle: str = "phase", measure: bool = True) -> Circuit:
    if synthesis == "auto":
        synthesis = choose_synthesis(problem)
    if synthesis not in SYNTHESIS_MODES[1:]:
        raise ValueError(f"synthesis must be one of {SYNTHESIS_MODES}")
    if oracle not in ORACLE_MODES:
        raise ValueError(f"oracle must be one of {ORACLE_MODES}")
    if iterations is None:
        iterations = optimal_iterations(problem.num_candidates, 1)
    if not 0 <= iterations <= 6:
        raise ValueError("Grover iterations: 0..6")
    L = len(problem.plaintext)
    a = problem.alphabet
    qc = Circuit(name=f"enigma_grover_{problem.model}_{synthesis}_{oracle}")
    key = qc.add_qreg("k", problem.key_bits)
    syms = [qc.add_qreg(f"s{i}", problem.width) for i in range(L)]
    flags = qc.add_qreg("f", L) if oracle == "flag" else None
    out = qc.add_creg("key", problem.key_bits) if measure else None
    enc = [keyed_encryption(problem, i, synthesis) for i in range(L)]

    def load(i: int) -> None:
        v = a.index(problem.plaintext[i])
        for j, q in enumerate(syms[i]):
            if (v >> j) & 1:
                qc.x(q)

    def encrypt_letter(i: int, inverse: bool = False) -> None:
        qc.compose(enc[i].inverse() if inverse else enc[i], qubits=list(key) + list(syms[i]))

    def target_conj(i: int) -> None:
        c = a.index(problem.ciphertext[i])
        for j, q in enumerate(syms[i]):
            if not (c >> j) & 1:
                qc.x(q)

    qc.h(list(key))
    for _ in range(iterations):
        if oracle == "phase":
            # v8 direct-phase oracle: encrypt all letters, one collective phase, uncompute.
            for i in range(L):
                load(i)
                encrypt_letter(i)
                target_conj(i)
            allq = [q for s in syms for q in s]
            qc.mcz(allq[:-1], allq[-1])
            for i in reversed(range(L)):
                target_conj(i)
                encrypt_letter(i, inverse=True)
                load(i)
        else:
            assert flags is not None
            for i in range(L):        # compute flags, restoring symbols each time
                load(i)
                encrypt_letter(i)
                target_conj(i)
                qc.mcx(list(syms[i]), flags[i])
                target_conj(i)
                encrypt_letter(i, inverse=True)
                load(i)
            if L == 1:
                qc.z(flags[0])
            else:
                qc.mcz(list(flags)[:-1], flags[L - 1])
            for i in reversed(range(L)):
                load(i)
                encrypt_letter(i)
                target_conj(i)
                qc.mcx(list(syms[i]), flags[i])
                target_conj(i)
                encrypt_letter(i, inverse=True)
                load(i)
        _diffuser(qc, list(key))
    if measure:
        qc.measure(list(key), out)
    qc.metadata.update({"experiment": "enigma_grover", "synthesis": synthesis, "oracle": oracle,
                        "iterations": iterations, **problem.describe()})
    return qc
