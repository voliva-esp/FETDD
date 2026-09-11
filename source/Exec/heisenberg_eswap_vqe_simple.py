#!/usr/bin/env python3
"""Minimal Qiskit VQE example for the periodic Heisenberg model.

This educational version intentionally uses only:

  1. a singlet-pair initial state;
  2. the eSWAP ansatz from Fig. 4 of Seki et al. (without symmetry projection);
  3. exact state-vector expectation values;
  4. parameter-shift gradients; and
  5. fixed-step gradient descent.

Install dependencies and run, for example:

    pip install numpy qiskit
    python heisenberg_eswap_vqe_simple.py --qubits 4 --depth 1

The dense exact diagonalization used for comparison is intended for small
teaching examples (roughly N <= 10), not large calculations.
"""

import argparse

import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit import ParameterVector
from qiskit.quantum_info import SparsePauliOp, Statevector
from source.Simulate import simulate


def append_eswap(circuit, q0, q1, theta):
    """Append exp(-i theta SWAP/2), up to an irrelevant global phase.

    SWAP = (I + XX + YY + ZZ)/2, so the non-global part is

        RXX(theta/2) RYY(theta/2) RZZ(theta/2).
    """
    circuit.rxx(theta / 2, q0, q1)
    circuit.ryy(theta / 2, q0, q1)
    circuit.rzz(theta / 2, q0, q1)


def make_ansatz(num_qubits, depth):
    """Construct the singlet-pair plus D-layer eSWAP ansatz."""
    if num_qubits < 4 or num_qubits % 2 != 0:
        raise ValueError("The number of qubits must be even and at least 4.")

    parameters = ParameterVector("theta", num_qubits * depth)
    circuit = QuantumCircuit(num_qubits)

    # Qiskit starts in |0...0>.  Starting each pair in |11>, H followed by
    # CNOT prepares (|01> - |10>)/sqrt(2), i.e. a spin singlet.
    circuit.x(range(num_qubits))
    for q in range(0, num_qubits, 2):
        circuit.h(q)
        circuit.cx(q, q + 1)

    # Each layer contains N eSWAP gates in two brick-wall time steps.
    p = 0
    for _ in range(depth):
        # (2,3), (4,5), ..., (N,1) in the paper's 1-based notation.
        for q in range(1, num_qubits - 1, 2):
            append_eswap(circuit, q, q + 1, parameters[p])
            p += 1
        append_eswap(circuit, num_qubits - 1, 0, parameters[p])
        p += 1

        # (1,2), (3,4), ..., (N-1,N).
        for q in range(0, num_qubits, 2):
            append_eswap(circuit, q, q + 1, parameters[p])
            p += 1

    return circuit, parameters


def make_heisenberg_hamiltonian(num_qubits, coupling=1.0):
    """H = J/4 sum_i (X_i X_{i+1} + Y_i Y_{i+1} + Z_i Z_{i+1})."""
    terms = []
    for q in range(num_qubits):
        r = (q + 1) % num_qubits
        for pauli in ("XX", "YY", "ZZ"):
            terms.append((pauli, [q, r], coupling / 4))
    return SparsePauliOp.from_sparse_list(terms, num_qubits=num_qubits)


def statevector(circuit, parameters, values, use_tdd=True):
    """Evaluate the parameterized circuit and return its state vector."""
    parameter_map = dict(zip(parameters, values))
    bound_circuit = circuit.assign_parameters(parameter_map)
    result = None
    if use_tdd:
        tdd = simulate(bound_circuit, is_input_closed=True, is_output_closed=False, handler_name="none",
                       backend="FTDD", contraction_method="k-ops", use_tetris=True, index_order_method="default",
                       force_init=False)
        result = Statevector(tdd.to_array())
    else:
        result = Statevector(bound_circuit)
    return result


def energy(circuit, parameters, values, hamiltonian, use_tdd):
    """Return <psi(theta)|H|psi(theta)> exactly."""
    state = statevector(circuit, parameters, values, use_tdd)
    return float(state.expectation_value(hamiltonian).real)


def parameter_shift_gradient(circuit, parameters, values, hamiltonian, use_tdd):
    """Calculate every dE/dtheta_i with the parameter-shift rule.

    Since eSWAP(theta) = exp(-i theta SWAP/2),

      dE/dtheta_i = [E(theta_i + pi/2) - E(theta_i - pi/2)] / 2.

    This is simple and close to how gradients can be measured on quantum
    hardware, although it requires two energy evaluations per parameter.
    """
    gradient = np.zeros_like(values)
    shift = np.pi / 2

    for i in range(len(values)):
        plus = values.copy()
        minus = values.copy()
        plus[i] += shift
        minus[i] -= shift

        energy_plus = energy(circuit, parameters, plus, hamiltonian, use_tdd)
        energy_minus = energy(circuit, parameters, minus, hamiltonian, use_tdd)
        gradient[i] = (energy_plus - energy_minus) / 2

    return gradient


def exact_ground_state(hamiltonian):
    """Dense exact diagonalization for a small reference system."""
    import scipy.sparse.linalg as spla
    sparse_matrix = hamiltonian.to_matrix(sparse=True)
    eigenvalues, eigenvectors = spla.eigsh(sparse_matrix, k=1, which="SA")

    return float(eigenvalues[0].real), Statevector(eigenvectors[:, 0])


def run_vqe(num_qubits, depth, iterations, learning_rate, seed,
            print_every, use_tdd):
    from time import time
    print(f"Using TDD: {use_tdd}")
    circuit, parameters = make_ansatz(num_qubits, depth)
    hamiltonian = make_heisenberg_hamiltonian(num_qubits)
    exact_energy, exact_state = exact_ground_state(hamiltonian)

    rng = np.random.default_rng(seed)
    values = rng.uniform(-0.2, 0.2, len(parameters))

    print(f"N={num_qubits}, D={depth}, parameters={len(parameters)}")
    print(f"Exact ground-state energy: {exact_energy:.12f}")
    print("iteration\tenergy\terror\tmax|gradient|\tTime(s)")
    t = time()

    for iteration in range(iterations):
        current_energy = energy(circuit, parameters, values, hamiltonian, use_tdd)
        gradient = parameter_shift_gradient(
            circuit, parameters, values, hamiltonian, use_tdd
        )

        if iteration % print_every == 0 or iteration == iterations - 1:
            t2 = time()
            print(
                f"{iteration:9d}\t{current_energy: .12f}\t"
                f"{current_energy - exact_energy: .3e}\t"
                f"{np.max(np.abs(gradient)): .3e}\t"
                f"\t{t2 - t}"
            )
            t = t2

        # The complete optimization rule: fixed-step steepest descent.
        values = values - learning_rate * gradient

    final_state = statevector(circuit, parameters, values, use_tdd=use_tdd)
    final_energy = float(final_state.expectation_value(hamiltonian).real)
    fidelity = abs(exact_state.inner(final_state)) ** 2
    import source.cpp.build.cTDD as cTDD
    cTDD.Clear_TDD()

    print("\nFinal result")
    print(f"VQE energy:        {final_energy:.12f}")
    print(f"Exact energy:      {exact_energy:.12f}")
    print(f"Energy error:      {final_energy - exact_energy:.3e}")
    print(f"Ground fidelity:   {fidelity:.10f}")

    return values, final_energy, fidelity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qubits", type=int, default=20)
    parser.add_argument("--depth", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--learning-rate", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--print-every", type=int, default=2)
    parser.add_argument("--use-tdd", type=bool, default=False)
    args = parser.parse_args()

    run_vqe(
        num_qubits=args.qubits,
        depth=args.depth,
        iterations=args.iterations,
        learning_rate=args.learning_rate,
        seed=args.seed,
        print_every=args.print_every,
        use_tdd=args.use_tdd,
    )


if __name__ == "__main__":
    main()
