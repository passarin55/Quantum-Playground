"""Translation between the qplay IR and Qiskit, plus SamplerV2 result parsing.

The SamplerV2 parser never assumes a ``meas`` field (the v4.1/v4.2 bug in the
reference project): it reads each classical register by name, falls back to
scanning the DataBin, and rebuilds per-shot joint bitstrings so multi-register
circuits (teleportation, BB84 with an eavesdropper, ...) analyse correctly.
"""
from __future__ import annotations

import math
from typing import Optional, Sequence

from ..core.circuit import Circuit
from ..core.results import CircuitResult


def _require_qiskit():
    try:
        import qiskit  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Qiskit is not installed. Run: pip install 'quantum-playground-studio[ibm]'") from exc


def to_qiskit(circuit: Circuit):
    """Convert to ``qiskit.QuantumCircuit`` with identically named registers."""
    _require_qiskit()
    from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister

    qregs = [QuantumRegister(r.size, r.name) for r in circuit.qregs]
    cregs = [ClassicalRegister(r.size, r.name) for r in circuit.cregs]
    qc = QuantumCircuit(*qregs, *cregs, name=circuit.name)
    qubits = list(qc.qubits)
    clbits = list(qc.clbits)
    creg_by_bits = {tuple(range(r.start, r.start + r.size)): cregs[i] for i, r in enumerate(circuit.cregs)}

    def emit(ins):
        q = [qubits[i] for i in ins.qubits]
        p = list(ins.params)
        name = ins.name
        if name == "measure":
            qc.measure(q[0], clbits[ins.clbits[0]])
        elif name == "reset":
            qc.reset(q[0])
        elif name == "barrier":
            qc.barrier(*(q or qubits))
        elif name == "delay":
            qc.delay(p[0], q[0], unit="s")
        elif name in ("mcx", "mcp", "ccz") or ins.ctrl_state is not None:
            nc = ins.num_controls
            cs = ins.ctrl_state if ins.ctrl_state is not None else (1 << nc) - 1
            flips = [q[i] for i in range(nc) if not (cs >> i) & 1]
            for f in flips:
                qc.x(f)
            if name in ("mcx", "cx", "ccx"):
                qc.mcx(q[:nc], q[nc])
            elif name in ("mcp", "cp"):
                qc.mcp(p[0], q[:nc], q[nc])
            elif name in ("ccz", "cz"):
                qc.mcp(math.pi, q[:nc], q[nc]) if nc > 2 else (qc.ccz(*q) if nc == 2 else qc.cz(*q))
            else:
                raise ValueError(f"ctrl_state not supported for {name}")
            for f in flips:
                qc.x(f)
        else:
            getattr(qc, name)(*p, *q)

    for ins in circuit.instructions:
        if ins.condition is None:
            emit(ins)
            continue
        bits, value = ins.condition
        if len(bits) == 1:
            with qc.if_test((clbits[bits[0]], value & 1)):
                emit(ins)
        elif tuple(bits) in creg_by_bits:
            with qc.if_test((creg_by_bits[tuple(bits)], value)):
                emit(ins)
        else:  # AND of single-bit tests via nesting
            def nest(k):
                if k == len(bits):
                    emit(ins)
                    return
                with qc.if_test((clbits[bits[k]], (value >> k) & 1)):
                    nest(k + 1)
            nest(0)
    qc.metadata = dict(circuit.metadata)
    return qc


_FROM_QISKIT = {"id", "x", "y", "z", "h", "s", "sdg", "t", "tdg", "sx", "sxdg", "rx", "ry", "rz", "p", "u",
                "swap", "rxx", "ryy", "rzz", "cx", "cy", "cz", "ch", "cp", "crx", "cry", "crz", "cswap",
                "ccx", "ccz", "mcx", "mcp", "measure", "reset", "barrier"}
_ALIASES = {"u1": "p", "cu1": "cp", "u3": "u", "cnot": "cx", "toffoli": "ccx", "fredkin": "cswap",
            "mcphase": "mcp", "mcu1": "mcp"}


def from_qiskit(qc) -> Circuit:
    """Import a (control-flow-free) Qiskit circuit into the IR."""
    out = Circuit(name=qc.name or "imported")
    qindex: dict = {}
    cindex: dict = {}
    for reg in qc.qregs:
        r = out.add_qreg(reg.name, reg.size)
        for i, b in enumerate(reg):
            qindex[b] = r.start + i
    for reg in qc.cregs:
        r = out.add_creg(reg.name, reg.size)
        for i, b in enumerate(reg):
            cindex[b] = r.start + i
    for b in qc.qubits:
        if b not in qindex:
            raise ValueError("Qiskit circuits with register-less qubits are not supported")
    for item in qc.data:
        op = item.operation
        name = _ALIASES.get(op.name, op.name)
        qs = [qindex[b] for b in item.qubits]
        if name == "u2":
            phi, lam = [float(x) for x in op.params]
            out.u(math.pi / 2, phi, lam, qs[0])
            continue
        if name.startswith("mcx") or name in ("c3x", "c4x"):
            name = "mcx"
        if name not in _FROM_QISKIT:
            raise ValueError(f"Cannot import Qiskit instruction {op.name!r}; transpile to a basic gate set first")
        if name == "measure":
            out.measure(qs[0], cindex[item.clbits[0]])
        elif name == "barrier":
            out.barrier(*qs)
        elif name == "mcx":
            out.mcx(qs[:-1], qs[-1])
        elif name == "mcp":
            out.mcp(float(op.params[0]), qs[:-1], qs[-1])
        else:
            out.append(name, qs, [float(x) for x in op.params])
    return out


# ---------------------------------------------------------------- results
def _bitarray(data, name: str):
    for getter in (lambda: data[name], lambda: getattr(data, name)):
        try:
            arr = getter()
            if hasattr(arr, "get_bitstrings"):
                return arr
        except (KeyError, AttributeError, TypeError):
            pass
    return None


def _databin_fields(data) -> list[str]:
    try:
        return list(data.keys())
    except Exception:
        return [n for n in dir(data) if not n.startswith("_") and hasattr(getattr(data, n, None), "get_bitstrings")]


def pub_to_result(pub, registers: Optional[Sequence[tuple[str, int, int]]] = None,
                  metadata: Optional[dict] = None) -> CircuitResult:
    """Convert one SamplerV2 PUB result into a CircuitResult (per-shot memory included)."""
    data = pub.data
    if not registers:
        registers = []
        start = 0
        for name in _databin_fields(data):
            arr = _bitarray(data, name)
            if arr is not None:
                registers.append((name, start, int(arr.num_bits)))
                start += int(arr.num_bits)
    per_reg = []
    shots = None
    for name, start, size in registers:
        arr = _bitarray(data, name)
        if arr is None:
            fields = _databin_fields(data)
            if len(registers) == 1 and len(fields) == 1:
                arr = _bitarray(data, fields[0])
            if arr is None:
                raise RuntimeError(f"SamplerV2 result has no register {name!r}; DataBin fields: {fields}")
        bits = arr.get_bitstrings()
        shots = len(bits) if shots is None else shots
        per_reg.append(bits)
    if shots is None:
        raise RuntimeError("Result contains no classical data")
    memory = ["".join(per_reg[r][s] for r in range(len(per_reg) - 1, -1, -1)) for s in range(shots)]
    counts: dict[str, int] = {}
    for m in memory:
        counts[m] = counts.get(m, 0) + 1
    width = sum(size for _, _, size in registers)
    return CircuitResult(counts=dict(sorted(counts.items())), shots=shots, num_clbits=width,
                         registers=[tuple(r) for r in registers], memory=memory, metadata=dict(metadata or {}))


def isa_metrics(isa) -> dict:
    """Native gate statistics of a transpiled (ISA) circuit."""
    mix: dict[str, int] = {}
    one = two = multi = 0
    active = set()
    for item in isa.data:
        op = item.operation
        if op.name in ("barrier", "delay"):
            continue
        mix[op.name] = mix.get(op.name, 0) + 1
        k = len(item.qubits)
        active.update(isa.find_bit(q).index for q in item.qubits)
        if op.name in ("measure", "reset") or op.name in ("if_else", "for_loop", "while_loop", "switch_case", "box"):
            continue
        if k == 1:
            one += 1
        elif k == 2:
            two += 1
        elif k > 2:
            multi += 1
    return {"depth": isa.depth(), "size": isa.size(), "one_qubit": one, "two_qubit": two,
            "multi_qubit": multi, "active_qubits": len(active), "ops": dict(sorted(mix.items(), key=lambda kv: -kv[1]))}


def measured_physical_qubits(isa) -> dict[int, int]:
    """clbit index -> physical qubit for the last measurement into each clbit."""
    out: dict[int, int] = {}
    for item in isa.data:
        if item.operation.name == "measure":
            out[isa.find_bit(item.clbits[0]).index] = isa.find_bit(item.qubits[0]).index
    return out
