#!/usr/bin/env python3
"""Quantum Magnetism Simulation Benchmark (1D Ising Model on a 10-Qubit Chain).

Recreates the exact structure of the QASM file:
  1. Initial state in superposition.
  2. Rzz gates decomposed into CX - RZ - CX between neighbors (i, i+1).
  3. Rx rotations decomposed into H - RZ - H.
  4. Expectation value calculation of the 1D Ising Hamiltonian energy:
     H = - J * sum(Z_i Z_{i+1}) - h_x * sum(X_i)
"""

import argparse
from time import time
import numpy as np

from qiskit import QuantumCircuit
from qiskit.quantum_info import SparsePauliOp, Statevector

from source.Simulate import simulate


def build_ising_1d_circuit(num_qubits, gamma_angles, beta_angles):
    """Builds a 1D QAOA/VQE-style circuit equivalent to the QASM pattern."""
    qc = QuantumCircuit(num_qubits)
    depth = len(gamma_angles)

    # Initial state: |+>^(10)
    qc.h(range(num_qubits))

    for p in range(depth):
        gamma = gamma_angles[p]
        beta = beta_angles[p]

        # 1. Interaction layer Rzz(gamma) between nearest neighbors (0-1, 1-2, ..., 8-9)
        for i in range(num_qubits - 1):
            qc.cx(i, i + 1)
            qc.rz(2 * gamma, i + 1)
            qc.cx(i, i + 1)

        # 2. Transverse field layer Rx(beta) = H - RZ(2*beta) - H
        for i in range(num_qubits):
            qc.h(i)
            qc.rz(2 * beta, i)
            qc.h(i)

    return qc


def build_ising_1d_hamiltonian(num_qubits, J=1.0, h_x=0.5):
    """Builds the 1D Ising Hamiltonian: H = - J sum(Z_i Z_{i+1}) - h_x sum(X_i)."""
    pauli_list = []

    # Interaction terms -J * Z_i Z_{i+1}
    for i in range(num_qubits - 1):
        label = ["I"] * num_qubits
        # Qiskit uses Little-Endian ordering: qubit 0 is on the far right
        label[num_qubits - 1 - i] = "Z"
        label[num_qubits - 1 - (i + 1)] = "Z"
        pauli_list.append(("".join(label), -J))

    # Transverse field terms -h_x * X_i
    for i in range(num_qubits):
        label = ["I"] * num_qubits
        label[num_qubits - 1 - i] = "X"
        pauli_list.append(("".join(label), -h_x))

    return SparsePauliOp.from_list(pauli_list)


def statevector(circuit, use_tdd):
    """Evaluates the final quantum state of the circuit.

    THIS is where you will connect your simulator by replacing this function.
    """
    result = None
    if use_tdd:
        tdd = simulate(
            circuit,
            is_input_closed=True,
            is_output_closed=False,
            handler_name="none",
            backend="FTDD",
            contraction_method="k-ops",
            use_tetris=True,
            index_order_method="default",
            force_init=False,
        )
        result = Statevector(tdd.to_array())
    else:
        result = Statevector(circuit)
    return result


def run_ising_benchmark(num_qubits, depth, seed, use_tdd):
    rng = np.random.default_rng(seed)

    # Test angles
    gamma_angles = rng.uniform(0.1, 1.5, depth)
    beta_angles = rng.uniform(0.1, 1.5, depth)

    circuit = build_ising_1d_circuit(num_qubits, gamma_angles, beta_angles)
    hamiltonian = build_ising_1d_hamiltonian(num_qubits)

    print(f"Using TDD: {use_tdd}")
    print(f"1D Chain Ising Circuit: N={num_qubits} qubits, Depth p={depth}")
    print(f"Total number of gates: {circuit.size()}")
    print(f"Operation breakdown: {dict(circuit.count_ops())}")

    t0 = time()
    sv = statevector(circuit, use_tdd)
    execution_time = time() - t0

    energy = float(sv.expectation_value(hamiltonian).real)

    print("\n--- Evaluation Result ---")
    print(f"Calculated energy <H>:   {energy:.6f}")
    print(f"Simulation time:        {execution_time:.4f} s")

    return energy, execution_time


def main():
    parser = argparse.ArgumentParser(
        description="1D Ising Simulation Benchmark (QASM Pattern)."
    )
    parser.add_argument(
        "--qubits", type=int, default=10, help="Number of qubits in the chain"
    )
    parser.add_argument("--depth", type=int, default=1, help="Number of layers (p)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--use-tdd", type=bool, default=False)
    args = parser.parse_args()

    run_ising_benchmark(
        num_qubits=args.qubits,
        depth=args.depth,
        seed=args.seed,
        use_tdd=args.use_tdd,
    )


if __name__ == "__main__":
    main()