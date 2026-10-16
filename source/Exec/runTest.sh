#!/bin/bash

declare -A circuit_name
declare -A circuit_qubits

circuit_name["qpe"]="qpeexact_indep_qiskit"
circuit_name["qft_indep"]="qftentangled_indep_qiskit"
circuit_name["qnn"]="qnn_indep_tket"
circuit_name["qwalk"]="qwalk_d1"
circuit_name["rqc"]="rqc"
circuit_name["ghz"]="ghz"
circuit_name["graph_state"]="graph_state"
circuit_name["real_amplitude"]="realamprandom_indep_qiskit"
circuit_name["amplitude_estimation"]="ae_indep_qiskit"
circuit_name["QFTec"]="qft_qec"

circuit_qubits["qpe"]="15 20 25 30"
circuit_qubits["qft_indep"]="20 50 80 110"
circuit_qubits["qnn"]="15 20 25 30"
circuit_qubits["qwalk"]="10 12 14 15"
circuit_qubits["rqc"]="1 2 3 4"
circuit_qubits["ghz"]="20 30 40 50"
circuit_qubits["graph_state"]="20 30 40 50"
circuit_qubits["real_amplitude"]="15 20 25 30"
circuit_qubits["amplitude_estimation"]="5 10 15 20"
circuit_qubits["QFTec"]="20 25 30 35 40 45 50 55 60 65 70 75 80 85 90 95 100 110 120 135 150 175 200 225 250 275 300 325 350 375 400 450 500 550 600 650 700 750 800 850 900 950 1000"

methods=('seq')
circuit=("QFTec")
tools=('FTDD')
index_order=('default')

echo "Starting simulations..."
for method in "${methods[@]}"; do
  # Making sure script is compatible between Windows and Linux
  method=$(echo $method | tr -d '\r')

  for c in "${circuit[@]}"; do
    # Making sure script is compatible between Windows and Linux
    curr_circuit=$(echo $c | tr -d '\r' | xargs)
    echo " ## Init simulations with [$curr_circuit] circuit..."

    for tool in "${tools[@]}"; do
      # Making sure script is compatible between Windows and Linux
      tool=$(echo $tool | tr -d '\r')
      raw_qubits=${circuit_qubits[$curr_circuit]}
      n_qubits=($raw_qubits)

      if [ ${#n_qubits[@]} -eq 0 ]; then
          echo " [ERROR] no number of qubits found for key: '$curr_circuit'"
          continue
      fi

      for q in "${n_qubits[@]}"; do
        c_full_name=${circuit_name[$curr_circuit]}
        echo " #--#>> Simulating $curr_circuit ($q qubits)..."
        for order in "${index_order[@]}"; do
          timeout 7200 python3 source/Exec/runCircuit.py "$q" "$method" "$curr_circuit" "$c_full_name" "$tool" "$order"
        done
      done
    done
  done
done
