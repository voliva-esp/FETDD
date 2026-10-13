#!/usr/bin/env python3
"""Shor's Factoring Algorithm Benchmark for Arbitrary N and Precision.

Compatible with older and newer Qiskit versions on Python 3.8+.
"""

import argparse
from math import gcd, ceil, log2
from time import time
from fractions import Fraction
import numpy as np

from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector

# Compatibility for transpile and UnitaryGate across different Qiskit versions
try:
    from qiskit import transpile
except ImportError:
    from qiskit.compiler import transpile

try:
    from qiskit.circuit.library import UnitaryGate
except ImportError:
    try:
        from qiskit.extensions import UnitaryGate
    except ImportError:
        from qiskit.circuit.library.generalized_gates import UnitaryGate

from source.Simulate import simulate


def build_modular_exponentiation_matrix(a: int, power: int, N: int, m: int) -> np.ndarray:
    """Generates the 2^m x 2^m unitary permutation matrix for (a^power * x) mod N."""
    dim = 1 << m
    val = pow(a, power, N)
    matrix = np.zeros((dim, dim), dtype=complex)

    for x in range(dim):
        if x < N:
            y = (val * x) % N
        else:
            y = x  # Leave states >= N invariant
        matrix[y, x] = 1.0

    return matrix


def apply_iqft(qc: QuantumCircuit, counting_qubits: list):
    """Applies Inverse Quantum Fourier Transform (IQFT) on counting qubits."""
    n = len(counting_qubits)
    # Swap qubits for endianness alignment
    for i in range(n // 2):
        qc.swap(counting_qubits[i], counting_qubits[n - 1 - i])

    for j in range(n):
        for m_idx in range(j):
            angle = -np.pi / (2 ** (j - m_idx))
            qc.cp(angle, counting_qubits[m_idx], counting_qubits[j])
        qc.h(counting_qubits[j])


def build_shor_circuit(N: int, a: int, num_counting: int):
    """Builds a flat Shor circuit for arbitrary N, base 'a', and counting precision."""
    m_target = ceil(log2(N)) if N > 1 else 1
    total_qubits = num_counting + m_target

    qc = QuantumCircuit(total_qubits)

    counting_qubits = list(range(num_counting))
    target_qubits = list(range(num_counting, total_qubits))

    # 1. Initialize counting qubits in superposition |+>
    for q in counting_qubits:
        qc.h(q)

    # 2. Initialize target register to |1> = |00...01>
    qc.x(target_qubits[0])

    # 3. Controlled Modular Exponentiation: C-U^(2^k) mod N
    for k in range(num_counting):
        power = 2 ** k
        mod_matrix = build_modular_exponentiation_matrix(a, power, N, m_target)
        u_gate = UnitaryGate(mod_matrix, label=f"{a}^{power} mod {N}")
        cu_gate = u_gate.control(1)

        qc.append(cu_gate, [counting_qubits[k]] + target_qubits)

    # 4. Inverse QFT on counting register
    apply_iqft(qc, counting_qubits)

    return qc, num_counting, m_target


def statevector(circuit: QuantumCircuit, use_tdd: bool) -> Statevector:
    """Evaluates the final quantum state of the circuit."""
    if use_tdd:
        tdd = simulate(
            circuit,
            is_input_closed=True,
            is_output_closed=False,
            handler_name="none",
            backend="FTDD",
            contraction_method="k-ops",
            use_tetris=False,
            index_order_method="path",
            force_init=False,
        )
        raw_array = tdd.to_array()

        # Endianness conversion: Big-Endian (TDD) -> Little-Endian (Qiskit)
        n_qubits = circuit.num_qubits
        tensor = raw_array.reshape([2] * n_qubits)
        tensor_reversed = tensor.transpose(list(range(n_qubits))[::-1])
        result = Statevector(tensor_reversed.flatten())
    else:
        result = Statevector(circuit)

    return result


def extract_factors_from_phase(measured_phase_decimal: int, a: int, N: int, num_counting: int):
    """Classical post-processing to recover period 'r' and prime factors."""
    phase = measured_phase_decimal / (2 ** num_counting)
    frac = Fraction(phase).limit_denominator(N)
    r = frac.denominator

    print(f"  Phase measurement: {measured_phase_decimal}/{2**num_counting} -> Phase = {phase:.4f} | Inferred period r = {r}")

    if r % 2 != 0:
        print("  [!] Period 'r' is odd. Retry.")
        return None, None

    val = pow(a, r // 2, N)
    if (val + 1) % N == 0:
        print("  [!] a^(r/2) = -1 (mod N). Trivial period.")
        return None, None

    factor1 = gcd(val - 1, N)
    factor2 = gcd(val + 1, N)

    return factor1, factor2


def run_shor_benchmark(N: int, a: int, num_counting: int, use_tdd: bool):
    if gcd(a, N) != 1:
        raise ValueError(f"Base a={a} is not coprime with N={N}. GCD({a}, {N}) = {gcd(a, N)}")

    circuit, t, m = build_shor_circuit(N, a, num_counting)

    print(f"=== SCALABLE SHOR'S ALGORITHM BENCHMARK ===")
    print(f"Using TDD: {use_tdd}")
    print(f"Factoring N = {N} | Coprime base a = {a}")
    print(f"Counting qubits (precision t): {t}")
    print(f"Target register qubits (m): {m}")
    print(f"Total qubits in circuit:        {circuit.num_qubits}")
    print(f"Total number of gates (Decomposed): {circuit.size()}")
    print(f"Circuit depth:                  {circuit.depth()}")

    t0 = time()
    sv = statevector(circuit, use_tdd)
    execution_time = time() - t0

    counting_probs = sv.probabilities(qargs=list(range(t)))

    print("\n--- Simulation Results ---")
    print(f"Simulation time: {execution_time:.4f} s")
    print("\nMeasured state distribution in counting register (Top p > 0.02):")

    factors_found = set()
    for decimal_state, prob in enumerate(counting_probs):
        if prob > 0.02:
            if use_tdd:
                # 1. Convert to 't'-bit binary
                raw_bin = bin(decimal_state)[2:].zfill(t)

                # 2. Correct Bit-Reversal of the counting register
                bin_str = raw_bin[::-1]
                decimal_state = int(bin_str, 2)
            else:
                bin_str = bin(decimal_state)[2:].zfill(t)
            print(f"\n> State |{bin_str}> (Decimal {decimal_state}) | Probability: {prob:.4f}")
            p, q = extract_factors_from_phase(decimal_state, a, N, t)
            if p and q and p != 1 and p != N:
                factors_found.add(p)
                factors_found.add(q)

    print("\n==========================================")
    if factors_found:
        print(f" SUCCESSFUL FACTORIZATION: {N} = {' x '.join(map(str, sorted(factors_found)))}")
    else:
        print(f" No non-trivial factors obtained in main states.")
    print("==========================================")

    return execution_time


def main():
    parser = argparse.ArgumentParser(
        description="Scalable Shor's Algorithm Benchmark."
    )
    parser.add_argument("--N", type=int, default=15, help="Number to factor")
    parser.add_argument("--a", type=int, default=7, help="Chosen coprime base (GCD(a, N) = 1)")
    parser.add_argument(
        "--counting-qubits",
        type=int,
        default=None,
        help="Number of precision qubits 't' (Default: 2 * ceil(log2(N)))",
    )
    parser.add_argument(
        "--use-tdd", action="store_true", help="Use FTDD simulation engine"
    )
    args = parser.parse_args()

    m = ceil(log2(args.N)) if args.N > 1 else 1
    t = args.counting_qubits if args.counting_qubits is not None else 2 * m

    run_shor_benchmark(N=args.N, a=args.a, num_counting=t, use_tdd=args.use_tdd)


if __name__ == "__main__":
    main()