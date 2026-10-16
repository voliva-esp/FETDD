from qiskit import QuantumCircuit

from source.Simulate import simulate
from math import pi
import re


class DynamicQasm3Parser:
    """
    Motor independiente para parsear y descomponer dinámicamente
    archivos OpenQASM 3.0 para versiones clásicas de Qiskit (0.39.5).
    Soporta registros nombrados (q[0]) y qubits físicos llanos ($0).
    """

    def __init__(self, content):
        self.content = content
        self.gate_definitions = {}
        self.qubit_map = {}
        self.total_qubits = 0
        self.total_bits = 0
        self.qc = None

    def _extract_macros(self):
        gate_blocks = re.findall(r'gate\s+(\w+)(?:\(([^)]*)\))?\s+([^{]+)\{\s*([^}]+)\}', self.content)
        for gate_name, params_str, qubits_str, body_str in gate_blocks:
            gate_params = [p.strip() for p in params_str.split(',') if p.strip()] if params_str else []
            gate_qubits = [q.strip() for q in qubits_str.split(',') if q.strip()]
            body_lines = [line.strip() for line in body_str.split(';') if line.strip()]

            self.gate_definitions[gate_name] = {
                'params': gate_params,
                'qubits': gate_qubits,
                'body': body_lines
            }

    def _build_registers(self):
        # 1. Buscar registros de qubits nombrados clásicos (ej: qubit[4] q;)
        qubit_matches = re.findall(r'qubit\[(\d+)\]\s+(\w+);', self.content)
        for size, name in qubit_matches:
            size = int(size)
            for i in range(size):
                self.qubit_map[f"{name}[{i}]"] = self.total_qubits + i
            self.total_qubits += size

        # 2. DETECCIÓN AUTOMÁTICA DE QUBITS FÍSICOS ($0, $1, ...)
        # Si el circuito usa la notación '$', extraemos todos los números únicos de qubits referenciados
        physical_qubits = re.findall(r'\$(\d+)', self.content)
        if physical_qubits:
            # Encontrar el índice de qubit más alto para dimensionar correctamente el circuito
            max_physical_index = max(int(idx) for idx in physical_qubits)
            # Si no había registros nombrados, inicializamos el conteo desde el máximo encontrado
            if self.total_qubits <= max_physical_index:
                # El tamaño total del circuito debe albergar hasta el qubit max_index
                for i in range(max_physical_index + 1):
                    if f"${i}" not in self.qubit_map:
                        self.qubit_map[f"${i}"] = i
                self.total_qubits = max_physical_index + 1

        # 3. Mapear registros clásicos de bits para mediciones
        bit_matches = re.findall(r'bit\[(\d+)\]\s+(\w+);', self.content)
        self.total_bits = sum(int(size) for size, _ in bit_matches)

        # Instanciar el circuito final con las dimensiones unificadas calculadas
        self.qc = QuantumCircuit(self.total_qubits, self.total_bits)

    def _execute_instruction(self, name, value_args, qubit_args):
        # Caso A: Es una superpuerta registrada (Unrolling dinámico)
        if name in self.gate_definitions:
            macro = self.gate_definitions[name]
            local_qubit_map = dict(zip(macro['qubits'], qubit_args))
            local_param_map = dict(zip(macro['params'], value_args))

            for sub_line in macro['body']:
                sub_match = re.match(r'(\w+)(?:\(([^)]*)\))?\s+(.+)', sub_line)
                if sub_match:
                    sub_name = sub_match.group(1)
                    sub_params_str = sub_match.group(2)
                    sub_qubits_str = sub_match.group(3)

                    sub_values = []
                    if sub_params_str:
                        for p in sub_params_str.split(','):
                            p = p.strip()
                            # 1. Sustituir las variables de la macro (ej: 'p0') por sus valores numéricos en formato de texto
                            for macro_p_name, macro_p_val in local_param_map.items():
                                p = p.replace(macro_p_name, str(macro_p_val))
                            sub_values.append(p)

                    real_sub_qubits = [local_qubit_map[q.strip()] for q in sub_qubits_str.split(',')]
                    self._execute_instruction(sub_name, sub_values, real_sub_qubits)

        # Caso B: Es una compuerta nativa de Qiskit o de un solo qubit depreciada
        elif hasattr(self.qc, name) or name in ["U", "u2", "u3"]:
            qc_indices = [self.qubit_map[q] for q in qubit_args]
            evaluated_params = []

            # 2. EVALUACIÓN ARITMÉTICA COMPLETA AL LLEGAR A LA COMPUERTA BASE
            for val in value_args:
                try:
                    # Resolvemos operaciones como '0.5*5.28' o expresiones con 'pi'
                    expr = str(val).replace('pi', '3.141592653589793')
                    evaluated_params.append(float(eval(expr)))
                except Exception:
                    evaluated_params.append(val)

            # --- INTERCEPCIÓN Y TRADUCCIÓN DE COMPUERTAS DEPRECIADAS ---
            if name == "u2":
                phi, lam = evaluated_params[0], evaluated_params[1]
                self.qc.u(3.141592653589793 / 2, phi, lam, *qc_indices)
            elif name in ["U", "u3"]:
                theta, phi, lam = evaluated_params[0], evaluated_params[1], evaluated_params[2]
                self.qc.u(theta, phi, lam, *qc_indices)
            else:
                # Comportamiento normal para el resto de compuertas nativas (p, cx, h, t, etc.)
                func = getattr(self.qc, name)
                func(*evaluated_params, *qc_indices)
        else:
            print(f"Warning: Instrucción '{name}' no reconocida en el pipeline.")

    def parse(self):
        self._extract_macros()
        self._build_registers()

        clean_content = re.sub(r'gate\s+\w+(?:\([^)]*\))?\s+[^{]+\{[^}]+\}', '', self.content)

        for line in clean_content.split('\n'):
            line = line.strip()
            if not line or line.startswith("//") or line.startswith("OPENQASM") or line.startswith(
                    "include") or line.startswith("barrier"):
                continue

            if " = measure " in line:
                continue

            gate_match = re.match(r'(\w+)(?:\(([^)]*)\))?\s+(.+);', line)
            if gate_match:
                g_name = gate_match.group(1)
                g_params_str = gate_match.group(2)
                g_qubits_str = gate_match.group(3)

                g_params = [p.strip() for p in g_params_str.split(',')] if g_params_str else []
                g_qubits = [q.strip() for q in g_qubits_str.split(',')]

                self._execute_instruction(g_name, g_params, g_qubits)

        return self.qc


def load_circuit_safely(full_path):
    """
    Detecta automáticamente la versión del archivo QASM
    y lo carga usando el lector adecuado de Qiskit.
    """
    with open(full_path, 'r') as f:
        first_line = f.readline()
        while "OPENQASM" not in first_line:
            first_line = f.readline()

    if "OPENQASM 3" in first_line:
        with open(full_path, 'r') as f:
            content = f.read()
        # Si es QASM 3.0, delegamos toda la lógica al motor externo
        parser = DynamicQasm3Parser(content)
        circuit = parser.parse()
        circuit.qasm(filename=path + file_name + '_VERIFICADO.qasm')
        return circuit
    else:
        # Si es QASM 2.0 (o no se especifica), usamos tu método clásico habitual
        return QuantumCircuit.from_qasm_file(full_path)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 6:
        raise ValueError("Incorrect usage of runCircuit file. \n Correct usage: \n   $ python runCircuit.py " +
                         "<n_qubits> <contraction_method> <folder_name> <circuit_name> (<tool> <index_order>)" +
                         "  These are the arguments you used: \n  " + str(sys.argv))
    n_qubits = int(sys.argv[1])
    contraction_method = sys.argv[2]
    folder_name = sys.argv[3]
    circuit_name = sys.argv[4]
    tool = "FTDD"
    index_order = "default"
    if len(sys.argv) == 6:
        tool = sys.argv[5]
    if len(sys.argv) == 7:
        tool = sys.argv[5]
        index_order = sys.argv[6]
    use_slicing = False
    is_input_closed = True
    is_output_closed = False
    use_tetris = False
    n_indices = 0
    slicing_method = "max"
    path=f"./Benchmarks/MQTbench/{folder_name}/"
    file_name = f"{circuit_name}_{n_qubits}"
    circuit = load_circuit_safely(path + file_name + '.qasm')
    circuit.name = circuit_name

    result = simulate(circuit, use_slicing=use_slicing, contraction_method=contraction_method,
                      is_input_closed=is_input_closed, is_output_closed=is_output_closed,
                      use_tetris=use_tetris, n_indices=n_indices, slicing_method=slicing_method,
                      backend=tool, handler_name="print", index_order_method=index_order)


