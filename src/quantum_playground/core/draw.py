"""Compact ASCII circuit drawer (column-packed, one column per gate layer)."""
from __future__ import annotations

from .circuit import Circuit

_SHORT = {"measure": "M", "reset": "|0>", "barrier": "░", "delay": "dly"}


def _label(ins) -> str:
    if ins.name in _SHORT:
        return _SHORT[ins.name]
    base = ins.name
    if ins.name in ("cx", "ccx", "mcx"):
        base = "X"
    elif ins.name in ("cz", "ccz"):
        base = "Z"
    elif ins.name in ("cp", "mcp"):
        base = "P"
    elif ins.name in ("cy", "ch", "crx", "cry", "crz"):
        base = ins.name[1:].upper()
    else:
        base = base.upper()
    if ins.params:
        base += "(" + ",".join(f"{p:.2f}" for p in ins.params) + ")"
    if ins.condition is not None:
        base += "?"
    return base


def draw_text(qc: Circuit, max_columns: int = 120) -> str:
    n = qc.num_qubits
    cols: list[dict[int, str]] = []
    level = [0] * n
    for ins in qc.instructions:
        qs = ins.qubits or tuple(range(n))
        lo, hi = min(qs), max(qs)
        span = range(lo, hi + 1)
        col = max(level[q] for q in span)
        while len(cols) <= col:
            cols.append({})
        cell = cols[col]
        nc = ins.num_controls
        controls = set(ins.qubits[:nc])
        for q in span:
            if q in controls:
                k = ins.qubits.index(q)
                on = ins.ctrl_state is None or (ins.ctrl_state >> k) & 1
                cell[q] = "●" if on else "○"
            elif q in ins.qubits:
                cell[q] = "x" if ins.name in ("swap", "cswap") else _label(ins)
            elif hi > lo and ins.name != "barrier":
                cell[q] = "│"
        if ins.name == "measure":
            cell[ins.qubits[0]] = f"M{ins.clbits[0]}"
        for q in span:
            level[q] = col + 1
    names = []
    for q in range(n):
        reg, i = qc.qubit_register(q)
        names.append(f"{reg.name}[{i}]")
    w0 = max((len(s) for s in names), default=1)
    rows = [f"{names[q]:>{w0}} ─" for q in range(n)]
    for cell in cols[:max_columns]:
        width = max((len(v) for v in cell.values()), default=1)
        for q in range(n):
            v = cell.get(q)
            if v is None:
                rows[q] += "─" * (width + 2)
            elif v == "│":
                rows[q] += "─" + "┼".center(width, "─") + "─"
            else:
                rows[q] += "─" + v.center(width, "─") + "─"
    if len(cols) > max_columns:
        rows = [r + " …" for r in rows]
    return "\n".join(rows)
