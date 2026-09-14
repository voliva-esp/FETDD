"""

Modified by Vicente Lopez (voliva@uji.es). Modifications will be marked with @romOlivo.

  - Slight optimization of PyTN_2_cTN

"""

from source.TDD_Q import squeezeTN, squeezeTN_ultra, TNtoCotInput, generate_close_indices, cir_2_tn_lbl, \
    get_real_qubit_num, add_inputs, add_outputs
from source.utils import FileOutputHandler, PrintOutputHandler, HybridOutputHandler, OutputHandler
from source.TN import Index, Tensor, TensorNetwork, contTensor
from source.IndexOrder import calculate_order, INDEX_ORDER_DEFAULT
import numpy as np

global handler
global ctdd_has_init


def get_cotengra_configuration():
    """
        @romOlivo: Added to configurate cotengra and use the same configuration in all methods.
    """
    import cotengra as ctg
    return ctg.HyperOptimizer(
            minimize=f'combo-{56}',
            max_repeats=512,
            max_time=60,
            progbar=True,
        )


def apply_full_tetris(tn, depth):
    """
        romOlivo: This method was added in order to simplify and reduce the number of error in the application of Tetris
    """
    n = tn.qubits_num
    tensors_tetris = squeezeTN(tn.tensors, n, depth)
    tensors_tetris = squeezeTN_ultra(tensors_tetris, n, depth)
    new_tn = TensorNetwork(tensors_tetris, tn.tn_type, n)
    new_tn.is_input_close = tn.is_input_close
    new_tn.is_output_close = tn.is_output_close
    return new_tn


def calculate_path(p_tnn, method, tensors_to_slice=()):
    """
        romOlivo: This method is added to encapsulate all the methods that calculates the contraction path of a circuit.
        Input variables:
        p_tn --------------> Tensor Network you want to calculate the contraction path
        method ------------> Str with the method want to calculate the path. Could be 'seq', 'cot', 'pair or 'spair'.
        tensors_to_slice --> Array with the positions of the tensors to slice. Only used with 'spair'
        Returning:
        path --------------> Contains the calculated contraction path
    """
    path = None
    p_tn = p_tnn.generate_tn()
    n = p_tn.qubits_num
    if method == 'cot':
        tensor_list, open_indices, size_dict, arrays, oe_input = TNtoCotInput(p_tn, n)
        opt = get_cotengra_configuration()
        tree = opt.search(tensor_list, open_indices, size_dict)
        path = tree.get_path()
    elif method == 'pair':
        path = p_tn.get_pairing_path()
    elif method == 'spair':
        tensors_to_slice = p_tnn.get_tensors_to_slice()
        path = p_tn.get_smart_pairing_path(tensors_to_slice)
    elif method == 'k-ops':
        from DDPathGenerator import PathGenerator, PATH_KOPS
        tensor_list, open_indices, size_dict, arrays, oe_input = TNtoCotInput(p_tn, n)
        closed_indices = generate_close_indices(p_tn)
        pg = PathGenerator(tensor_list, closed_indices)
        path = pg.generate_path(PATH_KOPS)
    else:
        path = p_tn.get_seq_path()
    return path


def get_order_max(tn, n=1):
    """
        romOlivo: Gets the indices that are used in more tensors
        Input variables:
        tn -------> Tensor Network
        n --------> Number of indices to return
        Returning:
        indices --> Str name of the indices
    """
    # return ['x10_2', 'x15_2', 'x6_2']
    tn.get_index_set()
    count_indices = [(tn.index_count[index], index) for index in tn.index_count.keys()]
    count_indices.sort(reverse=True)
    indices = [count_indices[i][1] for i in range(n)]
    return indices


def get_slice_cot(tn, n_qubits, n=1):
    """
        romOlivo: Gets the indices using cotengra
        Input variables:
        tn -------> Tensor Network
        n_qubits--> Number of qubits of the TN
        n --------> Number of indices to return
        Returning:
        indices --> Str name of the indices
    """
    tensor_list, open_indices, size_dict, arrays, oe_input = TNtoCotInput(tn, n_qubits)
    opt = get_cotengra_configuration()
    tree = opt.search(tensor_list, open_indices, size_dict)
    result = tree.slice(target_slices=2**n, allow_outer=False)
    return result.sliced_inds


def get_sliced_indices(tn, n, slicing_method, n_qubits=None):
    """
        romOlivo: Gets the indices to sliced, using the specified method
        Input variables:
        tn --------------> Tensor Network
        n ---------------> Number of indices to return
        slicing_method --> Method to use to calculate the indices. Can be 'max' or 'cot'
        n_qubits --------> Number of qubits of the TN
        Returning:
        indices --> Str name of the indices
    """
    indices = ()
    if slicing_method == "max":
        indices = get_order_max(tn, n)
    elif slicing_method == "cot":
        indices = get_slice_cot(tn, n_qubits, n)
    return indices


def replace_tensor(value, indx, tn, all_index=None, all_tensors=None):
    """
        romOlivo: This method modify the tensor network by replacing the index to slice to some new indices
          which matches the new index of the new tensors that are put to give a concrete value to the index.
        Input variables:
        value --------> Value to set the index. Only can be 0 or 1.
        indx ---------> Str name of the index to slice.
        tn -----------> Original Tensor Network.
        all_index ----> Array with all indices of the TN.
        all_tensors --> Array to store the positions of the sliced tensors. If 'None', it will not store the positions.
        Returning:
        Nothing. All the changes will be reflected in the tn and all_index parameters.
    """
    from copy import deepcopy
    U0 = np.array([1, 0])
    U1 = np.array([0, 1])
    MATRICES = [U0, U1]
    tensor_to_add = []
    tensors_to_remove = []
    for j in range(len(tn.tensors)):
        tensor = tn.tensors[j]
        tensor_to_insert = None
        tensors_to_contract = []
        for i in range(len(tensor.index_set)):
            if tensor.index_set[i].key == indx:
                if all_tensors is not None:
                    all_tensors.add(j)
                if tensor_to_insert is None:
                    tensor_to_insert = deepcopy(tensor)
                tensor_to_insert.index_set[i].key = f"{indx}#{j}"
                new_tensor = Tensor(MATRICES[value],
                                    [Index(f"{indx}#{j}", tensor.index_set[i].idx)],
                                    'in',
                                    [tensor.qubits[i // 2]]  # There is 2 indices for each qubit
                                    )
                tensors_to_contract.append(new_tensor)
        if tensor_to_insert is not None:
            for tensor in tensors_to_contract:
                tensor_to_insert = contTensor(tensor_to_insert, tensor)
            tn.tensors[j] = tensor_to_insert
    for tensor in tensors_to_remove:
        tn.tensors.remove(tensor)
    for tensor in tensor_to_add:
        tn.tensors.append(tensor)
    if all_index is not None and indx in all_index:
        all_index.remove(indx)


def slicing(tn, all_index, n=1, slicing_method='max', n_qubits=None, tensors_to_slice=None):
    """
        romOlivo: Generates copies of the tensor network given as input in which some indices were sliced.
        Input variables:
        tn ----------------> Original Tensor Network
        all_index ---------> Array that contains all the indices of the TN
        n -----------------> Number of indices to slice
        slicing_method ----> Method to use to calculate the indices. Can be 'max' or 'cot'
        n_qubits ----------> Number of qubits of the TN
        tensors_to_slice --> Array with the positions of the tensors to slice
        Returning:
        tns ---------------> Array of the TNs resulting of applying slicing
    """
    def make_values(n_values, iteration):
        dev_values = [0] * n_values
        for i in range(n_values - 1, -1, -1):
            if iteration >= (2 ** i):
                iteration -= 2 ** i
                dev_values[i] = 1
        return dev_values

    from copy import deepcopy
    indices_to_slice = get_sliced_indices(tn, n, slicing_method, n_qubits=n_qubits)
    # print(indices_to_slice)
    # tns = [deepcopy(tn)]
    tns = []
    all_tensors = set()
    """
    for idx in indices_to_slice:
        new_tns = []
        for tn in tns:
            new_tn = deepcopy(tn)
            replace_tensor(0, idx, tn, all_index, all_tensors=all_tensors)
            new_tns.append(tn)
            replace_tensor(1, idx, new_tn, all_index)
            new_tns.append(new_tn)
        tns = new_tns
    """
    n_indices = len(indices_to_slice)
    for i in range(2**n_indices):
        tns.append(SlicedTensorNetwork(tn, indices_to_slice, make_values(n_indices, i)))
    # Updated and filled, if needed, the 'tensors_to_slice' variable
    if tensors_to_slice is not None:
        all_tensors_list = list(all_tensors)
        all_tensors_list.sort()
        for it in all_tensors_list:
            tensors_to_slice.append(it)
    return tns


def get_total_memory_used_kb():
    """
        romOlivo: Returns the RAM used in Kbs.
    """
    import psutil
    mem = psutil.virtual_memory()
    return mem.used / 1024


def contract_with_PyTDD(path, tns, indices):
    """
        romOlivo: Makes all the contractions using PyTDD
        Input variables:
        path -----> Contraction path to use
        tns ------> List of all Tensor Networks to contract (1 if no slicing had been applied)
        indices --> List of all indices of the Tensor Networks
        Returning:
        tdd ------> TDD that contains the result of contracting the tensor network
    """
    from source.TDD import Ini_TDD, add
    from time import time

    global handler
    memory_no_init = get_total_memory_used_kb()

    # Initialize PyTDD
    Ini_TDD(indices)

    # Start timer
    ttn = tns[0].generate_tn()
    t_total = 0
    first_memory = get_total_memory_used_kb()
    t_ini = time()

    # Make the contractions
    tdd = ttn.cont_TN(path, False)

    # Calculate time spent and add to total
    t_fin = time()
    t_partial = t_fin-t_ini
    other_data = {
        "memory_no_init": memory_no_init,
        "memory_after": get_total_memory_used_kb(),
        "memory_before": first_memory,
    }
    if len(tns) > 1:
        handler.print_time_result(t_partial, 0, other_data=other_data)
    t_total += t_partial

    for i in range(1, len(tns)):
        ttn = tns[i].generate_tn()
        # Start timer
        memory_after = get_total_memory_used_kb()
        t_ini = time()
        # Make the contractions
        temp_tdd = ttn.cont_TN(path, False)
        t_fin = time()
        tdd = add(tdd, temp_tdd)
        # Calculate time spent and add to total
        t_partial = t_fin - t_ini
        other_data = {
            "memory_no_init": memory_no_init,
            "memory_after": get_total_memory_used_kb(),
            "memory_before": memory_after,
        }
        handler.print_time_result(t_partial, i, other_data=other_data)
        t_total += t_partial
    other_data = {
        "memory_no_init": memory_no_init,
        "memory_after": get_total_memory_used_kb(),
        "memory_before": first_memory,
    }
    handler.print_time_result(t_total, other_data=other_data)
    """
        This is important because this variable not always is filled correctly. I do not know why but i can fill it
        correctly, so i set it myself. If you remove it, some simulations will not work properly, in the sense that
        you cannot execute the function 'to_array' of the resulting TDD.
    """
    for i in range(len(tdd.key_2_index.keys()) - 1):
        tdd.key_width[i] = 2

    return tdd


def contract_with_GTN(path, tns):
    """
        romOlivo: Makes all the contractions using GTN
        Input variables:
        path -----> Contraction path to use
        tns ------> List of all Tensor Networks to contract (1 if no slicing had been applied)
        Returning:
        tdd ------> Matrix that contains the result of contracting the tensor network
    """

    global handler
    memory_no_init = get_total_memory_used_kb()

    # Make the contractions
    first_memory = get_total_memory_used_kb()
    result, t_total = tns[0].generate_tn().cont_GTN(path, False)
    other_data = {
        "memory_no_init": memory_no_init,
        "memory_after": get_total_memory_used_kb(),
        "memory_before": first_memory,
    }
    if len(tns) > 1:
        handler.print_time_result(t_total, 0, other_data=other_data)
    result = result[0].tensor

    for i in range(1, len(tns)):
        memory_after = get_total_memory_used_kb()
        temp_result, t_contraction = tns[i].generate_tn().cont_GTN(path, False)
        temp_result = temp_result[0].tensor
        result = temp_result + result
        other_data = {
            "memory_no_init": memory_no_init,
            "memory_after": get_total_memory_used_kb(),
            "memory_before": memory_after,
        }
        handler.print_time_result(t_contraction, i, other_data=other_data)
        t_total += t_contraction
    other_data = {
        "memory_no_init": memory_no_init,
        "memory_after": get_total_memory_used_kb(),
        "memory_before": first_memory,
    }
    handler.print_time_result(t_total, other_data=other_data)

    return result


def PyTN_2_cTN(tn_lbl):
    import source.cpp.build.cTDD as cTDD

    # Create cTDD tensor network
    cTN = cTDD.TensorNetwork(tn_lbl.tn_type, tn_lbl.qubits_num)

    # @romOlivo: Added for less attribute search
    cTensor_cls = cTDD.Tensor
    add_tensor = cTN.add_tensor

    # Add tensors from PyTDD TN to cTDD TN
    for ts in tn_lbl.tensors:
        # Create C++ tensor
        data = ts.data.flatten()
        shape = list(ts.data.shape)
        index_key = [ind.key for ind in ts.index_set]
        index_idx = [ind.idx for ind in ts.index_set]
        # @romOlivo Changed for having less variables
        cTensor = cTensor_cls(data, shape, index_key, index_idx, ts.name, ts.qubits, ts.depth)
        # Add C++ Tensor to C++ TN
        add_tensor(cTensor, False)

    return cTN


def contract_with_FTDD(path, tns, indices, n, N=12, force_init=True):
    """
        romOlivo: Makes all the contractions using GTN
        Input variables:
        path -----> Contraction path to use
        tns ------> List of all Tensor Networks to contract (1 if no slicing had been applied)
        indices --> List of all indices of the Tensor Networks
        n --------> Number of qubits of the TN
        N --------> Determines the number of buckets to use (2^N)
        Returning:
        tdd ------> Matrix that contains the result of contracting the tensor network
    """

    import source.cpp.build.cTDD as cTDD
    from time import time

    memory_no_init = get_total_memory_used_kb()

    global ctdd_has_init
    if force_init or ctdd_has_init is None or not ctdd_has_init:
        import psutil
        import math

        # cTDD Table parameters
        load_factor = 1
        alpha = 2
        memory = psutil.virtual_memory().available
        N = int(math.log2(memory)) - 10
        print(f"memory = {memory} // N = {N}")

        N_max = min(alpha * n, N)

        N_max = N

        NBUCKET = 2 ** N_max
        INITIAL_GC_LIMIT = int(load_factor * NBUCKET)
        INITIAL_GC_LUR = 0.9
        # CCT_NBUCKET = ACT_NBUCKET = 2 ** (N_max - 1) - 1
        CCT_NBUCKET = ACT_NBUCKET = 2 ** 15 - 1
        uniqTabConfig = [INITIAL_GC_LIMIT, INITIAL_GC_LUR, NBUCKET, ACT_NBUCKET, CCT_NBUCKET]

        cTDD.Ini_TDD(indices, uniqTabConfig, False)

        # print("init")
        ctdd_has_init = True

    matrix = None

    for i in range(len(tns)):
        tns[i] = PyTN_2_cTN(tns[i].generate_tn())

    # Make the contractions
    t_total = 0
    first_memory = get_total_memory_used_kb()
    t_ini = time()
    tdd = tns[0].cont_TN(path, False)
    t_fin = time()
    # matrix = tdd.to_array()
    matrix = tdd
    t_partial = t_fin - t_ini
    if len(tns) > 1:
        other_data = {
            "memory_no_init": memory_no_init,
            "memory_after": get_total_memory_used_kb(),
            "memory_before": first_memory,
        }
        handler.print_time_result(t_partial, 0, other_data=other_data)
    t_total += t_partial

    """
    for i in range(1, len(tns)):
        memory_after = get_total_memory_used_kb()
        t_ini = time()
        tdd = tns[i].cont_TN(path, False)
        t_fin = time()
        partial_matrix = tdd.to_array()
        matrix = matrix + partial_matrix
        t_partial = t_fin - t_ini
        other_data = {
            "memory_no_init": memory_no_init,
            "memory_after": get_total_memory_used_kb(),
            "memory_before": memory_after,
        }
        handler.print_time_result(t_partial, i, other_data=other_data)
        t_total += t_partial
    """
    other_data = {
        "memory_no_init": memory_no_init,
        "memory_after": get_total_memory_used_kb(),
        "memory_before": first_memory,
    }
    handler.print_time_result(t_total, other_data=other_data)
    return matrix


def clear():
    import source.cpp.build.cTDD as cTDD
    print("Clearing....")
    global ctdd_has_init
    ctdd_has_init = False
    cTDD.Clear_TDD()


def simulate(cir, is_input_closed=True, is_output_closed=True, use_tetris=False, use_slicing=False,
             contraction_method='seq', n_indices=1, slicing_method="max", backend="PyTDD", handler_name="hybrid",
             index_order_method="path", force_init=True):
    """
        romOlivo: This method was added to simplify the simulation process. It will encapsulate all the process
        after the circuit is read as a QuantumCircuit until you get the result of all the contraction.
        Input variables:
        cir -----------------> Circuit in the form of 'QuantumCircuit' class of qiskit
        is_input_closed -----> True if you want to close the input
        is_output_closed ----> True if you want to close the output
        use_tetris ----------> True if you want to apply Tetris
        use_slicing ---------> True if you want to apply slicing. NOT IMPLEMENTED YET
        contraction_method --> Name of the contraction method. Can be 'seq', 'cot', 'k-ops', 'pair' or 'spair'
        n_indices -----------> Number of indices to slice
        slicing_method ------> Slicing method tu use. Can be 'max' or 'cot'
        handler_name --------> Output handler to use. Can be 'hybrid', 'print' or 'file'
        index_order_method --> Name of the global index order using. Can be 'default', 'rcm' or 'path'.
        Returning:
        tdd ----------------> TDD that contains the result of contracting the tensor network
    """

    # Init the handler
    global handler
    if handler_name == "print":
        handler = PrintOutputHandler(backend, circuit=cir, cont_method=contraction_method, index_order=index_order_method)
    elif handler_name == "file":
        handler = FileOutputHandler(backend, circuit=cir, cont_method=contraction_method, index_order=index_order_method)
    elif handler_name == "hybrid":
        handler = HybridOutputHandler(backend, circuit=cir, cont_method=contraction_method, index_order=index_order_method)
    elif handler_name == "none":
        handler = OutputHandler(backend, circuit=cir, cont_method=contraction_method, index_order=index_order_method)

    # Read and prepare the circuit
    tn, all_indices_lbl, depth = cir_2_tn_lbl(cir)
    n = get_real_qubit_num(cir)

    # Inputs and outputs are here to make the simple contractions using tetris
    state = [0] * n
    if is_input_closed:
        add_inputs(tn, state, n)
    if is_output_closed:
        add_outputs(tn, state, n)

    # Print init handler
    handler.print_init(
        n_indices if use_slicing else 0,                                              # Number of slices
        ["memory_no_init", "memory_after", "memory_before"]                  # Additional info we want to show
    )

    # Preprocess with Tetris
    if use_tetris:
        tn = apply_full_tetris(tn, depth)

    # Applying slicing
    tensors_to_slice = []
    tns = [SlicedTensorNetwork(tn, [], [])]
    if use_slicing:
        tns = slicing(tn, all_indices_lbl, n=n_indices, n_qubits=n, slicing_method=slicing_method,
                      tensors_to_slice=tensors_to_slice)

    # Calculate the path
    path = calculate_path(tns[0], contraction_method, tensors_to_slice=tensors_to_slice)

    # Calculate the index order
    index_order = calculate_order(index_order_method, tns[0].generate_tn().tensors, path, default=all_indices_lbl)

    tdd = None
    if backend == "PyTDD":
        tdd = contract_with_PyTDD(path, tns, index_order)
    elif backend == "GTN":
        tdd = contract_with_GTN(path, tns)
    elif backend == "FTDD":
        tdd = contract_with_FTDD(path, tns, index_order, n, force_init=force_init)
    handler.end_printing()
    return tdd


class SlicedTensorNetwork:
    def __init__(self, tn, indices, values):
        self.tn = tn
        self.new_tn = None
        self.indices = indices
        self.values = values
        self.all_tensors = set()
        self.tensors_to_slice = None

    def generate_tn(self):
        from copy import deepcopy
        if self.new_tn is None:
            self.new_tn = deepcopy(self.tn)
            for i in range(len(self.indices)):
                idx = self.indices[i]
                value = self.values[i]
                replace_tensor(value, idx, self.new_tn, all_tensors=self.all_tensors)
        return self.new_tn

    def get_tensors_to_slice(self):
        if self.tensors_to_slice is None:
            self.tensors_to_slice = []
            all_tensors_list = list(self.all_tensors)
            all_tensors_list.sort()
            for it in all_tensors_list:
                self.tensors_to_slice.append(it)
        return self.tensors_to_slice

# Extract the statevector result given the qiskit.Statevector order
def get_statevector(tdd, n_qubits):
    statevector = []

    # For all the computational basis
    for i in range(2 ** n_qubits):
        # Extracting the desired order (q_0, q_1, ..., q_n-1)
        bit_values = [(i >> k) & 1 for k in range(n_qubits)]

        # Get the correct amplitude
        amplitude = tdd.get_amplitude(bit_values)
        statevector.append(amplitude)

    return np.asarray(statevector, dtype=np.complex128).flatten()


ctdd_has_init = False
handler = OutputHandler(None, circuit=None, cont_method=None, index_order=None)

