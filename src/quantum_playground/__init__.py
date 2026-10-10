"""Quantum Playground Studio v9 — an over-engineered quantum computing lab.

Sub-packages
------------
core         circuit IR, statevector / density-matrix / reversible simulators,
             permutation synthesis, QASM export, readout mitigation
enigma       historical Enigma M3/M4 + Mini-Enigma, classical cryptanalysis
             (Turing-Welchman bombe, window scans, IoC), quantum Grover oracles
backends     local simulators, Qiskit Aer, IBM Quantum Runtime, AWS Braket,
             persistent job store and execution manager
experiments  17 runnable, self-analysing quantum experiments
web          zero-dependency local web studio (``qplay serve``)
cli          ``qplay`` command-line interface
"""
__version__ = "9.0.0"
