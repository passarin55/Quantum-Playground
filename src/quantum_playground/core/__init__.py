"""Core quantum engine: IR, simulators, synthesis and exporters (numpy only)."""
from .circuit import Circuit, CircuitError, Instruction, Register
from .density import DensityMatrix, density_distribution, simulate_density
from .mitigation import ReadoutMitigator, calibration_circuits
from .noise import NOISE_PRESETS, NoiseModel
from .qasm import QasmError, to_qasm2, to_qasm3
from .results import CircuitResult, hellinger_fidelity, total_variation, wilson_interval
from .reversible import permutation_of, truth_table
from .statevector import Statevector, exact_distribution, simulate, unitary_matrix
from .synthesis import (apply_permutation, cancel_adjacent_inverses, emit_network, extend_permutation,
                        synthesize_permutation)

__all__ = [
    "Circuit", "CircuitError", "Instruction", "Register", "DensityMatrix", "density_distribution",
    "simulate_density", "ReadoutMitigator", "calibration_circuits", "NOISE_PRESETS", "NoiseModel",
    "QasmError", "to_qasm2", "to_qasm3", "CircuitResult", "hellinger_fidelity", "total_variation",
    "wilson_interval", "permutation_of", "truth_table", "Statevector", "exact_distribution", "simulate",
    "unitary_matrix", "apply_permutation", "cancel_adjacent_inverses", "emit_network",
    "extend_permutation", "synthesize_permutation",
]
