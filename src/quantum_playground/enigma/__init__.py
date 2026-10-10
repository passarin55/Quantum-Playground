"""Enigma lab: historical machines, classical baseline, quantum Grover oracles."""
from .classical import BitSource, KeySheet, generate_keysheet, window_scan
from .machine import (ABC, MINI_ABC, REFLECTORS, ROTORS, Enigma, EnigmaConfig, encrypt, groups, letter_permutations,
                      letters, mini_encrypt, parse_plugboard)
from .quantum import (KeySearchProblem, build_grover_circuit, choose_synthesis, historical_problem, keyed_encryption,
                      mini_problem, optimal_iterations, success_probability, verify_keyed_encryption)

__all__ = [
    "BitSource", "KeySheet", "generate_keysheet", "window_scan", "ABC", "MINI_ABC", "REFLECTORS", "ROTORS",
    "Enigma", "EnigmaConfig", "encrypt", "groups", "letter_permutations", "letters", "mini_encrypt",
    "parse_plugboard", "KeySearchProblem", "build_grover_circuit", "choose_synthesis", "historical_problem",
    "keyed_encryption", "mini_problem", "optimal_iterations", "success_probability", "verify_keyed_encryption",
]
