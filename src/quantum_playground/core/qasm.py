"""OpenQASM 2.0 / 3.0 exporters for the IR.

* QASM 3 uses ``stdgates.inc`` plus gate modifiers (``ctrl @``, ``negctrl @``,
  ``inv @``) for multi-controlled gates, and ``if`` blocks for feed-forward.
  Optional ``dialect="braket"`` renames gates to Amazon Braket's built-ins.
* QASM 2 targets Qiskit's extended ``qelib1.inc`` (c3x / c4x available);
  multi-controlled gates with more controls raise ``QasmError``.
"""
from __future__ import annotations

import math

from .circuit import Circuit, Instruction


class QasmError(ValueError):
    pass


def _fmt(x: float) -> str:
    for k, name in ((1, "pi"), (2, "pi/2"), (4, "pi/4"), (8, "pi/8")):
        if abs(x - math.pi / k) < 1e-12:
            return name
        if abs(x + math.pi / k) < 1e-12:
            return "-" + name
    return repr(float(x))


def _qref(qc: Circuit, q: int) -> str:
    reg, i = qc.qubit_register(q)
    return f"{reg.name}[{i}]"


def _cref(qc: Circuit, c: int) -> str:
    reg, i = qc.clbit_register(c)
    return f"{reg.name}[{i}]"


_Q3_NAMES = {"id": "id", "u": "U"}
_BRAKET_NAMES = {"cx": "cnot", "ccx": "ccnot", "sdg": "si", "tdg": "ti", "sx": "v", "sxdg": "vi",
                 "p": "phaseshift", "cp": "cphaseshift", "id": "i", "rxx": "xx", "ryy": "yy", "rzz": "zz"}


def to_qasm3(qc: Circuit, dialect: str = "standard") -> str:
    lines = ["OPENQASM 3.0;"]
    if dialect == "standard":
        lines.append('include "stdgates.inc";')
        needs = {i.name for i in qc.instructions}
        if "rzz" in needs:
            lines.append("gate rzz(theta) a, b { cx a, b; rz(theta) b; cx a, b; }")
        if "rxx" in needs:
            lines.append("gate rxx(theta) a, b { h a; h b; cx a, b; rz(theta) b; cx a, b; h a; h b; }")
        if "ryy" in needs:
            lines.append("gate ryy(theta) a, b { rx(pi/2) a; rx(pi/2) b; cx a, b; rz(theta) b; cx a, b; "
                         "rx(-pi/2) a; rx(-pi/2) b; }")
    for r in qc.qregs:
        lines.append(f"qubit[{r.size}] {r.name};")
    for r in qc.cregs:
        lines.append(f"bit[{r.size}] {r.name};")
    names = _BRAKET_NAMES if dialect == "braket" else _Q3_NAMES
    for ins in qc.instructions:
        stmt = _q3_stmt(qc, ins, names, dialect)
        if stmt is None:
            continue
        if ins.condition is not None:
            stmt = f"if ({_q3_cond(qc, ins.condition)}) {{ {stmt} }}"
        lines.append(stmt)
    return "\n".join(lines) + "\n"


def _q3_cond(qc: Circuit, cond) -> str:
    bits, value = cond
    parts = [f"{_cref(qc, c)} == {(value >> i) & 1}" for i, c in enumerate(bits)]
    return " && ".join(parts)


def _q3_stmt(qc: Circuit, ins: Instruction, names: dict, dialect: str):
    if ins.name == "barrier":
        if dialect == "braket":
            return None
        qs = ins.qubits or tuple(range(qc.num_qubits))
        return "barrier " + ", ".join(_qref(qc, q) for q in qs) + ";"
    if ins.name == "measure":
        return f"{_cref(qc, ins.clbits[0])} = measure {_qref(qc, ins.qubits[0])};"
    if ins.name == "reset":
        return f"reset {_qref(qc, ins.qubits[0])};"
    if ins.name == "delay":
        return f"delay[{ins.params[0] * 1e9:.1f}ns] {_qref(qc, ins.qubits[0])};"
    params = "(" + ", ".join(_fmt(p) for p in ins.params) + ")" if ins.params else ""
    if ins.name in ("mcx", "mcp", "ccz") or ins.ctrl_state is not None:
        nc = ins.num_controls
        base = {"mcx": "x", "ccx": "x", "cx": "x", "mcp": ("phaseshift" if dialect == "braket" else "p"),
                "cp": ("phaseshift" if dialect == "braket" else "p"), "ccz": "z", "cz": "z"}.get(ins.name)
        if base is None:
            raise QasmError(f"ctrl_state on {ins.name} not exportable")
        cs = ins.ctrl_state if ins.ctrl_state is not None else (1 << nc) - 1
        mods = []
        run_val, run_len = None, 0
        for i in range(nc):
            v = (cs >> i) & 1
            if v == run_val:
                run_len += 1
            else:
                if run_val is not None:
                    mods.append(("ctrl" if run_val else "negctrl", run_len))
                run_val, run_len = v, 1
        mods.append(("ctrl" if run_val else "negctrl", run_len))
        mod = " ".join(f"{m}({k}) @" if k > 1 else f"{m} @" for m, k in mods)
        return f"{mod} {base}{params} " + ", ".join(_qref(qc, q) for q in ins.qubits) + ";"
    name = names.get(ins.name, ins.name)
    return f"{name}{params} " + ", ".join(_qref(qc, q) for q in ins.qubits) + ";"


def to_qasm2(qc: Circuit) -> str:
    lines = ["OPENQASM 2.0;", 'include "qelib1.inc";']
    for r in qc.qregs:
        lines.append(f"qreg {r.name}[{r.size}];")
    for r in qc.cregs:
        lines.append(f"creg {r.name}[{r.size}];")
    for ins in qc.instructions:
        if ins.condition is not None:
            raise QasmError("OpenQASM 2 cannot express single-bit feed-forward portably; use to_qasm3()")
        if ins.name == "barrier":
            qs = ins.qubits or tuple(range(qc.num_qubits))
            lines.append("barrier " + ",".join(_qref(qc, q) for q in qs) + ";")
            continue
        if ins.name == "measure":
            lines.append(f"measure {_qref(qc, ins.qubits[0])} -> {_cref(qc, ins.clbits[0])};")
            continue
        if ins.name == "reset":
            lines.append(f"reset {_qref(qc, ins.qubits[0])};")
            continue
        if ins.name == "delay":
            raise QasmError("delay is not part of OpenQASM 2")
        nc = ins.num_controls
        flips = []
        if ins.ctrl_state is not None:
            flips = [ins.qubits[i] for i in range(nc) if not (ins.ctrl_state >> i) & 1]
        for q in flips:
            lines.append(f"x {_qref(qc, q)};")
        name = ins.name
        params = list(ins.params)
        if name == "mcx":
            name = {1: "cx", 2: "ccx", 3: "c3x", 4: "c4x"}.get(nc)
            if name is None:
                raise QasmError(f"mcx with {nc} controls has no qelib1 equivalent; use to_qasm3()")
        elif name == "mcp":
            if nc == 1:
                name = "cu1"
            else:
                raise QasmError("mcp with >1 control not in qelib1; use to_qasm3()")
        elif name == "ccz":
            q = _qref(qc, ins.qubits[2])
            lines += [f"h {q};", "ccx " + ",".join(_qref(qc, x) for x in ins.qubits) + ";", f"h {q};"]
            for q2 in flips:
                lines.append(f"x {_qref(qc, q2)};")
            continue
        elif name == "p":
            name = "u1"
        elif name == "cp":
            name = "cu1"
        elif name == "u":
            name = "u3"
        p = "(" + ",".join(_fmt(x) for x in params) + ")" if params else ""
        lines.append(f"{name}{p} " + ",".join(_qref(qc, q) for q in ins.qubits) + ";")
        for q in flips:
            lines.append(f"x {_qref(qc, q)};")
    return "\n".join(lines) + "\n"
