/*
 * File: cTDD.cpp
 * Author: Qirui Zhang (qiruizh@umich.edu)
 * Description: C++ backend for FTDD (https://github.com/QiruiZhang/FTDD)
 *
 * Copyright (c) 2024 Qirui Zhang
 * All rights reserved.
 *
 * Modified by Vicente Lopez (voliva@uji.es). Modifications will be marked with @romOlivo.
 *   - Showing the new metrics.
 *   - New binding to be able to use tdd addition
 *   - Fixed the GIL problem
 *   - Fixed memory leak in to_array
 *   - Type generalization in get_int_key for allowing smaller epi
 *   - Changed succs from vector to array for static size
 *   - Able to use to_array with TDDs of only one value (scalar)
 *   - Optimized to_array and tdd_2_np
 */

#include "cTDD.hpp"
#include "cTddUniqueTable.hpp"
#include "cTddComputedCache.hpp"

/*
    Bindings
*/
PYBIND11_MODULE(cTDD, m) {
    // Doc for the module
    m.doc() = "The PyBind11 module for wrapping TDD implemented in C++.";

    /*
        Class bindings
    */
    // Binding Index in C++
    py::class_<Index>(m, "Index")
    .def(py::init<std::string, int>())
    .def("__eq__", &Index::operator==, py::call_guard<py::gil_scoped_release>())
    .def("__lt__", &Index::operator<, py::call_guard<py::gil_scoped_release>())
    .def("str", &Index::str, py::call_guard<py::gil_scoped_release>())
    ;

    // @romOlivo Binding Edge in C++ for being able to test TDD Addition
    py::class_<Node>(m, "Node")
        .def(py::init<>())
        .def_readwrite("key", &Node::key)
        .def_readwrite("edges", &Node::edges)
    ;

    // @romOlivo Binding Edge in C++ for being able to use TDD Addition
    py::class_<Edge>(m, "Edge")
        .def(py::init<>())
        .def(py::init<Node*>())
        .def_readwrite("weight", &Edge::weight)
        .def_readwrite("node", &Edge::node, py::return_value_policy::reference)
        .def("__eq__", &Edge::operator==, py::call_guard<py::gil_scoped_release>())
    ;

    // Binding TDD in C++
    py::class_<TDD>(m, "TDD")
    .def(py::init<>())
    .def(py::init<Edge>())                          // @romOlivo for instantiating TDD(edge)
    .def_readwrite("root", &TDD::root)              // @romOlivo to ve able to read/write tdd.root
    .def("__eq__", &TDD::operator==, py::call_guard<py::gil_scoped_release>())
    .def("str", &TDD::str, py::call_guard<py::gil_scoped_release>())
    .def("node_number", &TDD::node_number, py::call_guard<py::gil_scoped_release>())
    .def("to_array", &TDD::to_array, py::call_guard<py::gil_scoped_release>())
    .def("get_amplitude", &TDD::get_amplitude, py::call_guard<py::gil_scoped_release>())
    .def("get_measure_prob", &TDD::get_measure_prob, py::call_guard<py::gil_scoped_release>())
    .def("measure", &TDD::measure, py::call_guard<py::gil_scoped_release>())
    ;

    // Binding Tensor in C++
    py::class_<Tensor>(m, "Tensor")
    .def(py::init<py::object, py::list, py::list, py::list, std::string, py::list, int>())
    .def("str", &Tensor::str, py::call_guard<py::gil_scoped_release>())
    .def("get_data", &Tensor::get_data, py::call_guard<py::gil_scoped_release>())
    .def("tdd", &Tensor::tdd, py::call_guard<py::gil_scoped_release>())
    ;

    // Binding TensorNetwork in C++
    py::class_<TensorNetwork>(m, "TensorNetwork")
    .def(py::init<std::string, int>())
    .def("add_tensor", &TensorNetwork::add_tensor, py::call_guard<py::gil_scoped_release>())
    .def("cont_TN", &TensorNetwork::cont_TN, py::call_guard<py::gil_scoped_release>())
    .def("str", &TensorNetwork::str, py::call_guard<py::gil_scoped_release>())
    ;

    /*
        Function bindings
    */
    // Binding get_count()
    m.def("get_count", &get_count, "The function that reports TDD statistics.");

    // Binding get_unique_table_num()
    m.def("get_unique_table_num", &get_unique_table_num, "The function that returns number of unique nodes.");

    // Binding get_gc_runs()
    m.def("get_gc_runs", &get_gc_runs, "The function that returns number of gc runs.");

    // Binding get computed table sizes
    m.def("get_add_computed_table_num", &get_add_computed_table_num, "The function that returns size of add computed table.");
    m.def("get_cont_computed_table_num", &get_cont_computed_table_num, "The function that returns size of cont computed table.");

    // Binding Ini_TDD() in C++
    m.def("Ini_TDD", &Ini_TDD, "The function that initializes all global variables.");

    // Binding Clear_TDD() in C++
    m.def("Clear_TDD", &Clear_TDD, "The function that clears all global variables.");

    // @romOlivo Binding TDD Addition
    m.def("add", &add, "Function that performs TDD addition.", py::call_guard<py::gil_scoped_release>());

}


/*
    Edge
*/
bool Edge::operator==(const Edge& other) const {
    return ((node == other.node) && (get_int_key(weight) == get_int_key(other.weight)));
}

// cTDD.cpp

// @romOlivo: Changed to fix de GIL problem and to allow different index ordering
std::complex<dataType> TDD::get_amplitude(std::vector<int> index_values) {
    if (index_values.size() != index_set.size()) {
        throw std::invalid_argument("The number of values does not match the number of indices in index_set.");
    }

    // Find the maximum 'key' registered in this TDD
    keyType max_key = -1;
    for (const auto& pair : key_2_index) {
        if (pair.first > max_key) {
            max_key = pair.first;
        }
    }

    // Create a vector where each index position corresponds to 'node->key'
    std::vector<int> key_values(max_key + 1, 0);

    // Map each input value to its corresponding 'key' by associating it with the qubit index
    for (size_t i = 0; i < index_set.size(); ++i) {
        const std::string& idx_name = index_set[i].key;
        if (index_2_key.find(idx_name) != index_2_key.end()) {
            keyType key = index_2_key.at(idx_name);
            if (key >= 0 && key <= max_key) {
                // Extract the actual qubit index from the variable name (e.g., "x0" -> 0, "x1_0" -> 1)
                size_t q_idx = i;
                int parsed_num = 0;
                bool has_num = false;
                for (char c : idx_name) {
                    if (std::isdigit(c)) {
                        parsed_num = parsed_num * 10 + (c - '0');
                        has_num = true;
                    } else if (has_num) {
                        break;
                    }
                }
                if (has_num && static_cast<size_t>(parsed_num) < index_values.size()) {
                    q_idx = parsed_num;
                }

                key_values[key] = index_values[q_idx];
            }
        }
    }

    // Execute recursive traversal passing the key-mapped values
    return root.get_amplitude_recur(key_values);
}

// @romOlivo: Changed to allow different index ordering
std::complex<dataType> Edge::get_amplitude_recur(std::vector<int>& key_values) {
    // Base case: terminal or null node reached
    if (node == node_n1 || node == nullptr) {
        return weight;
    }

    // Get the bit corresponding to the current node's key
    int bit_value = key_values[node->key];

    // Slice the current node's key with its corresponding bit value
    Edge temp_edge = Slicing(*this, node->key, bit_value);

    // Recurse and multiply by current edge weight
    return weight * temp_edge.get_amplitude_recur(key_values);
}

void Edge::get_measure_prob_recur() {
    if (!node->meas_prob.empty()) {
        return;
    }
    if (node->key == -1) {
        node->meas_prob={0.5, 0.5};
        return;
    }

    Slicing(*this, node->key, 0).get_measure_prob_recur();
    Slicing(*this, node->key, 1).get_measure_prob_recur();

    node->meas_prob.push_back(pow(std::abs(node->edges[0].weight), 2) * (node->edges[0].node->meas_prob[0] + node->edges[0].node->meas_prob[1]) * pow(2, (node->key - node->edges[0].node->key)));
    node->meas_prob.push_back(pow(std::abs(node->edges[1].weight), 2) * (node->edges[1].node->meas_prob[0] + node->edges[1].node->meas_prob[1]) * pow(2, (node->key - node->edges[1].node->key)));
    return;
}

std::string Edge::measure_recur(int split_pos) {
    std::string res, temp_res;
    if (split_pos == -1) {
        res = "";
        return res;
    } else {
        if (split_pos != node->key) {
            int rand_bit = dist1(gen1);
            temp_res = measure_recur(split_pos - 1);
            res = std::to_string(rand_bit) + temp_res;
            return res;
        }

        // Define a distribution to produce integers in the range [0, sum(meas_prob))
        std::uniform_real_distribution<dataType> dist2(0, (node->meas_prob[0] + node->meas_prob[1]));
        dataType rand_float = dist2(gen2);
        if (rand_float < node->meas_prob[0]) {
            Edge temp_edge = Slicing(*this, node->key, 0);
            temp_res = temp_edge.measure_recur(split_pos - 1);
            res = '0' + temp_res;
        } else {
            Edge temp_edge = Slicing(*this, node->key, 1);
            temp_res = temp_edge.measure_recur(split_pos - 1);
            res = '1' + temp_res;
        }
    }
    return res;
}


/*
    TDD
*/
bool TDD::operator==(const TDD& other) const {
    return (root == other.root);
}

int TDD::node_number() {
    std::set<Node*> node_set;
    get_node_set(root.node, node_set);
    return node_set.size();
}

// @romOivo: Modified to be able to do amplitude-simulations and optimized
complexArrayType TDD::to_array() {
    keyType split_pos = 0;
    std::map<keyType,int> key_repeat_num;
    std::map<std::string,int> var_idx;

    // @romOivo: Return single value if TDD is a single value
    if (index_set.empty()) {
        complexArrayType vec;
        vec.resize(1);
        vec[0] = root.weight;
        return vec;
    }

    // Count the appearance of indices and log in var_idx
    for (const auto& idx : index_set) {
        if (var_idx.find(idx.key) == var_idx.end()) {
            var_idx[idx.key] = 1;
        } else {
            var_idx[idx.key]++;
        }
    }

    // split_pos is sort of the number of different indices
    // @romOlivo: Optimized
    split_pos = key_2_index.rbegin()->first;

    // Count the appearance of different keys and log in key_repeat_num
    for (keyType k = 0; k <= split_pos; k++) {
        if (key_2_index.find(k) != key_2_index.end()) {
            if (var_idx.find(key_2_index[k]) != var_idx.end()) {
                key_repeat_num[k] = var_idx[key_2_index[k]];
            }
        } else {
            key_repeat_num[k] = 1;
        }
    }

    // Initialize the data array
    complexArrayType vec; uint ndim = index_set.size(); std::vector<uint> shape(ndim, 2);
    // @romOlivo: Changed for fixing a memory leak problem
    TensorArray U_obj(vec, shape, ndim);
    U_obj.vec.resize(std::pow(2, ndim)); U_obj.vec.setZero();
    tdd_2_np(&U_obj, root, split_pos, std::vector<uint>(ndim, 0), 0, key_repeat_num);
    return U_obj.vec;
}

void TDD::get_measure_prob() {
    root.get_measure_prob_recur();
}

std::string TDD::measure() {
    auto maxElement = std::max_element(
        key_2_index.begin(), key_2_index.end(),
        [](const auto& a, const auto& b) {
            return a.first < b.first;
        }
    );
    return root.measure_recur(maxElement->first);
}


/*
    Tensor
*/
TDD Tensor::tdd() {
    return get_tdd(data, index_set);
}


/*
    TensorNetwork
*/
// @romOlivo Change the signature for solving the GIL problem
TDD TensorNetwork::cont_TN(const std::vector<std::pair<int, int>>& path, bool debug) {
    std::vector<TDD> tdd_list(tensors.size());

    // Convert all tensors to TDDs beforehand
    for (uint i = 0; i < tensors.size(); i++) {
        tdd_list[i] = tensors[i].tdd();
        unique_table.incr_ref_count(tdd_list[i].root.node);
    }

    // Contraction
    for (uint i = 0; i < path.size(); i++) {
        std::pair<int, int> pair = path[i];  // @romOlivo Changed for matching the new signature
        // Acquire the tensors/TDDs pointed to by the pair
        TDD tdd_a = tdd_list[pair.first];
        TDD tdd_b = tdd_list[pair.second];

        // Perform contraction
        TDD tdd_c = cont(tdd_a, tdd_b);

        // Update reference count
        unique_table.decr_ref_count(tdd_a.root.node);
        unique_table.decr_ref_count(tdd_b.root.node);
        unique_table.incr_ref_count(tdd_c.root.node);

        // Update tensor list
        tdd_list.erase(tdd_list.begin() + std::max(pair.first, pair.second));
        tdd_list.erase(tdd_list.begin() + std::min(pair.first, pair.second));
        tdd_list.push_back(tdd_c);

        if (debug) {
            std::cout << "Contracted the " << i+1 << "-th pair (" << std::to_string(pair.first) << ", " << std::to_string(pair.second) << ")" << std::endl;
            std::cout << "Active node count: " << unique_table.getActiveNodeCount() << ", Unique table size: " << unique_table.getNodeCount() << std::endl;
        }

        // Garbage collection, not for the last operation
        if (i < path.size() - 1) {
            uint num_collected = unique_table.garbageCollection();
            if (debug) { std::cout << "Number of remained nodes: " << unique_table.getNodeCount() << ", Number of collected nodes: " << num_collected << ", garbage collection threshold: " << unique_table.getGcLimit() << std::endl << std::endl; }
        }

    }



    if (tdd_list.size() != 1) { throw std::runtime_error("In TensorNetwork.cont_TN: TDD list size is not one after all contractions!\n"); }
    return tdd_list[0];
}


/*
    Utility Functions: not core TDD functions
*/

// Get the number of unique nodes
int get_unique_table_num() {
    return unique_table.getNodeCount() + 1;
}

// Get the size of computed tables
int get_add_computed_table_num() {
    return add_computed_table.getCount();
}
int get_cont_computed_table_num() {
    return cont_computed_table.getCount();
}
int get_gc_runs(){
    return unique_table.getGcruns();
}

// Report TDD statistics
std::string get_count() {
    std::ostringstream ss;
    ss << "node: " << unique_table.getHit() << " / " << unique_table.getLookups() << " / " << unique_table.hitRatio() << "\n";
    // romOlivo: Modified so it can show the number of collisions
    ss << "add: " << add_computed_table.getHit() << " / " << add_computed_table.getLookups() << " / " << add_computed_table.hitRatio() << " / " << add_computed_table.getCollisions() << "\n";
    // romOlivo: Modified so it can show the number of collisions
    ss << "cont: " << cont_computed_table.getHit() << " / " << cont_computed_table.getLookups() << " / " << cont_computed_table.hitRatio() << " / " << cont_computed_table.getCollisions() << "\n";
    ss << "Final number of nodes: " << get_unique_table_num() - 1 << ", Number of garbage collection runs: " << unique_table.getGcruns() << "\n";
    // @romOlivo: Prints more info about the performance of the Unique Table
    ss << unique_table.get_performance_metrics();
    return ss.str();
}

// Scale a weight up to reduce numerical instability
// @romOlivo Changed the type for allowing smaller epis
std::tuple<epiKeyValue, epiKeyValue> get_int_key(const std::complex<dataType>& weight) {
    epiKeyValue real_part = round(weight.real() * epi_inv);
    epiKeyValue imag_part = round(weight.imag() * epi_inv);
    return std::make_tuple(real_part, imag_part);
}

// Set global_index_order with all_indexs
void set_index_order(py::list var_order, bool debug=false) {
    global_index_order.clear();
    for (uint k = 0; k < var_order.size(); k++) {
        std::string ind = var_order[k].cast<std::string>();
        global_index_order[ind] = k;
        if (debug) {
            std::cout << "k is " << k << ", adding index " << ind << std::endl;
        }
    }
    global_index_order["-1"] = INT_MAX;
}

// Get the set of nodes for a TDD
void get_node_set(Node* node, std::set<Node*>& node_set) {
    if (!node_set.count(node)) {
        node_set.insert(node);
        if (node->key != -1) { for (uint k = 0; k < succ_num; ++k) { if (node->edges[k].node) { get_node_set(node->edges[k].node, node_set); } } }
    }
}

// Create TDD's index_2_key and key_2_index based on index_set of a tensor
std::pair<std::map<std::string, keyType>, std::map<keyType, std::string>> get_index_2_key(const std::vector<Index>& var){
    std::vector<Index> var_sort(var);
    std::sort(var_sort.begin(), var_sort.end(), std::less<Index>());
    std::reverse(var_sort.begin(), var_sort.end());

    std::map<std::string, keyType> idx_2_key{{"-1", -1}};
    std::map<keyType, std::string> key_2_idx{{-1, "-1"}};
    keyType n = 0;
    for (const auto& idx : var_sort) {
        if (idx_2_key.find(idx.key) == idx_2_key.end()) {
            idx_2_key[idx.key] = n;
            key_2_idx[n] = idx.key;
            n++;
        }
    }

    return std::make_pair(idx_2_key, key_2_idx);
}


/*
    Core TDD functions
*/

// Initialize global variables
TDD Ini_TDD(py::list index_order, py::list TabConfig, bool debug) {
    // Initialize the unique table
    unique_table = UniqueTable<Node>(
        TabConfig[0].cast<std::size_t>(),   // INITIAL_GC_LIMIT
        TabConfig[1].cast<dataType>(),      // INITIAL_GC_LUR
        TabConfig[2].cast<std::size_t>()    // NBUCKET
    );
    unique_table.resize();
    unique_table.clear();

    // Initialize the add computed table
    add_computed_table = AddComputedCache(
        TabConfig[3].cast<std::size_t>()    // NBUCKET
    );
    add_computed_table.clear();

    // Initialize the cont computed table
    cont_computed_table = ContComputedCache(
        TabConfig[4].cast<std::size_t>()    // NBUCKET
    );
    cont_computed_table.clear();

    // Set global index order
    set_index_order(index_order, debug);

    return get_identity_tdd();
}

// Clear global variables
void Clear_TDD() {
    unique_table.clear();
    add_computed_table.clear();
    cont_computed_table.clear();
}


// Get identity TDD
TDD get_identity_tdd() {
    TDD tdd = TDD(Edge(node_n1));
    tdd.index_2_key = {{"-1", -1}};
    tdd.key_2_index = {{-1, "-1"}};
    return tdd;
}

// Normalization // @romOlivo Changed for static array size
Edge normalize(const keyType& x, const std::array<Edge, succ_num>& the_successors) {
    // Check if the two successors are the same, if so, return directly the successor
    if (the_successors[0] == the_successors[1]) { return the_successors[0]; }

    // Copy the successors
    std::array<Edge, succ_num> edges = the_successors; // @romOlivo Changed for static array size

    // Calculate absolute weights and find the max of two weights. Here we are taking the left weight if they equal, same as Python
    dataType weigs_abs0 = std::round(std::abs(edges[0].weight) * epi_inv);
    dataType weigs_abs1 = std::round(std::abs(edges[1].weight) * epi_inv);
    std::complex<dataType> weig_max;
    if (weigs_abs0 >= weigs_abs1) { weig_max = edges[0].weight; } else { weig_max = edges[1].weight; }

    // Normalize the node
    for (uint k = 0; k < succ_num; k++) {
        edges[k].weight /= weig_max;
        // Check if any of the successor has zero weight
        if (get_int_key(edges[k].weight) == std::tuple<epiKeyValue, epiKeyValue>(0, 0)) { // romOlivo Change to general
            edges[k].node = node_n1;
            edges[k].weight = 0;
        }
    }

    // Find or insert the new node to unique table
    Edge res = Edge(unique_table.Find_Or_Add_Unique_table(x, edges));
    res.weight = weig_max;
    return res;
}


// The get_tdd() function
TDD get_tdd(TensorArray& U, const std::vector<Index>& var) {
    auto pair = get_index_2_key(var);
    std::map<std::string, keyType> idx_2_key = pair.first;
    std::map<keyType, std::string> key_2_idx = pair.second;

    std::vector<keyType> order(var.size());
    for (uint k = 0; k < var.size(); k++) { order[k] = idx_2_key[var[k].key]; }

    TensorArray* U_ptr = &U;
    Edge root = np_2_tdd(U_ptr, std::vector<uint>(order.size(), 0), std::vector<bool>(order.size(), false), order);

    TDD tdd(root);
    tdd.index_2_key = idx_2_key;
    tdd.key_2_index = key_2_idx;
    tdd.index_set = var;

    return tdd;
}

// Array to TDD conversion
Edge np_2_tdd(TensorArray* U, const std::vector<uint>& slice, const std::vector<bool>& sliced, const std::vector<keyType>& order) {
    // Recursion terminal
    bool allSliced = std::all_of(sliced.begin(), sliced.end(), [](bool x){ return x; });
    if (allSliced){
        Edge res = Edge(node_n1);
        res.weight = U->at(slice);
        return res;
    }

    // Create a copy of order
    std::vector<keyType> order_copy = order;

    // Split tensor array based on current index
      // find the max of order and its position
    auto max_iter = std::max_element(order_copy.begin(), order_copy.end());
    keyType x = *max_iter;
    int split_pos = std::distance(order_copy.begin(), max_iter);
    order_copy[split_pos] = -1;
      // Split the position, essentially slicing the array index
    std::vector<bool> sliced_split = sliced;
    std::vector<std::vector<uint>> slice_split(succ_num, slice);
    sliced_split[split_pos] = true;
    for (uint i = 0; i < succ_num; i++) { slice_split[i][split_pos] = i; }
      // Keep splitting hyper-edges
    while (std::find(order_copy.begin(), order_copy.end(), x) != order_copy.end()) {
        int split_pos = std::find(order_copy.begin(), order_copy.end(), x) - order_copy.begin();
        sliced_split[split_pos] = true;
        for (uint k = 0; k < succ_num; k++) {
            slice_split[k][split_pos] = k;
        }
        order_copy[split_pos] = -1;
    }

    // Recursion
    std::array<Edge, succ_num> the_successors; // @romOlivo Changed for static array size
    for (uint k = 0; k < slice_split.size(); k++) {
        Edge res = np_2_tdd(U, slice_split[k], sliced_split, order_copy);
        the_successors[k] = res;
    }

    // Normalization
    return normalize(x, the_successors);
}


// TDD to Array conversion
// @romOlivo Optimized
void tdd_2_np(TensorArray* U, const Edge& edge, const keyType& split_pos, const std::vector<uint>& slice, const uint& slice_ptr, std::map<keyType, int>& key_repeat_num) {
    // romOlivo: Base case if weight is zero
    if (edge.weight == 0.0) return;

    if (split_pos == -1){ // Recursion terminal
        U->update(slice, edge.weight);
    } else {
        // Get the time that current key is repeated in index_set (for hyper-edges)
        uint repeat_num;
        if (key_repeat_num.find(split_pos) == key_repeat_num.end()) { repeat_num = 1; } else { repeat_num = key_repeat_num[split_pos]; }

        // Update the start pointer of slice slots to be split
        uint slice_ptr_new = slice_ptr + repeat_num;

        // Split TDD and slice array index based on current key and recursion
        // romOlivo: Reworked to have only one reusable vector
        std::vector<uint> next_slice = slice;
        for (uint i = 0; i < succ_num; i++) {
            for (uint r = slice_ptr; r < slice_ptr_new; r++) {
                next_slice[r] = i;
            }

            Edge succ_edge = Slicing2(edge, split_pos, i);
            tdd_2_np(U, succ_edge, split_pos - 1, next_slice, slice_ptr_new, key_repeat_num);
        }
    }
}


// Slicing: Simply return the slice as a sub-graph, not changing any weight
Edge Slicing(const Edge& edge, const keyType& x, const int& c) {
    keyType k = edge.node->key;
    if ((k == -1) || (k < x)) {
        return edge;
    } else { // k == x, which is always the case in current TDD setting
        Edge res = edge.node->edges[c];
        return res;
    }
}

// Slicing2: Return the sub-graph with weight inherited from father. This way the sub-graph still has accurate amplitude for each leaf
Edge Slicing2(const Edge& edge, const keyType& x, const int& c) {
    keyType k = edge.node->key;
    if ((k == -1) || (k < x)) {
        return edge;
    } else { // k == x, which is always the case in current TDD setting
        Edge res = edge.node->edges[c]; res.weight *= edge.weight;
        return res;
    }
}


// TDD Addition
Edge add(const Edge& edge1, const Edge& edge2) {
    Edge res;
    keyType k1 = edge1.node->key;
    keyType k2 = edge2.node->key;

    // Terminal cases
    if (edge1.weight == std::complex<dataType>(0.0, 0.0)) { // Left operand is zero
        return edge2;
    }
    if (edge2.weight == std::complex<dataType>(0.0, 0.0)) { // right operand is zero
        return edge1;
    }
    if (edge1.node == edge2.node) { // two operands are the same
        std::complex<dataType> weig = edge1.weight + edge2.weight;
        // romOlivo Change to general
        if (get_int_key(weig) == std::tuple<epiKeyValue, epiKeyValue>(0, 0)) { // result is 0
            res = Edge(node_n1);
            res.weight = 0;
            return res;
        } else {
            res = Edge(edge1.node);
            res.weight = weig;
            return res;
        }
    }

    // Query addition computed table
    Edge find_add = add_computed_table.find(edge1, edge2);
    if (find_add.node != nullptr) { return find_add; }

    // Recursive addition // @romOlivo Changed for static array size
    std::array<Edge, succ_num> the_successors; keyType x;
    if (k1 > k2) {
        x = k1;
        for (uint k = 0; k < succ_num; k++) {
            the_successors[k] = add(Slicing2(edge1, x, k), edge2);
        }
    } else if (k1 == k2) {
        x = k1;
        for (uint k = 0; k < succ_num; k++) {
            the_successors[k] = add(Slicing2(edge1, x, k), Slicing2(edge2, x, k));
        }
    } else {
        x = k2;
        for (uint k = 0; k < succ_num; k++) {
            the_successors[k] = add(edge1, Slicing2(edge2, x, k));
        }
    }

    // Normalization and insertion to addition computed table
    res = normalize(x, the_successors);
    add_computed_table.insert(edge1, edge2, res);

    return res;
}


// TDD contraction
TDD cont(TDD& tdd1, TDD& tdd2) {
    // Index set pre-processing
    std::vector<Index> var_cont, var_out1, var_out2;
    for (auto var : tdd1.index_set) { if (std::find(tdd2.index_set.begin(), tdd2.index_set.end(), var) != tdd2.index_set.end()) {var_cont.push_back(var);} } // tdd1 && tdd2
    for (auto var : tdd1.index_set) { if (std::find(var_cont.begin(), var_cont.end(), var) == var_cont.end()) {var_out1.push_back(var);} } // tdd1 / (tdd1 && tdd2)
    for (auto var : tdd2.index_set) { if (std::find(var_cont.begin(), var_cont.end(), var) == var_cont.end()) {var_out2.push_back(var);} } // tdd2 / (tdd1 && tdd2)

      // Construct var_out and var_out_idx
    std::vector<Index> var_out(var_out1);
    var_out.insert(var_out.end(), var_out2.begin(), var_out2.end());
    std::sort(var_out.begin(), var_out.end(), [](const Index& a, const Index& b) { return a < b; });
    std::vector<std::string> var_out_idx(var_out.size());
    for (uint k = 0; k < var_out.size(); k++) { var_out_idx[k] = var_out[k].key; }

      // Construct var_cont_idx
    std::vector<std::string> var_cont_idx_(var_cont.size()), var_cont_idx;
    for (uint k = 0; k < var_cont.size(); k++) { var_cont_idx_[k] = var_cont[k].key; }
    for (auto var : var_cont_idx_) { if (std::find(var_out_idx.begin(), var_out_idx.end(), var) == var_out_idx.end()) {var_cont_idx.push_back(var);} } // var_cont_idx_ / var_out_idx

    // Generate idx_2_key and key_2_idx for the new resulted TDD
    std::map<std::string, keyType> idx_2_key {{"-1",-1}}; std::map<keyType, std::string> key_2_idx {{-1,"-1"}};
    keyType n = 0;
    for (int k = var_out_idx.size() - 1; k >= 0; k--) {
        if (idx_2_key.find(var_out_idx[k]) == idx_2_key.end()) {
            idx_2_key[var_out_idx[k]] = n;
            key_2_idx[n] = var_out_idx[k];
            n++;
        }
    }

    // Generate key_2_new_key and cont_order
    std::vector<keyType> key_2_new_key_0(tdd1.key_2_index.size() - 1), key_2_new_key_1(tdd2.key_2_index.size() - 1);
    std::vector<int> cont_order_0(tdd1.key_2_index.size()), cont_order_1(tdd2.key_2_index.size());

    cont_order_0[0] = INT_MAX;
    for (uint k = 0; k < tdd1.key_2_index.size() - 1; k++) {
        std::string v = tdd1.key_2_index[k];
        if (idx_2_key.find(v) != idx_2_key.end()) { key_2_new_key_0[k] = idx_2_key[v]; } else { key_2_new_key_0[k] = -2; }
        cont_order_0[k+1] = global_index_order[v];
    }

    cont_order_1[0] = INT_MAX;
    for (uint k = 0; k < tdd2.key_2_index.size() - 1; k++) {
        std::string v = tdd2.key_2_index[k];
        if (idx_2_key.find(v) != idx_2_key.end()) { key_2_new_key_1[k] = idx_2_key[v]; } else { key_2_new_key_1[k] = -2; }
        cont_order_1[k+1] = global_index_order[v];
    }

    // Perform contraction
    std::set<std::string> var_cont_idx_set{var_cont_idx.begin(), var_cont_idx.end()};
    Edge root = contract(tdd1.root, tdd2.root, key_2_new_key_0, key_2_new_key_1, cont_order_0, cont_order_1, var_cont_idx_set.size());

    // TDD attributes
    TDD tdd(root);
    tdd.index_set = var_out;
    tdd.index_2_key = idx_2_key;
    tdd.key_2_index = key_2_idx;

    return tdd;
}

Edge contract(const Edge& edge1_in, const Edge& edge2_in, const std::vector<keyType>& key_2_new_key_0, const std::vector<keyType>& key_2_new_key_1, const std::vector<int>& cont_order_0, const std::vector<int>& cont_order_1, const int& cont_num) {
    Edge res;

    keyType k1 = edge1_in.node->key;
    keyType k2 = edge2_in.node->key;
    std::complex<dataType> w1 = edge1_in.weight;
    std::complex<dataType> w2 = edge2_in.weight;

    // Terminal case 1: Both inputs are terminal nodes
    if ((k1 == -1) && (k2 == -1)) {
        if (w1 == std::complex<dataType>(0.0, 0.0)) {
            res = Edge(edge1_in.node);
            res.weight = 0;
            return res;
        }
        if (w2 == std::complex<dataType>(0.0, 0.0)) {
            res = Edge(edge1_in.node);
            res.weight = 0;
            return res;
        }
        res = Edge(edge1_in.node);
        res.weight = w1 * w2;
        if (cont_num > 0) { res.weight *= std::pow(2, cont_num); }
        return res;
    }
    // Terminal case 2: If edge1 is terminal node
    if (k1 == -1) {
        if (w1 == std::complex<dataType>(0.0, 0.0)) {
            res = Edge(edge1_in.node);
            res.weight = 0;
            return res;
        }
        if ((cont_num == 0) && (key_2_new_key_1[k2] == k2)) {
            res = Edge(edge2_in.node);
            res.weight = w1 * w2;
            return res;
        }
    }
    // Terminal case 3: If edge2 is terminal node
    if (k2 == -1) {
        if (w2 == std::complex<dataType>(0.0, 0.0)) {
            res = Edge(edge2_in.node);
            res.weight = 0;
            return res;
        }
        if ((cont_num == 0) && (key_2_new_key_0[k1] == k1)) {
            res = Edge(edge1_in.node);
            res.weight = w1 * w2;
            return res;
        }
    }

    // Normalize input tdds' weights to 1 for contraction computed table query
    Edge edge1 = edge1_in; edge1.weight = 1;
    Edge edge2 = edge2_in; edge2.weight = 1;


    if (k1 + k2 > 3) {
        // key_2_new_key for the curent level of recursion

        // Query contraction computed table
        Edge find_cont = cont_computed_table.find(edge1.node, edge2.node, key_2_new_key_0, k1 + 1,
                                                  key_2_new_key_1, k2 + 1);
        if (find_cont.node != nullptr) {
            res = find_cont;
            res.weight *= w1 * w2;
            return res;
        }
    }

    // Recursive contraction // @romOlivo Changed for static array size
    std::array<Edge, succ_num> the_successors; keyType the_key;
    if (cont_order_0[k1+1] < cont_order_1[k2+1]) { // edge1 is now on top of edge2
        the_key = key_2_new_key_0[k1];
        if (the_key != -2) { // if x not in var
            for (uint k = 0; k < succ_num; k++) {
                the_successors[k] = contract(Slicing(edge1, k1, k), edge2, key_2_new_key_0, key_2_new_key_1, cont_order_0, cont_order_1, cont_num);
            }
            res = normalize(the_key, the_successors);
            if (k1 + k2 > 3)
                cont_computed_table.insert(edge1.node, edge2.node, key_2_new_key_0, k1 + 1,
                                             key_2_new_key_1, k2 + 1, res);
            res.weight *= w1 * w2;
        } else { // if x in var
            res = add(contract(Slicing(edge1, k1, 0), edge2, key_2_new_key_0, key_2_new_key_1, cont_order_0, cont_order_1, cont_num - 1),
                      contract(Slicing(edge1, k1, 1), edge2, key_2_new_key_0, key_2_new_key_1, cont_order_0, cont_order_1, cont_num - 1));
            if (k1 + k2 > 3)
                cont_computed_table.insert(edge1.node, edge2.node, key_2_new_key_0, k1 + 1,
                                             key_2_new_key_1, k2 + 1, res);
            res.weight *= w1 * w2;
        }
    } else if (cont_order_0[k1+1] == cont_order_1[k2+1]) { // Two tdds get to the same index
        the_key = key_2_new_key_0[k1];
        if (the_key != -2) { // if x not in var
            for (uint k = 0; k < succ_num; k++) {
                the_successors[k] = contract(Slicing(edge1, k1, k), Slicing(edge2, k2, k), key_2_new_key_0, key_2_new_key_1, cont_order_0, cont_order_1, cont_num);
            }
            res = normalize(the_key, the_successors);
            if (k1 + k2 > 3)
                cont_computed_table.insert(edge1.node, edge2.node, key_2_new_key_0, k1 + 1,
                                             key_2_new_key_1, k2 + 1, res);
            res.weight *= w1 * w2;
        } else { // if x in var
            res = add(contract(Slicing(edge1, k1, 0), Slicing(edge2, k2, 0), key_2_new_key_0, key_2_new_key_1, cont_order_0, cont_order_1, cont_num - 1),
                      contract(Slicing(edge1, k1, 1), Slicing(edge2, k2, 1), key_2_new_key_0, key_2_new_key_1, cont_order_0, cont_order_1, cont_num - 1));
            cont_computed_table.insert(edge1.node, edge2.node, key_2_new_key_0, k1 + 1,
                                             key_2_new_key_1, k2 + 1, res);
            res.weight *= w1 * w2;
        }
    } else { // edge2 is on top of edge1
        the_key = key_2_new_key_1[k2];
        if (the_key != -2) { // if x not in var
            for (uint k = 0; k < succ_num; k++) {
                the_successors[k] = contract(edge1, Slicing(edge2, k2, k), key_2_new_key_0, key_2_new_key_1, cont_order_0, cont_order_1, cont_num);
            }
            res = normalize(the_key, the_successors);
            if (k1 + k2 > 3)
                cont_computed_table.insert(edge1.node, edge2.node, key_2_new_key_0, k1 + 1,
                                             key_2_new_key_1, k2 + 1, res);
            res.weight *= w1 * w2;
        } else { // if x in var
            res = add(contract(edge1, Slicing(edge2, k2, 0), key_2_new_key_0, key_2_new_key_1, cont_order_0, cont_order_1, cont_num - 1),
                      contract(edge1, Slicing(edge2, k2, 1), key_2_new_key_0, key_2_new_key_1, cont_order_0, cont_order_1, cont_num - 1));
            if (k1 + k2 > 3)
                cont_computed_table.insert(edge1.node, edge2.node, key_2_new_key_0, k1 + 1,
                                             key_2_new_key_1, k2 + 1, res);
            res.weight *= w1 * w2;
        }
    }

    return res;
}
