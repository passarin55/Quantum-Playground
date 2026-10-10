"""Exhaustive classical simulation of reversible (X/CX/CCX/MCX/SWAP/CSWAP) circuits.

All 2^n basis inputs are pushed through the circuit simultaneously as a numpy
integer vector, giving the circuit's full truth table in milliseconds.  This is
how every compiled Enigma rotor network is verified *for every input symbol
and every key*, not just for the crib.
"""
from __future__ import annotations

from typing import Optional, Sequence

import numpy as np

from .circuit import Circuit


def truth_table(circuit: Circuit, inputs: Optional[np.ndarray] = None) -> np.ndarray:
    """Return out[i] = basis state reached from basis state i."""
    n = circuit.num_qubits
    if n > 24:
        raise ValueError("truth_table limited to 24 qubits")
    state = np.arange(1 << n, dtype=np.int64) if inputs is None else np.asarray(inputs, dtype=np.int64).copy()
    for ins in circuit.instructions:
        if ins.name in ("barrier", "id", "delay"):
            continue
        if ins.name in ("z", "s", "sdg", "t", "tdg", "rz", "p", "cz", "cp", "crz", "ccz", "mcp", "rzz"):
            continue  # diagonal phases do not change the classical permutation
        if not ins.spec.classical:
            raise ValueError(f"Instruction {ins.name} is not classical-reversible")
        nc = ins.num_controls
        controls, targets = ins.qubits[:nc], ins.qubits[nc:]
        cs = ins.ctrl_state if ins.ctrl_state is not None else (1 << nc) - 1
        mask = np.ones(state.shape, dtype=bool)
        for i, c in enumerate(controls):
            want = (cs >> i) & 1
            mask &= ((state >> c) & 1) == want
        if ins.name in ("swap", "cswap"):
            a, b = targets
            ba, bb = (state >> a) & 1, (state >> b) & 1
            diff = (ba != bb) & mask
            state = np.where(diff, state ^ ((1 << a) | (1 << b)), state)
        else:
            t = targets[0]
            state = np.where(mask, state ^ (1 << t), state)
    return state


def permutation_of(circuit: Circuit, qubits: Sequence[int], fixed: int = 0) -> tuple[int, ...]:
    """Permutation induced on the sub-register ``qubits`` with all other qubits = ``fixed``.

    Raises if the other qubits are not restored (i.e. ancillas left dirty).
    """
    qubits = list(qubits)
    k = len(qubits)
    inputs = []
    for v in range(1 << k):
        s = fixed
        for j, q in enumerate(qubits):
            s = (s & ~(1 << q)) | (((v >> j) & 1) << q)
        inputs.append(s)
    out = truth_table(circuit, np.array(inputs, dtype=np.int64))
    other_mask = ~sum(1 << q for q in qubits)
    result = []
    for s_in, s_out in zip(inputs, out):
        if (int(s_out) & other_mask) != (s_in & other_mask):
            raise ValueError("Circuit leaves work/key qubits modified (not clean)")
        v = 0
        for j, q in enumerate(qubits):
            v |= ((int(s_out) >> q) & 1) << j
        result.append(v)
    return tuple(result)
