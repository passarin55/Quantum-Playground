"""Oracle algorithms: Deutsch–Jozsa, Bernstein–Vazirani, Simon, Grover (marked states and SAT)."""
from __future__ import annotations

import itertools
import math
import re
from typing import Optional

from ..core.circuit import Circuit
from ..core.statevector import exact_distribution
from .base import Chart, Experiment, Param, Plan, Report, Table, Tutor, counts_chart, register
from .library import dot2, parse_bitstring_list, rng_from


def _bits(v: int, n: int) -> str:
    return format(v, f"0{n}b")


@register
class DeutschJozsa(Experiment):
    id = "deutsch_jozsa"
    tutor = Tutor(
        concept="The Deutsch–Jozsa algorithm answers a yes/no question about a hidden function in a SINGLE query, where "
                "a classical computer might need exponentially many. It's the first proof that quantum can beat classical.",
        how_it_works="Put all input qubits in superposition, run the oracle once with the output qubit in |−⟩ so it "
                     "stamps a phase (−1)^f(x) onto each branch, then apply Hadamards again. Interference makes the "
                     "all-zeros outcome certain if f is constant, and impossible if f is balanced.",
        intuition="You don't evaluate f on every input in parallel and 'read them all' — you can only read one answer. "
                  "The trick is interference: arrange the phases so the branches you don't want cancel out and the "
                  "answer you do want adds up.",
        misconception="Quantum speedups are NOT 'try all answers at once then look'. Measurement gives one outcome. The "
                      "power is in engineering interference so the useful information survives and the rest cancels.",
        what_to_look_for="Measure the input register: all zeros → constant, anything else → balanced. One shot suffices "
                         "in the ideal case; the report shows P(00…0).",
        try_this=["Flip oracle between balanced / constant0 / constant1 and confirm the verdict.",
                  "Increase n: classically the worst case needs 2^(n−1)+1 queries; here it's still one.",
                  "Run on a noisy backend and see how many shots you need to be confident."],
        real_world_use="Deutsch–Jozsa is pedagogical, but phase kickback and interference — the ideas it isolates — are "
                       "the engine inside Grover, Shor and phase estimation.",
        going_deeper="Bernstein–Vazirani uses the same trick to read out a whole hidden string, not just one bit.",
        references=[{"title": "Deutsch–Jozsa algorithm", "url": "https://en.wikipedia.org/wiki/Deutsch%E2%80%93Jozsa_algorithm"}],
        prerequisites=["bell_states"],
    )
    title = "Deutsch–Jozsa: constant vs balanced in one query"
    category = "Oracles"
    summary = "Decide whether f:{0,1}^n→{0,1} is constant or balanced with a single oracle call."
    params = [Param("n", "int", 4, "Input bits", 1, 12),
              Param("oracle", "choice", "balanced", "Oracle type", choices=["balanced", "constant0", "constant1"]),
              Param("seed", "int", 7, "Seed for the random balanced function (-1 = random)", -1, 2**31)]
    hardware_notes = "n+1 qubits, ≤ n CX gates."

    def build(self, p):
        n = p["n"]
        rng = rng_from(p["seed"])
        s = int(rng.integers(1, 1 << n)) if p["oracle"] == "balanced" else 0
        b = 1 if p["oracle"] == "constant1" else int(rng.integers(0, 2)) if p["oracle"] == "balanced" else 0
        qc = Circuit(name=f"dj_{p['oracle']}")
        x = qc.add_qreg("x", n)
        y = qc.add_qreg("y", 1)
        c = qc.add_creg("c", n)
        qc.x(y[0]).h(y[0]).h(x)
        for i in range(n):           # f(x) = s·x XOR b  (balanced iff s != 0)
            if (s >> i) & 1:
                qc.cx(x[i], y[0])
        if b:
            qc.x(y[0])
        qc.h(x)
        qc.measure(x, c)
        return Plan([qc], {"s": s, "b": b})

    def analyze(self, p, ctx, results):
        n = p["n"]
        res = results[0]
        p0 = res.counts.get("0" * n, 0) / res.shots
        decision = "constant" if p0 > 0.5 else "balanced"
        truth = "balanced" if p["oracle"] == "balanced" else "constant"
        return Report("Deutsch–Jozsa",
                      [f"P(0…0) = {p0:.4f} → decided '{decision}' (truth: {truth})",
                       "A classical deterministic algorithm needs 2^(n-1)+1 queries in the worst case."],
                      {"p_all_zero": p0, "correct": decision == truth, "hidden_s": _bits(ctx['s'], n)},
                      charts=[counts_chart("Input-register outcomes", res.counts, top=16)],
                      verdict="pass" if decision == truth else "fail")


@register
class BernsteinVazirani(Experiment):
    id = "bernstein_vazirani"
    tutor = Tutor(
        concept="Given a black box computing f(x) = s·x (mod 2) for a hidden n-bit string s, Bernstein–Vazirani "
                "recovers ALL of s in one query. Classically you need n queries — one per bit.",
        how_it_works="Same recipe as Deutsch–Jozsa: superpose the inputs, run the oracle once with phase kickback so "
                     "each bit of s becomes a phase, then Hadamard everything. The interference deposits s directly into "
                     "the measured bitstring.",
        intuition="Each Hadamard sandwich converts 'is bit i set?' from a value you'd have to probe into a phase the "
                  "final Hadamards read off in parallel. One query, because the oracle touches all bits at once.",
        misconception="The oracle isn't 'cheating' by containing s plainly — s is encoded only in which qubits the "
                      "oracle's CNOTs target. The algorithm's job is to read that structure out in one shot.",
        what_to_look_for="The single most-frequent measurement IS the hidden string s. The report shows P(s); on an "
                         "ideal backend it's 1.0.",
        try_this=["Change the `secret` to any bitstring and confirm it's recovered exactly.",
                  "Leave secret empty for a random 6-bit string.",
                  "Run on ibm:fake_fez: note popcount(s) CNOTs, so sparser secrets survive noise better."],
        real_world_use="BV is the ancestor of the hidden-subgroup algorithms (Simon, Shor). The 'learn a linear "
                       "function from one quantum query' idea also appears in quantum learning theory.",
        going_deeper="Simon's problem keeps the hidden-string flavour but makes the classical cost exponential.",
        references=[{"title": "Bernstein–Vazirani algorithm", "url": "https://en.wikipedia.org/wiki/Bernstein%E2%80%93Vazirani_algorithm"}],
        prerequisites=["deutsch_jozsa"],
    )
    title = "Bernstein–Vazirani: read a hidden string in one query"
    category = "Oracles"
    summary = "Recover s from f(x) = s·x mod 2 with one query (classically n queries)."
    params = [Param("secret", "bits", "101101", "Hidden bitstring s (MSB first); empty = random 6 bits")]
    hardware_notes = "n+1 qubits, popcount(s) CX gates."

    def build(self, p):
        s = p["secret"] or format(int(rng_from(None).integers(0, 64)), "06b")
        n = len(s)
        val = int(s, 2)
        qc = Circuit(name="bernstein_vazirani")
        x = qc.add_qreg("x", n)
        y = qc.add_qreg("y", 1)
        c = qc.add_creg("c", n)
        qc.x(y[0]).h(y[0]).h(x)
        for i in range(n):
            if (val >> i) & 1:
                qc.cx(x[i], y[0])
        qc.h(x)
        qc.measure(x, c)
        return Plan([qc], {"secret": s})

    def analyze(self, p, ctx, results):
        s = ctx["secret"]
        res = results[0]
        best = res.most_frequent()
        ps = res.counts.get(s, 0) / res.shots
        return Report("Bernstein–Vazirani",
                      [f"Hidden s = {s}; most frequent outcome {best}; P(s) = {ps:.4f}"],
                      {"secret": s, "recovered": best, "p_secret": ps, "correct": best == s},
                      charts=[counts_chart("Outcomes", res.counts, top=16)],
                      verdict="pass" if best == s else "fail")


@register
class Simon(Experiment):
    id = "simon"
    tutor = Tutor(
        concept="Simon's problem hides a secret string s such that f(x) = f(x⊕s). Finding s classically takes "
                "exponentially many queries; quantumly it takes about n. This exponential gap directly inspired Shor.",
        how_it_works="Entangle an input register with an output register through f, then measure the output. The input "
                     "collapses to a two-element superposition {x, x⊕s}. A Hadamard transform turns that into a random "
                     "bitstring y guaranteed to satisfy y·s = 0. Collect n−1 independent y's and solve the linear system "
                     "over GF(2) to pull out s.",
        intuition="Each run doesn't reveal s, only one random linear equation that s must obey. A handful of equations "
                  "pins s down. The quantum part is efficiently sampling those constraints; the solving is classical.",
        misconception="A single run doesn't give the answer — you need several, then classical linear algebra. The "
                      "'speedup' is in how cheaply each constraint is harvested.",
        what_to_look_for="Every measured y should satisfy y·s = 0. The report scores candidate s values by how "
                         "consistent they are with the measured y's and recovers the best non-zero one.",
        try_this=["Change the `secret` and confirm recovery.",
                  "Note the number of distinct outcomes ≈ 2^(n−1) — half the space, the signature of the 2-to-1 map.",
                  "Run on a noisy backend and see how consistency degrades."],
        real_world_use="Simon's algorithm is the template for the hidden-subgroup problem that Shor's factoring is a "
                       "special case of; it also breaks certain symmetric constructions (e.g. Even–Mansour) in the "
                       "quantum query model.",
        going_deeper="Shor replaces the XOR-period with a modular-multiplication period and uses the QFT to find it.",
        references=[{"title": "Simon's problem", "url": "https://en.wikipedia.org/wiki/Simon%27s_problem"}],
        prerequisites=["bernstein_vazirani"],
    )
    title = "Simon's algorithm: find the hidden period s"
    category = "Oracles"
    summary = "f(x) = f(x ⊕ s): each run yields y with y·s = 0; GF(2) post-processing recovers s."
    description = ("Exponential query separation (vs. classical Θ(2^{n/2})). On noisy hardware we score every "
                   "candidate s by the fraction of shots satisfying y·s = 0 and pick the best non-zero one.")
    params = [Param("secret", "bits", "1011", "Hidden period s ≠ 0 (MSB first)")]
    hardware_notes = "2n qubits, ≤ 2n CX gates."

    def build(self, p):
        s = p["secret"]
        if not s or int(s, 2) == 0:
            raise ValueError("secret must be a non-zero bitstring")
        n = len(s)
        val = int(s, 2)
        qc = Circuit(name="simon")
        x = qc.add_qreg("x", n)
        y = qc.add_qreg("y", n)
        c = qc.add_creg("c", n)
        qc.h(x)
        for i in range(n):
            qc.cx(x[i], y[i])
        j = (val & -val).bit_length() - 1
        for i in range(n):
            if (val >> i) & 1:
                qc.cx(x[j], y[i])
        qc.h(x)
        qc.measure(x, c)
        return Plan([qc], {"secret": s})

    def analyze(self, p, ctx, results):
        s = ctx["secret"]
        n = len(s)
        res = results[0]
        scores = []
        for cand in range(1, 1 << n):
            ok = sum(c for k, c in res.counts.items() if dot2(int(k, 2), cand) == 0)
            scores.append((ok / res.shots, cand))
        scores.sort(reverse=True)
        best = _bits(scores[0][1], n)
        rows = [[_bits(c, n), round(sc, 4)] for sc, c in scores[:8]]
        return Report("Simon's algorithm",
                      [f"Hidden s = {s}; recovered {best} (consistency {scores[0][0]:.4f})",
                       f"Distinct y observed: {len(res.counts)} (ideal: 2^(n-1) = {1 << (n - 1)})"],
                      {"secret": s, "recovered": best, "correct": best == s},
                      [Table("Top candidates", ["s'", "fraction with y·s' = 0"], rows)],
                      [counts_chart("Measured y", res.counts, top=32)],
                      "pass" if best == s else "fail")


# =============================================================================
def _diffuser(qc: Circuit, qubits) -> None:
    qc.h(qubits)
    qc.phase_flip_on(qubits, 0)
    qc.h(qubits)


def _optimal_iterations(N: int, M: int) -> int:
    if M <= 0 or M >= N:
        return 0
    theta = math.asin(math.sqrt(M / N))
    return max(0, round(math.pi / (4 * theta) - 0.5))


def _theory(N: int, M: int, k: int) -> float:
    if M <= 0:
        return 0.0
    theta = math.asin(math.sqrt(min(1.0, M / N)))
    return math.sin((2 * k + 1) * theta) ** 2


@register
class Grover(Experiment):
    id = "grover"
    tutor = Tutor(
        concept="Grover's algorithm finds a needle in an unsorted haystack of N items in about √N steps, versus N/2 for "
                "any classical search. It's the most broadly applicable quantum speedup — a quadratic boost for brute force.",
        how_it_works="Start in an equal superposition of all N candidates. Repeat two steps: an ORACLE that flips the "
                     "sign of the marked item(s), then a DIFFUSER that reflects all amplitudes about their average. Each "
                     "round rotates probability toward the answer; after ≈(π/4)√N rounds, measuring almost certainly "
                     "returns a marked item.",
        intuition="Picture amplitudes as arrows. The oracle flips the target's arrow below the axis; the diffuser "
                  "'inverts about the mean', which makes the flipped arrow grow. Repeat and the target towers over the rest.",
        misconception="More iterations is NOT always better — amplitude amplification OVERSHOOTS. Past the optimal count "
                      "the success probability falls again, like a pendulum. The quadratic speedup also can't be improved: "
                      "Grover is provably optimal for unstructured search.",
        what_to_look_for="Success probability near 1 at the optimal iteration count. The report plots P(success) vs "
                         "iterations — watch it rise then fall. With M marked items the optimum is ≈(π/4)√(N/M).",
        try_this=["Set iterations beyond the optimum and watch success DROP — the overshoot.",
                  "Mark several states at once and see the optimal iteration count shrink.",
                  "Grow n toward 8–10 and watch hardware noise wash out the peak on ibm:fake_fez."],
        real_world_use="Grover accelerates brute-force search anywhere: database lookup, constraint satisfaction, and — "
                       "crucially for security — guessing symmetric keys and hash preimages, which is why AES-128 is "
                       "considered to have only ~64 bits of quantum security. See the password-search demo.",
        going_deeper="Grover-SAT builds a real logical oracle; the Enigma lab amplifies a cryptographic key; amplitude "
                     "amplification generalises the diffuser to arbitrary starting states.",
        references=[{"title": "Grover's algorithm", "url": "https://en.wikipedia.org/wiki/Grover%27s_algorithm"}],
        prerequisites=["deutsch_jozsa"],
    )
    title = "Grover search over marked basis states"
    category = "Oracles"
    summary = "Amplitude amplification: find marked items among N = 2^n in ~π/4·√(N/M) iterations."
    params = [Param("n", "int", 4, "Search qubits", 2, 10),
              Param("marked", "str", "1011", "Comma-separated marked bitstrings (MSB first) or 'random'"),
              Param("iterations", "int", -1, "Grover iterations (-1 = optimal)", -1, 50),
              Param("seed", "int", 5, "Seed for 'random'", -1, 2**31)]
    hardware_notes = "n ≥ 4 needs multi-controlled Z gates; expect rapid decoherence beyond n = 4–5 on hardware."

    def build(self, p):
        n = p["n"]
        if p["marked"].strip().lower() == "random":
            marked = [int(rng_from(p["seed"]).integers(0, 1 << n))]
        else:
            marked = parse_bitstring_list(p["marked"], n)
        if not marked:
            raise ValueError("no marked states")
        k = p["iterations"] if p["iterations"] >= 0 else _optimal_iterations(1 << n, len(set(marked)))
        qc = Circuit(n, name=f"grover_n{n}_k{k}")
        c = qc.add_creg("c", n)
        q = list(range(n))
        qc.h(q)
        for _ in range(k):
            for m in sorted(set(marked)):
                qc.phase_flip_on(q, m)
            _diffuser(qc, q)
        qc.measure(q, c)
        return Plan([qc], {"marked": sorted(set(marked)), "iterations": k})

    def analyze(self, p, ctx, results):
        n = p["n"]
        N = 1 << n
        marked = ctx["marked"]
        k = ctx["iterations"]
        res = results[0]
        succ = sum(res.counts.get(_bits(m, n), 0) for m in marked) / res.shots
        theo = _theory(N, len(marked), k)
        ks = list(range(0, max(2 * _optimal_iterations(N, len(marked)) + 2, 4)))
        return Report(
            "Grover search",
            [f"Marked: {', '.join(_bits(m, n) for m in marked)}; iterations: {k}",
             f"Success probability {succ:.4f} (ideal {theo:.4f}; random guess {len(marked) / N:.4f})"],
            {"success": succ, "ideal_success": theo, "iterations": k, "speedup_queries": f"{k} vs ~{N // 2} classical"},
            charts=[counts_chart("Outcomes", res.counts, top=32),
                    Chart("Ideal success vs iterations", [str(i) for i in ks],
                          {"ideal": [_theory(N, len(marked), i) for i in ks]}, "line", "iterations", "P(success)")],
            verdict="pass" if succ > max(0.5, 2 * len(marked) / N) else "warn")


# --------------------------------------------------------------------------- SAT
_TOKEN = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*|~|!|¬|\(|\)|\||&|∧|∨)")


def parse_cnf(text: str) -> tuple[list[str], list[list[tuple[str, bool]]]]:
    """Parse '(a | ~b) & (b | c)' into variables and clauses [(var, positive)]."""
    clauses = []
    for part in re.split(r"&|∧", text):
        part = part.strip().strip("()").strip()
        if not part:
            continue
        lits = []
        for lit in re.split(r"\||∨", part):
            lit = lit.strip().strip("()").strip()
            neg = lit.startswith(("~", "!", "¬"))
            name = lit.lstrip("~!¬").strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise ValueError(f"bad literal {lit!r}")
            lits.append((name, not neg))
        clauses.append(lits)
    variables = sorted({v for c in clauses for v, _ in c})
    if not clauses or len(variables) > 10:
        raise ValueError("need 1..10 variables and at least one clause")
    return variables, clauses


@register
class GroverSAT(Experiment):
    id = "grover_sat"
    tutor = Tutor(
        concept="This turns Grover from a toy (mark a known state) into a real solver: it builds a reversible quantum "
                "circuit that RECOGNISES satisfying assignments of a Boolean formula, then amplifies them.",
        how_it_works="Each clause (OR of literals) is computed into an ancilla qubit with one multi-controlled gate "
                     "using mixed-polarity controls. A final multi-controlled Z fires only when every clause ancilla is "
                     "satisfied, stamping the phase; then the clause computation is reversed (uncomputed) to clean the "
                     "ancillas. That whole block is the Grover oracle.",
        intuition="The oracle doesn't know the answers — it checks them. Amplitude amplification then boosts whichever "
                  "assignments pass the check. The classical solution count is used only to pick the iteration number.",
        misconception="This doesn't make NP-complete problems easy: Grover gives a quadratic (√), not exponential, "
                      "speedup over brute force, and building the oracle costs real gates. It's a speedup, not magic.",
        what_to_look_for="The most frequent assignments should satisfy the formula. The report tags each by whether it "
                         "satisfies, and compares P(solution) to the ideal amplified value and to random guessing.",
        try_this=["Edit the CNF formula and watch the solver find its satisfying assignments.",
                  "Use an unsatisfiable formula and see amplification fail (no solutions to amplify).",
                  "Add more variables and inspect the growing ancilla/depth cost in the circuit preview."],
        real_world_use="Oracle-based Grover search underlies quantum approaches to constraint satisfaction, verification "
                       "and — as the Enigma lab shows — cryptographic key search.",
        going_deeper="The Enigma Grover lab is a cryptographic SAT: 'which key encrypts this plaintext to this ciphertext?'",
        references=[{"title": "Boolean satisfiability problem", "url": "https://en.wikipedia.org/wiki/Boolean_satisfiability_problem"}],
        prerequisites=["grover"],
    )
    title = "Grover SAT solver (reversible CNF oracle)"
    category = "Oracles"
    summary = "Builds a clause-by-clause reversible oracle for a CNF formula and amplifies satisfying assignments."
    description = ("Each clause OR(l1..lk) is computed into an ancilla as NOT(AND(¬l_i)) with one "
                   "multi-controlled X (mixed-polarity controls), the phase is applied when all clause "
                   "ancillas are 1, then everything is uncomputed. The classical solution count is used only to "
                   "choose the iteration number (it is reported, not hidden).")
    params = [Param("formula", "str", "(a | b | ~c) & (~a | c) & (b | ~d) & (~b | ~c | d)", "CNF formula"),
              Param("iterations", "int", -1, "Iterations (-1 = optimal from classical count)", -1, 20)]
    hardware_notes = "variables + clauses qubits; deep for >3 variables on current hardware."

    def build(self, p):
        variables, clauses = parse_cnf(p["formula"])
        n, m = len(variables), len(clauses)
        sols = [a for a in range(1 << n) if self._sat(a, variables, clauses)]
        k = p["iterations"] if p["iterations"] >= 0 else _optimal_iterations(1 << n, len(sols))
        qc = Circuit(name="grover_sat")
        x = qc.add_qreg("x", n)
        anc = qc.add_qreg("clause", m)
        c = qc.add_creg("c", n)
        qc.h(x)

        def clauses_compute():
            for j, cl in enumerate(clauses):
                ctrls, state = [], 0
                for i, (v, pos) in enumerate(cl):
                    ctrls.append(x[variables.index(v)])
                    state |= (0 if pos else 1) << i   # control fires when literal is FALSE
                if len(set(ctrls)) != len(ctrls):
                    raise ValueError("repeated variable inside one clause is not supported")
                qc.mcx(ctrls, anc[j], ctrl_state=state)
                qc.x(anc[j])

        for _ in range(k):
            clauses_compute()
            qc.mcz(list(anc)[:-1], anc[m - 1]) if m > 1 else qc.z(anc[0])
            clauses_compute()      # self-inverse
            _diffuser(qc, list(x))
        qc.measure(x, c)
        return Plan([qc], {"variables": variables, "solutions": sols, "iterations": k})

    @staticmethod
    def _sat(a: int, variables, clauses) -> bool:
        val = {v: (a >> i) & 1 for i, v in enumerate(variables)}
        return all(any(val[v] == (1 if pos else 0) for v, pos in cl) for cl in clauses)

    def analyze(self, p, ctx, results):
        variables = ctx["variables"]
        n = len(variables)
        sols = ctx["solutions"]
        res = results[0]
        succ = sum(res.counts.get(_bits(s, n), 0) for s in sols) / res.shots
        top = sorted(res.counts.items(), key=lambda kv: -kv[1])[:8]
        _, clauses = parse_cnf(p["formula"])

        def assign(bs):
            v = int(bs, 2)
            return ", ".join(f"{name}={(v >> i) & 1}" for i, name in enumerate(variables))
        rows = [[bs, assign(bs), round(cnt / res.shots, 4), self._sat(int(bs, 2), variables, clauses)]
                for bs, cnt in top]
        theo = _theory(1 << n, len(sols), ctx["iterations"])
        return Report("Grover SAT",
                      [f"Formula: {p['formula']}", f"{len(sols)} satisfying assignment(s) of {1 << n}",
                       f"P(measure a solution) = {succ:.4f} (ideal {theo:.4f}, random {len(sols) / (1 << n):.4f})"],
                      {"solutions": len(sols), "success": succ, "ideal_success": theo,
                       "iterations": ctx["iterations"]},
                      [Table("Most frequent assignments (bit i = variable i)", ["bits", "assignment", "freq", "satisfies"],
                             rows)],
                      [counts_chart("Outcomes", res.counts, top=32)],
                      "pass" if sols and succ > len(sols) / (1 << n) * 1.5 else "warn")
