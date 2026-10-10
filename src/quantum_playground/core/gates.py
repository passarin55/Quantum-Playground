"""Gate library: matrices, inverses and metadata for every instruction in the IR.

Conventions (identical to Qiskit so circuits translate 1:1):

* Qubit 0 is the least-significant bit of a basis-state index.
* A k-qubit gate matrix acts on its *target* qubits with ``targets[0]`` as the
  least-significant bit of the matrix index.
* Controlled gates list their controls first, then their targets.  The optional
  ``ctrl_state`` integer gives the required value of each control (bit i of
  ``ctrl_state`` belongs to control i); the default is "all ones".
"""
from __future__ import annotations

import cmath
import math
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

import numpy as np

SQ2 = 1.0 / math.sqrt(2.0)

_I = np.eye(2, dtype=complex)
_X = np.array([[0, 1], [1, 0]], dtype=complex)
_Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
_Z = np.array([[1, 0], [0, -1]], dtype=complex)
_H = np.array([[1, 1], [1, -1]], dtype=complex) * SQ2
_S = np.array([[1, 0], [0, 1j]], dtype=complex)
_T = np.array([[1, 0], [0, cmath.exp(1j * math.pi / 4)]], dtype=complex)
_SX = 0.5 * np.array([[1 + 1j, 1 - 1j], [1 - 1j, 1 + 1j]], dtype=complex)
_SWAP = np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], dtype=complex)

PAULI = {"I": _I, "X": _X, "Y": _Y, "Z": _Z}


def rx(theta: float) -> np.ndarray:
    c, s = math.cos(theta / 2), math.sin(theta / 2)
    return np.array([[c, -1j * s], [-1j * s, c]], dtype=complex)


def ry(theta: float) -> np.ndarray:
    c, s = math.cos(theta / 2), math.sin(theta / 2)
    return np.array([[c, -s], [s, c]], dtype=complex)


def rz(theta: float) -> np.ndarray:
    return np.array([[cmath.exp(-0.5j * theta), 0], [0, cmath.exp(0.5j * theta)]], dtype=complex)


def phase(lam: float) -> np.ndarray:
    return np.array([[1, 0], [0, cmath.exp(1j * lam)]], dtype=complex)


def u3(theta: float, phi: float, lam: float) -> np.ndarray:
    c, s = math.cos(theta / 2), math.sin(theta / 2)
    return np.array(
        [[c, -cmath.exp(1j * lam) * s], [cmath.exp(1j * phi) * s, cmath.exp(1j * (phi + lam)) * c]],
        dtype=complex,
    )


def _pauli_rotation_2q(p: np.ndarray, theta: float) -> np.ndarray:
    pp = np.kron(p, p)
    return math.cos(theta / 2) * np.eye(4, dtype=complex) - 1j * math.sin(theta / 2) * pp


def rxx(theta: float) -> np.ndarray:
    return _pauli_rotation_2q(_X, theta)


def ryy(theta: float) -> np.ndarray:
    return _pauli_rotation_2q(_Y, theta)


def rzz(theta: float) -> np.ndarray:
    return _pauli_rotation_2q(_Z, theta)


@dataclass(frozen=True)
class GateSpec:
    """Static description of one instruction type."""

    name: str
    num_targets: int                       # qubits the base matrix acts on
    num_params: int = 0
    num_controls: Optional[int] = 0        # None => variable (mcx / mcp)
    matrix: Optional[Callable[..., np.ndarray]] = None
    inverse: Optional[Callable[[tuple], tuple]] = None  # params -> (name, params)
    diagonal: bool = False
    classical: bool = False                 # permutes basis states without phases
    unitary: bool = True
    description: str = ""

    def total_qubits(self, n_controls: int = 0) -> int:
        fixed = self.num_controls if self.num_controls is not None else n_controls
        return fixed + self.num_targets


def _self_inverse(name: str):
    return lambda params: (name, tuple(params))


def _neg(name: str):
    return lambda params: (name, tuple(-p for p in params))


def _pair(other: str):
    return lambda params: (other, ())


_SPECS: dict[str, GateSpec] = {}


def _reg(spec: GateSpec) -> None:
    _SPECS[spec.name] = spec


# ---- single-qubit -----------------------------------------------------------
_reg(GateSpec("id", 1, matrix=lambda: _I, inverse=_self_inverse("id"), diagonal=True, classical=True,
              description="Identity"))
_reg(GateSpec("x", 1, matrix=lambda: _X, inverse=_self_inverse("x"), classical=True, description="Pauli-X (NOT)"))
_reg(GateSpec("y", 1, matrix=lambda: _Y, inverse=_self_inverse("y"), description="Pauli-Y"))
_reg(GateSpec("z", 1, matrix=lambda: _Z, inverse=_self_inverse("z"), diagonal=True, description="Pauli-Z"))
_reg(GateSpec("h", 1, matrix=lambda: _H, inverse=_self_inverse("h"), description="Hadamard"))
_reg(GateSpec("s", 1, matrix=lambda: _S, inverse=_pair("sdg"), diagonal=True, description="Phase S = sqrt(Z)"))
_reg(GateSpec("sdg", 1, matrix=lambda: _S.conj().T, inverse=_pair("s"), diagonal=True, description="S dagger"))
_reg(GateSpec("t", 1, matrix=lambda: _T, inverse=_pair("tdg"), diagonal=True, description="T = fourth root of Z"))
_reg(GateSpec("tdg", 1, matrix=lambda: _T.conj().T, inverse=_pair("t"), diagonal=True, description="T dagger"))
_reg(GateSpec("sx", 1, matrix=lambda: _SX, inverse=_pair("sxdg"), description="sqrt(X)"))
_reg(GateSpec("sxdg", 1, matrix=lambda: _SX.conj().T, inverse=_pair("sx"), description="sqrt(X) dagger"))
_reg(GateSpec("rx", 1, 1, matrix=rx, inverse=_neg("rx"), description="X rotation"))
_reg(GateSpec("ry", 1, 1, matrix=ry, inverse=_neg("ry"), description="Y rotation"))
_reg(GateSpec("rz", 1, 1, matrix=rz, inverse=_neg("rz"), diagonal=True, description="Z rotation"))
_reg(GateSpec("p", 1, 1, matrix=phase, inverse=_neg("p"), diagonal=True, description="Phase gate P(lambda)"))
_reg(GateSpec("u", 1, 3, matrix=u3, inverse=lambda p: ("u", (-p[0], -p[2], -p[1])),
              description="Generic single-qubit U(theta, phi, lambda)"))

# ---- two-qubit, uncontrolled ---------------------------------------------------
_reg(GateSpec("swap", 2, matrix=lambda: _SWAP, inverse=_self_inverse("swap"), classical=True, description="SWAP"))
_reg(GateSpec("rxx", 2, 1, matrix=rxx, inverse=_neg("rxx"), description="XX interaction exp(-i theta/2 XX)"))
_reg(GateSpec("ryy", 2, 1, matrix=ryy, inverse=_neg("ryy"), description="YY interaction exp(-i theta/2 YY)"))
_reg(GateSpec("rzz", 2, 1, matrix=rzz, inverse=_neg("rzz"), diagonal=True, description="ZZ interaction exp(-i theta/2 ZZ)"))

# ---- controlled ----------------------------------------------------------------
_reg(GateSpec("cx", 1, num_controls=1, matrix=lambda: _X, inverse=_self_inverse("cx"), classical=True, description="CNOT"))
_reg(GateSpec("cy", 1, num_controls=1, matrix=lambda: _Y, inverse=_self_inverse("cy"), description="Controlled-Y"))
_reg(GateSpec("cz", 1, num_controls=1, matrix=lambda: _Z, inverse=_self_inverse("cz"), diagonal=True, description="Controlled-Z"))
_reg(GateSpec("ch", 1, num_controls=1, matrix=lambda: _H, inverse=_self_inverse("ch"), description="Controlled-H"))
_reg(GateSpec("cp", 1, 1, num_controls=1, matrix=phase, inverse=_neg("cp"), diagonal=True, description="Controlled phase"))
_reg(GateSpec("crx", 1, 1, num_controls=1, matrix=rx, inverse=_neg("crx"), description="Controlled RX"))
_reg(GateSpec("cry", 1, 1, num_controls=1, matrix=ry, inverse=_neg("cry"), description="Controlled RY"))
_reg(GateSpec("crz", 1, 1, num_controls=1, matrix=rz, inverse=_neg("crz"), diagonal=True, description="Controlled RZ"))
_reg(GateSpec("cswap", 2, num_controls=1, matrix=lambda: _SWAP, inverse=_self_inverse("cswap"), classical=True,
              description="Fredkin (controlled SWAP)"))
_reg(GateSpec("ccx", 1, num_controls=2, matrix=lambda: _X, inverse=_self_inverse("ccx"), classical=True, description="Toffoli"))
_reg(GateSpec("ccz", 1, num_controls=2, matrix=lambda: _Z, inverse=_self_inverse("ccz"), diagonal=True, description="CCZ"))
_reg(GateSpec("mcx", 1, num_controls=None, matrix=lambda: _X, inverse=_self_inverse("mcx"), classical=True,
              description="Multi-controlled X"))
_reg(GateSpec("mcp", 1, 1, num_controls=None, matrix=phase, inverse=_neg("mcp"), diagonal=True,
              description="Multi-controlled phase"))

# ---- non-unitary ---------------------------------------------------------------
_reg(GateSpec("measure", 1, unitary=False, description="Z-basis measurement"))
_reg(GateSpec("reset", 1, unitary=False, description="Reset to |0>"))
_reg(GateSpec("barrier", 0, unitary=False, num_controls=None, description="Scheduling barrier"))
_reg(GateSpec("delay", 1, 1, unitary=False, description="Idle for a duration (seconds)"))

GATES = _SPECS
UNITARY_GATES = tuple(n for n, s in _SPECS.items() if s.unitary)
ONE_QUBIT_GATES = tuple(n for n, s in _SPECS.items() if s.unitary and s.num_targets == 1 and s.num_controls == 0)


def spec(name: str) -> GateSpec:
    try:
        return _SPECS[name]
    except KeyError:
        raise ValueError(f"Unknown gate {name!r}. Known: {', '.join(sorted(_SPECS))}") from None


def base_matrix(name: str, params: Sequence[float] = ()) -> np.ndarray:
    s = spec(name)
    if s.matrix is None:
        raise ValueError(f"{name} has no matrix")
    return s.matrix(*params) if s.num_params else s.matrix()


def num_controls(name: str, num_qubits: int) -> int:
    s = spec(name)
    if s.num_controls is None:
        return num_qubits - s.num_targets
    return s.num_controls


def full_matrix(name: str, params: Sequence[float] = (), n_qubits: Optional[int] = None,
                ctrl_state: Optional[int] = None) -> np.ndarray:
    """Dense matrix of a (possibly controlled) gate over all of its qubits.

    Qubit ordering: controls first (least-significant), then targets.
    """
    s = spec(name)
    u = base_matrix(name, params)
    nc = num_controls(name, n_qubits if n_qubits is not None else s.total_qubits())
    if nc == 0:
        return u
    nt = s.num_targets
    dim = 1 << (nc + nt)
    out = np.eye(dim, dtype=complex)
    want = ((1 << nc) - 1) if ctrl_state is None else ctrl_state
    tdim = 1 << nt
    for t_in in range(tdim):
        for t_out in range(tdim):
            i = want | (t_out << nc)
            j = want | (t_in << nc)
            out[i, j] = u[t_out, t_in]
    return out
