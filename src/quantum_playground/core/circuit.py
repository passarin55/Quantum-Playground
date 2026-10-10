"""Backend-neutral circuit intermediate representation (IR).

The IR is deliberately small and explicit so it can be

* simulated exactly by the in-house simulators (statevector, density matrix,
  classical reversible),
* serialised to JSON for the web studio and the job store,
* exported to OpenQASM 2/3, and
* translated 1:1 into Qiskit ``QuantumCircuit`` objects for IBM Quantum,
  Aer, or AWS Braket submission.
"""
from __future__ import annotations

import contextlib
import copy
import json
import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Optional, Sequence, Union

from . import gates as G


class Register:
    """A named, contiguous block of qubit or classical-bit indices."""

    __slots__ = ("name", "start", "size", "kind")

    def __init__(self, name: str, start: int, size: int, kind: str):
        self.name, self.start, self.size, self.kind = name, start, size, kind

    @property
    def indices(self) -> tuple[int, ...]:
        return tuple(range(self.start, self.start + self.size))

    def __len__(self) -> int:
        return self.size

    def __iter__(self) -> Iterator[int]:
        return iter(self.indices)

    def __getitem__(self, item):
        idx = self.indices[item]
        return list(idx) if isinstance(item, slice) else idx

    def __repr__(self) -> str:
        return f"{self.kind}reg({self.name!r}, {self.size})"


QubitLike = Union[int, Register, Sequence[int]]


@dataclass(frozen=True)
class Instruction:
    name: str
    qubits: tuple[int, ...]
    params: tuple[float, ...] = ()
    clbits: tuple[int, ...] = ()
    # ((clbit, clbit, ...), value): bit i of value is required on clbits[i].
    condition: Optional[tuple[tuple[int, ...], int]] = None
    ctrl_state: Optional[int] = None

    @property
    def spec(self) -> G.GateSpec:
        return G.spec(self.name)

    @property
    def num_controls(self) -> int:
        if self.name in ("measure", "reset", "barrier", "delay"):
            return 0
        return G.num_controls(self.name, len(self.qubits))

    @property
    def controls(self) -> tuple[int, ...]:
        return self.qubits[: self.num_controls]

    @property
    def targets(self) -> tuple[int, ...]:
        return self.qubits[self.num_controls:]

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"name": self.name, "qubits": list(self.qubits)}
        if self.params:
            d["params"] = [float(p) for p in self.params]
        if self.clbits:
            d["clbits"] = list(self.clbits)
        if self.condition is not None:
            d["condition"] = {"clbits": list(self.condition[0]), "value": int(self.condition[1])}
        if self.ctrl_state is not None:
            d["ctrl_state"] = int(self.ctrl_state)
        return d

    @staticmethod
    def from_dict(d: dict) -> "Instruction":
        cond = d.get("condition")
        return Instruction(
            name=str(d["name"]).lower(),
            qubits=tuple(int(q) for q in d.get("qubits", ())),
            params=tuple(float(p) for p in d.get("params", ())),
            clbits=tuple(int(c) for c in d.get("clbits", ())),
            condition=(tuple(int(c) for c in cond["clbits"]), int(cond["value"])) if cond else None,
            ctrl_state=d.get("ctrl_state"),
        )


class CircuitError(ValueError):
    pass


class Circuit:
    """A quantum circuit over named quantum and classical registers."""

    def __init__(self, num_qubits: int = 0, num_clbits: int = 0, name: str = "circuit",
                 metadata: Optional[dict] = None):
        self.name = name
        self.qregs: list[Register] = []
        self.cregs: list[Register] = []
        self.instructions: list[Instruction] = []
        self.metadata: dict = dict(metadata or {})
        self._condition_stack: list[tuple[tuple[int, ...], int]] = []
        if num_qubits:
            self.add_qreg("q", num_qubits)
        if num_clbits:
            self.add_creg("c", num_clbits)

    # ------------------------------------------------------------------ registers
    @property
    def num_qubits(self) -> int:
        return sum(r.size for r in self.qregs)

    @property
    def num_clbits(self) -> int:
        return sum(r.size for r in self.cregs)

    def add_qreg(self, name: str, size: int) -> Register:
        if any(r.name == name for r in self.qregs):
            raise CircuitError(f"Quantum register {name!r} already exists")
        if size < 1:
            raise CircuitError("Register size must be >= 1")
        reg = Register(name, self.num_qubits, int(size), "q")
        self.qregs.append(reg)
        return reg

    def add_creg(self, name: str, size: int) -> Register:
        if any(r.name == name for r in self.cregs):
            raise CircuitError(f"Classical register {name!r} already exists")
        if size < 1:
            raise CircuitError("Register size must be >= 1")
        reg = Register(name, self.num_clbits, int(size), "c")
        self.cregs.append(reg)
        return reg

    def qreg(self, name: str) -> Register:
        for r in self.qregs:
            if r.name == name:
                return r
        raise KeyError(name)

    def creg(self, name: str) -> Register:
        for r in self.cregs:
            if r.name == name:
                return r
        raise KeyError(name)

    def clbit_register(self, clbit: int) -> tuple[Register, int]:
        for r in self.cregs:
            if r.start <= clbit < r.start + r.size:
                return r, clbit - r.start
        raise CircuitError(f"clbit {clbit} out of range")

    def qubit_register(self, qubit: int) -> tuple[Register, int]:
        for r in self.qregs:
            if r.start <= qubit < r.start + r.size:
                return r, qubit - r.start
        raise CircuitError(f"qubit {qubit} out of range")

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _flatten(arg: QubitLike) -> list[int]:
        if isinstance(arg, Register):
            return list(arg.indices)
        if isinstance(arg, (int,)) or hasattr(arg, "__index__"):
            return [int(arg)]
        out: list[int] = []
        for a in arg:  # type: ignore[union-attr]
            out.extend(Circuit._flatten(a))
        return out

    def _check_qubits(self, qubits: Sequence[int]) -> None:
        n = self.num_qubits
        for q in qubits:
            if not 0 <= q < n:
                raise CircuitError(f"qubit index {q} out of range (circuit has {n} qubits)")
        if len(set(qubits)) != len(qubits):
            raise CircuitError(f"duplicate qubits in one instruction: {list(qubits)}")

    def append(self, name: str, qubits: Sequence[int], params: Sequence[float] = (),
               clbits: Sequence[int] = (), ctrl_state: Optional[int] = None,
               condition: Optional[tuple[Sequence[int], int]] = None) -> "Circuit":
        name = name.lower()
        s = G.spec(name)
        qubits = tuple(int(q) for q in qubits)
        params = tuple(float(p) for p in params)
        if name != "barrier":
            self._check_qubits(qubits)
        if len(params) != s.num_params:
            raise CircuitError(f"{name} takes {s.num_params} parameter(s), got {len(params)}")
        if s.unitary:
            nc = G.num_controls(name, len(qubits))
            if s.num_controls is None:
                if nc < 1:
                    raise CircuitError(f"{name} needs at least one control")
            elif len(qubits) != s.total_qubits():
                raise CircuitError(f"{name} acts on {s.total_qubits()} qubits, got {len(qubits)}")
            if ctrl_state is not None and not 0 <= ctrl_state < (1 << nc):
                raise CircuitError("ctrl_state out of range")
        if name == "measure":
            if len(clbits) != 1 or len(qubits) != 1:
                raise CircuitError("measure maps exactly one qubit to one clbit")
            if not 0 <= clbits[0] < self.num_clbits:
                raise CircuitError(f"clbit {clbits[0]} out of range")
        if condition is None and self._condition_stack:
            condition = self._condition_stack[-1]
        cond = None
        if condition is not None:
            cbits = tuple(int(c) for c in condition[0])
            for c in cbits:
                if not 0 <= c < self.num_clbits:
                    raise CircuitError(f"condition clbit {c} out of range")
            cond = (cbits, int(condition[1]))
        self.instructions.append(Instruction(name, qubits, params, tuple(int(c) for c in clbits), cond,
                                             None if ctrl_state is None else int(ctrl_state)))
        return self

    # ------------------------------------------------------------------ gates
    def _broadcast_1q(self, name: str, qubits: QubitLike, params: Sequence[float] = ()) -> "Circuit":
        for q in self._flatten(qubits):
            self.append(name, (q,), params)
        return self

    def id(self, q: QubitLike): return self._broadcast_1q("id", q)
    def x(self, q: QubitLike): return self._broadcast_1q("x", q)
    def y(self, q: QubitLike): return self._broadcast_1q("y", q)
    def z(self, q: QubitLike): return self._broadcast_1q("z", q)
    def h(self, q: QubitLike): return self._broadcast_1q("h", q)
    def s(self, q: QubitLike): return self._broadcast_1q("s", q)
    def sdg(self, q: QubitLike): return self._broadcast_1q("sdg", q)
    def t(self, q: QubitLike): return self._broadcast_1q("t", q)
    def tdg(self, q: QubitLike): return self._broadcast_1q("tdg", q)
    def sx(self, q: QubitLike): return self._broadcast_1q("sx", q)
    def sxdg(self, q: QubitLike): return self._broadcast_1q("sxdg", q)
    def rx(self, theta: float, q: QubitLike): return self._broadcast_1q("rx", q, (theta,))
    def ry(self, theta: float, q: QubitLike): return self._broadcast_1q("ry", q, (theta,))
    def rz(self, theta: float, q: QubitLike): return self._broadcast_1q("rz", q, (theta,))
    def p(self, lam: float, q: QubitLike): return self._broadcast_1q("p", q, (lam,))
    def u(self, theta: float, phi: float, lam: float, q: QubitLike):
        return self._broadcast_1q("u", q, (theta, phi, lam))

    def _pairwise(self, name: str, a: QubitLike, b: QubitLike, params: Sequence[float] = ()) -> "Circuit":
        aa, bb = self._flatten(a), self._flatten(b)
        if len(aa) == 1 and len(bb) > 1:
            aa = aa * len(bb)
        if len(bb) == 1 and len(aa) > 1:
            bb = bb * len(aa)
        if len(aa) != len(bb):
            raise CircuitError(f"{name}: cannot broadcast {len(aa)} and {len(bb)} qubits")
        for x, y in zip(aa, bb):
            self.append(name, (x, y), params)
        return self

    def cx(self, control: QubitLike, target: QubitLike): return self._pairwise("cx", control, target)
    def cy(self, control: QubitLike, target: QubitLike): return self._pairwise("cy", control, target)
    def cz(self, control: QubitLike, target: QubitLike): return self._pairwise("cz", control, target)
    def ch(self, control: QubitLike, target: QubitLike): return self._pairwise("ch", control, target)
    def swap(self, a: QubitLike, b: QubitLike): return self._pairwise("swap", a, b)
    def cp(self, lam: float, control: QubitLike, target: QubitLike): return self._pairwise("cp", control, target, (lam,))
    def crx(self, theta: float, control: QubitLike, target: QubitLike): return self._pairwise("crx", control, target, (theta,))
    def cry(self, theta: float, control: QubitLike, target: QubitLike): return self._pairwise("cry", control, target, (theta,))
    def crz(self, theta: float, control: QubitLike, target: QubitLike): return self._pairwise("crz", control, target, (theta,))
    def rxx(self, theta: float, a: QubitLike, b: QubitLike): return self._pairwise("rxx", a, b, (theta,))
    def ryy(self, theta: float, a: QubitLike, b: QubitLike): return self._pairwise("ryy", a, b, (theta,))
    def rzz(self, theta: float, a: QubitLike, b: QubitLike): return self._pairwise("rzz", a, b, (theta,))

    def ccx(self, c1: int, c2: int, target: int): return self.append("ccx", (c1, c2, target))
    def ccz(self, c1: int, c2: int, target: int): return self.append("ccz", (c1, c2, target))
    def cswap(self, control: int, a: int, b: int): return self.append("cswap", (control, a, b))

    def mcx(self, controls: QubitLike, target: int, ctrl_state: Optional[int] = None) -> "Circuit":
        cs = self._flatten(controls)
        if not cs:
            if ctrl_state not in (None, 0):
                raise CircuitError("ctrl_state given without controls")
            return self.x(target)
        if ctrl_state is None or ctrl_state == (1 << len(cs)) - 1:
            if len(cs) == 1:
                return self.cx(cs[0], target)
            if len(cs) == 2:
                return self.ccx(cs[0], cs[1], target)
            return self.append("mcx", (*cs, target))
        return self.append("mcx", (*cs, target), ctrl_state=ctrl_state)

    def mcp(self, lam: float, controls: QubitLike, target: int, ctrl_state: Optional[int] = None) -> "Circuit":
        cs = self._flatten(controls)
        if not cs:
            return self.p(lam, target)
        if len(cs) == 1 and ctrl_state in (None, 1):
            return self.cp(lam, cs[0], target)
        return self.append("mcp", (*cs, target), (lam,), ctrl_state=ctrl_state)

    def mcz(self, controls: QubitLike, target: int, ctrl_state: Optional[int] = None) -> "Circuit":
        cs = self._flatten(controls)
        if not cs:
            return self.z(target)
        if ctrl_state is None or ctrl_state == (1 << len(cs)) - 1:
            if len(cs) == 1:
                return self.cz(cs[0], target)
            if len(cs) == 2:
                return self.ccz(cs[0], cs[1], target)
        return self.mcp(math.pi, cs, target, ctrl_state)

    def phase_flip_on(self, qubits: QubitLike, value: int) -> "Circuit":
        """Multiply the amplitude of basis state ``value`` of ``qubits`` by -1."""
        qs = self._flatten(qubits)
        if len(qs) == 1:
            if value & 1:
                return self.z(qs[0])
            self.x(qs[0]); self.z(qs[0]); return self.x(qs[0])
        ctrl = value & ((1 << (len(qs) - 1)) - 1)
        top = (value >> (len(qs) - 1)) & 1
        if not top:
            self.x(qs[-1])
        self.mcz(qs[:-1], qs[-1], ctrl_state=ctrl)
        if not top:
            self.x(qs[-1])
        return self

    def measure(self, qubits: QubitLike, clbits: QubitLike) -> "Circuit":
        qs, cs = self._flatten(qubits), self._flatten(clbits)
        if len(qs) != len(cs):
            raise CircuitError("measure: qubit and clbit counts differ")
        for q, c in zip(qs, cs):
            self.append("measure", (q,), clbits=(c,))
        return self

    def measure_all(self, register_name: str = "meas", barrier: bool = True) -> Register:
        reg = self.add_creg(register_name, self.num_qubits)
        if barrier:
            self.barrier()
        self.measure(list(range(self.num_qubits)), reg)
        return reg

    def reset(self, qubits: QubitLike) -> "Circuit":
        for q in self._flatten(qubits):
            self.append("reset", (q,))
        return self

    def barrier(self, *qubits: QubitLike) -> "Circuit":
        qs = self._flatten(list(qubits)) if qubits else list(range(self.num_qubits))
        self.instructions.append(Instruction("barrier", tuple(qs)))
        return self

    def delay(self, seconds: float, qubits: QubitLike) -> "Circuit":
        for q in self._flatten(qubits):
            self.append("delay", (q,), (float(seconds),))
        return self

    @contextlib.contextmanager
    def if_test(self, clbits: Union[int, Register, Sequence[int]], value: int):
        """``with qc.if_test(clbit, 1): qc.x(q)`` — classically controlled block."""
        bits = tuple(self._flatten(clbits))
        self._condition_stack.append((bits, int(value)))
        try:
            yield self
        finally:
            self._condition_stack.pop()

    # ------------------------------------------------------------------ structure
    def compose(self, other: "Circuit", qubits: Optional[QubitLike] = None,
                clbits: Optional[QubitLike] = None) -> "Circuit":
        """Append ``other`` in place, mapping its qubit i to ``qubits[i]``."""
        qmap = self._flatten(qubits) if qubits is not None else list(range(other.num_qubits))
        cmap = self._flatten(clbits) if clbits is not None else list(range(other.num_clbits))
        if len(qmap) != other.num_qubits:
            raise CircuitError(f"compose: need {other.num_qubits} qubits, got {len(qmap)}")
        if len(cmap) < other.num_clbits and any(i.clbits or i.condition for i in other.instructions):
            raise CircuitError("compose: classical bits not mapped")
        for ins in other.instructions:
            cond = None
            if ins.condition is not None:
                cond = (tuple(cmap[c] for c in ins.condition[0]), ins.condition[1])
            new = Instruction(ins.name, tuple(qmap[q] for q in ins.qubits), ins.params,
                              tuple(cmap[c] for c in ins.clbits), cond, ins.ctrl_state)
            if new.name != "barrier":
                self._check_qubits(new.qubits)
            self.instructions.append(new)
        return self

    def inverse(self) -> "Circuit":
        out = self.copy_empty(name=self.name + "_dg")
        for ins in reversed(self.instructions):
            if ins.name == "barrier":
                out.instructions.append(ins)
                continue
            s = ins.spec
            if not s.unitary or ins.condition is not None:
                raise CircuitError(f"cannot invert non-unitary instruction {ins.name}")
            name, params = s.inverse(ins.params)
            out.instructions.append(Instruction(name, ins.qubits, params, (), None, ins.ctrl_state))
        return out

    def copy_empty(self, name: Optional[str] = None) -> "Circuit":
        out = Circuit(name=name or self.name, metadata=copy.deepcopy(self.metadata))
        for r in self.qregs:
            out.add_qreg(r.name, r.size)
        for r in self.cregs:
            out.add_creg(r.name, r.size)
        return out

    def copy(self, name: Optional[str] = None) -> "Circuit":
        out = self.copy_empty(name)
        out.instructions = list(self.instructions)
        return out

    def remove_final_measurements(self) -> "Circuit":
        out = self.copy()
        out.instructions = [i for i in out.instructions if i.name != "measure"]
        return out

    # ------------------------------------------------------------------ queries
    def count_ops(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for ins in self.instructions:
            out[ins.name] = out.get(ins.name, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    def size(self) -> int:
        return sum(1 for i in self.instructions if i.name != "barrier")

    def depth(self) -> int:
        level_q = [0] * self.num_qubits
        level_c = [0] * self.num_clbits
        for ins in self.instructions:
            if ins.name == "barrier":
                qs = ins.qubits or tuple(range(self.num_qubits))
                top = max((level_q[q] for q in qs), default=0)
                for q in qs:
                    level_q[q] = top
                continue
            cbits = list(ins.clbits) + (list(ins.condition[0]) if ins.condition else [])
            top = max([level_q[q] for q in ins.qubits] + [level_c[c] for c in cbits] + [0]) + 1
            for q in ins.qubits:
                level_q[q] = top
            for c in cbits:
                level_c[c] = top
        return max(level_q + level_c + [0])

    def gate_profile(self) -> dict:
        one = two = multi = 0
        for ins in self.instructions:
            if not ins.spec.unitary:
                continue
            k = len(ins.qubits)
            if k == 1:
                one += 1
            elif k == 2:
                two += 1
            else:
                multi += 1
        return {"qubits": self.num_qubits, "clbits": self.num_clbits, "size": self.size(),
                "depth": self.depth(), "one_qubit": one, "two_qubit": two, "multi_qubit": multi,
                "ops": self.count_ops()}

    def is_unitary(self) -> bool:
        return all(i.spec.unitary or i.name in ("barrier", "delay") for i in self.instructions)

    def is_classical_reversible(self) -> bool:
        return all(i.spec.classical or i.name == "barrier" for i in self.instructions)

    def has_dynamic_features(self) -> bool:
        """True if measurement results feed forward or qubits are reused after measurement."""
        measured: set[int] = set()
        for ins in self.instructions:
            if ins.condition is not None or ins.name == "reset":
                return True
            if ins.name == "measure":
                measured.add(ins.qubits[0])
            elif ins.name != "barrier" and measured.intersection(ins.qubits):
                return True
        return False

    def measured_qubits(self) -> dict[int, int]:
        """clbit -> qubit for the last measurement writing each clbit."""
        out: dict[int, int] = {}
        for ins in self.instructions:
            if ins.name == "measure":
                out[ins.clbits[0]] = ins.qubits[0]
        return out

    # ------------------------------------------------------------------ serialisation
    def to_dict(self) -> dict:
        return {
            "format": "qplay-circuit/1",
            "name": self.name,
            "qregs": [{"name": r.name, "size": r.size} for r in self.qregs],
            "cregs": [{"name": r.name, "size": r.size} for r in self.cregs],
            "instructions": [i.to_dict() for i in self.instructions],
            "metadata": _jsonable(self.metadata),
        }

    @staticmethod
    def from_dict(d: dict) -> "Circuit":
        qc = Circuit(name=d.get("name", "circuit"), metadata=d.get("metadata") or {})
        if "qregs" in d:
            for r in d["qregs"]:
                qc.add_qreg(r["name"], int(r["size"]))
        elif d.get("num_qubits"):
            qc.add_qreg("q", int(d["num_qubits"]))
        if "cregs" in d:
            for r in d["cregs"]:
                qc.add_creg(r["name"], int(r["size"]))
        elif d.get("num_clbits"):
            qc.add_creg("c", int(d["num_clbits"]))
        for raw in d.get("instructions", []):
            ins = Instruction.from_dict(raw)
            if ins.name == "barrier":
                qc.instructions.append(ins)
            else:
                qc.append(ins.name, ins.qubits, ins.params, ins.clbits, ins.ctrl_state, ins.condition)
        return qc

    def to_json(self, **kw) -> str:
        return json.dumps(self.to_dict(), **kw)

    @staticmethod
    def from_json(s: str) -> "Circuit":
        return Circuit.from_dict(json.loads(s))

    def draw(self, **kw) -> str:
        from .draw import draw_text
        return draw_text(self, **kw)

    def __repr__(self) -> str:
        return (f"Circuit({self.name!r}, qubits={self.num_qubits}, clbits={self.num_clbits}, "
                f"size={self.size()})")

    def __len__(self) -> int:
        return len(self.instructions)


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    try:
        import numpy as np
        if isinstance(obj, np.generic):
            return obj.item()
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    except ImportError:  # pragma: no cover
        pass
    return str(obj)
