#!/usr/bin/python3 env
import math

import numpy as np
import pyomo.environ as pyo
from collections import deque


def solve_routing_MILP(
    N, P, T_max, revenues, cost, dist_matr, tau, v, R, r, start_node=0, end_node=0
):
    """
    All constraints MILP solutions to routing.

    Parameters:
    - N: total number of nodes
    - P: max number of checkpoints to visit
    - Tmax: max total time allowed
    - revenues_lst: list of revenues_lst for each node (length N)
    - c: cost coefficient per distance
    - d: NxN distance matrix
    - tau_lst: list of inspection times per node
    - v: speed of travel
    - R: max distance from depot (0) to any node
    - r: max distance from current node to next node
    - start_node[default=0]: start depot point
    - end_node[default=0]: final depot point

    Returns:
    - best_route: list of nodes including depot as start
    - best_time: total time of best route_lst
    - best_revenue: revenue collected from best route_lst
    - model: Solver model
    """
    DEBUG_MILP = False
    model = pyo.ConcreteModel()

    assert len(revenues) == N + 1, f"{N} is not len(w)= {len(revenues)}"
    assert len(tau) == N + 1, f"{N} is not len(w)= {len(tau)}"

    if N < 1:
        return [0], 0, 0
    elif N == 1:
        return (
            [0, 1, 0],
            (dist_matr[0][1] + dist_matr[1][0]) / v,
            revenues[0] - cost * (dist_matr[0][1] + dist_matr[1][0]),
        )

    BIG_M = 10000

    # Sets
    model.NODES = pyo.RangeSet(0, N)  # All nodes including start
    model.CITIES = pyo.RangeSet(1, N)  # Only inspection nodes (1..N)

    # Parameters
    model.w = pyo.Param(model.NODES, initialize=lambda model, i: revenues[i])
    # if not isinstance(dist_matr, np.ndarray):
    model.d = pyo.Param(
        model.NODES,
        model.NODES,
        initialize=lambda model, i, j: (
            dist_matr[i][j] if not math.isinf(dist_matr[i][j]) else BIG_M
        ),
    )
    # else:
    #     model.d = pyo.Param(model.NODES, model.NODES,
    #                         initialize=lambda model, i, j: dist_matr[i,j] if not math.isinf(dist_matr[i,j]) else BIG_M)

    model.tau = pyo.Param(model.NODES, initialize=lambda model, j: tau[j])

    model.v = pyo.Param(initialize=v)
    model.c = pyo.Param(initialize=cost)
    model.R = pyo.Param(initialize=R)
    model.r = pyo.Param(initialize=r)

    # Decision variables
    model.x = pyo.Var(model.NODES, model.NODES, domain=pyo.Binary)
    model.u = pyo.Var(model.NODES, domain=pyo.Integers, bounds=(0, P))
    model.t_total = pyo.Var(within=pyo.NonNegativeReals)

    # Clean up previous constraints
    constraint_names = [
        "max_inspections",
        "time_total",
        "dist_lim",
        "dist_zone",
        "no_circling",
        "visit_once_out",
        "visit_once_in",
        "start_from_zero",
        "return_to_zero",
        "mtz",
        "flow_conservation",
    ]

    for name in constraint_names:
        if hasattr(model, name):
            model.del_component(name)

    # Objective function
    def obj_expression(model):
        return sum(
            model.w[j] * model.x[i, j]
            for i in model.NODES
            for j in model.NODES
            if i != j
        ) - sum(
            model.c * model.d[i, j] * model.x[i, j]
            for i in model.NODES
            for j in model.NODES
            if i != j
        )

    model.obj = pyo.Objective(rule=obj_expression, sense=pyo.maximize)

    # Constraints
    # 1. Max number of inspections
    model.max_inspections = pyo.Constraint(
        expr=sum(model.x[i, j] for i in model.CITIES for j in model.CITIES if i != j)
        <= P
    )

    # 2. Total time constraint
    def total_time_calculation_rule(model):
        return model.t_total == sum(
            model.x[i, j] * (model.d[i, j] / model.v + model.tau[j])
            for i in model.NODES
            for j in model.NODES
            if i != j
        )

    model.total_time_calc = pyo.Constraint(rule=total_time_calculation_rule)

    def total_time_limit_rule(model):
        return model.t_total <= T_max

    model.time_limit = pyo.Constraint(rule=total_time_limit_rule)

    # 3. Max allowed zone (from/to start) and Neighborhood distance constraints
    model.dist_lim = pyo.ConstraintList()
    for i in model.CITIES:
        for j in model.CITIES:
            if model.d[i, j] >= BIG_M:
                model.dist_lim.add(model.x[i, j] == 0)

    # Probably this condition is already satisfied on main clause
    # But we can write it anyway
    model.dist_zone = pyo.ConstraintList()
    for i in model.CITIES:
        if model.d[start_node, i] >= BIG_M:
            model.dist_zone.add(expr=sum(model.x[i, j] for j in model.CITIES) == 0)
            model.dist_zone.add(expr=sum(model.x[j, i] for j in model.CITIES) == 0)
        elif model.d[i, end_node] >= BIG_M:
            model.dist_zone.add(expr=sum(model.x[i, j] for j in model.CITIES) == 0)
            model.dist_zone.add(expr=sum(model.x[j, i] for j in model.CITIES) == 0)

    # 4. No self-loop
    model.no_circling = pyo.ConstraintList()
    for i in model.NODES:
        model.no_circling.add(model.x[i, i] == 0)

    # 5. Visit once
    model.visit_once_out = pyo.ConstraintList()
    model.visit_once_in = pyo.ConstraintList()
    for i in model.NODES:
        model.visit_once_out.add(sum(model.x[i, j] for j in model.NODES if j != i) <= 1)
        model.visit_once_in.add(sum(model.x[j, i] for j in model.NODES if j != i) <= 1)

    # 6. Start and return
    model.start_from_zero = pyo.Constraint(
        expr=sum(model.x[start_node, j] for j in model.CITIES) == 1
    )
    model.return_to_zero = pyo.Constraint(
        expr=sum(model.x[i, end_node] for i in model.CITIES) == 1
    )

    # 7. MTZ subtour elimination
    model.mtz = pyo.ConstraintList()
    for i in model.NODES:
        for j in model.NODES:
            if i != j and j != 0 and i != 0:
                model.mtz.add(model.u[i] - model.u[j] + P * model.x[i, j] <= P - 1)

    # 8. Flow conservation (in == out)
    model.flow_conservation = pyo.ConstraintList()
    for k in model.NODES:
        model.flow_conservation.add(
            sum(model.x[k, j] for j in model.NODES if j != k)
            == sum(model.x[i, k] for i in model.NODES if i != k)
        )

    print(f"Solver launching for {N}x{N} bool matrix, {N} integers")
    # Solve
    # solver = pyo.SolverFactory('gurobi')  # Or 'glpk' if you prefer
    # solver = pyo.SolverFactory('glpk')  # Or 'glpk' if you prefer
    solver = pyo.SolverFactory("cbc")

    results = solver.solve(model)
    # print("results", results)

    if (results.solver.status == pyo.SolverStatus.ok) and (
        results.solver.termination_condition == pyo.TerminationCondition.optimal
    ):

        if DEBUG_MILP:
            model.display()

        # Extract route_lst
        try:
            edges = [
                (i, j)
                for i in range(N + 1)
                for j in range(N + 1)
                if pyo.value(model.x[i, j]) > 0.5
            ]
            best_route = [start_node]
            start = start_node
            end = end_node
            found = False
            while not found:
                for edge in edges:
                    if edge[0] == start:
                        if DEBUG_MILP:
                            print(edge)
                        if edge[1] == end:
                            best_route.append(edge[1])
                            found = True
                            break
                        best_route.append(edge[1])
                        start = edge[1]
                        break

            best_revenue = pyo.value(model.obj)

            # Extract t_total value from solved model
            best_time = pyo.value(model.t_total)

            print("Objective:", best_revenue)
            return best_route, best_time, best_revenue
        except Exception as e:
            print(e)
            return [], 0, 0

    # Do something when the solution in optimal and feasible
    elif results.solver.termination_condition == pyo.TerminationCondition.infeasible:
        # Do something when model in infeasible
        print("Infeasible!")
        return [], 0, 0

    else:
        # Something else is wrong
        print(f"Solver status: {results.solver.status}")
        return [], 0, 0


def solve_routing_MILP_optimized(
    N, P, T_max, revenues, cost, dist_matr, tau, v, R, r, start_node=0, end_node=0
):
    # Step 1: Precompute reachable nodes and feasible arcs
    if N <= 0:
        return [start_node], 0, 0

    # Build forward graph with feasibility rules
    forward_graph = {i: set() for i in range(N + 1)}
    for i in range(N + 1):
        for j in range(N + 1):
            if i == j:
                continue
            if math.isinf(dist_matr[i][j]) or dist_matr[i][j] > 1e6:  # Skip unreachable
                continue

            if i == start_node:
                if dist_matr[i][j] <= R:
                    forward_graph[i].add(j)
            elif j == end_node:
                if dist_matr[i][j] <= R:
                    forward_graph[i].add(j)
            else:
                if dist_matr[i][j] <= r:
                    forward_graph[i].add(j)

    # Compute reachable nodes from start
    reachable_from_start = set()
    queue = deque([start_node])
    while queue:
        i = queue.popleft()
        if i not in reachable_from_start:
            reachable_from_start.add(i)
            for j in forward_graph[i]:
                if j not in reachable_from_start:
                    queue.append(j)

    # Compute reverse graph for end reachability
    reverse_graph = {i: set() for i in range(N + 1)}
    for i in forward_graph:
        for j in forward_graph[i]:
            reverse_graph[j].add(i)

    reachable_to_end = set()
    queue = deque([end_node])
    while queue:
        i = queue.popleft()
        if i not in reachable_to_end:
            reachable_to_end.add(i)
            for j in reverse_graph[i]:
                if j not in reachable_to_end:
                    queue.append(j)

    # Final candidate nodes and arcs
    candidate_nodes = reachable_from_start & reachable_to_end
    FEASIBLE_ARCS = []
    for i in candidate_nodes:
        for j in forward_graph[i]:
            if j in candidate_nodes and i != j:
                FEASIBLE_ARCS.append((i, j))

    # Handle empty candidate sets
    if not candidate_nodes:
        if start_node == end_node:
            return [start_node], 0, 0
        return (
            (
                [start_node, end_node]
                if (start_node, end_node) in FEASIBLE_ARCS
                else [start_node]
            ),
            0,
            0,
        )

    # Create model with reduced sets
    model = pyo.ConcreteModel()
    model.NODES = pyo.Set(initialize=sorted(candidate_nodes))
    model.ARCS = pyo.Set(initialize=FEASIBLE_ARCS, dimen=2)
    model.CITIES = model.NODES - {start_node, end_node}

    # Parameters
    model.w = pyo.Param(model.NODES, initialize=lambda m, i: revenues[i])
    model.d = pyo.Param(model.ARCS, initialize=lambda m, i, j: dist_matr[i][j])
    model.tau = pyo.Param(model.NODES, initialize=lambda m, j: tau[j])
    model.v = v
    model.c = cost

    # Variables - only for feasible arcs
    model.x = pyo.Var(model.ARCS, domain=pyo.Binary)
    model.u = pyo.Var(model.CITIES, domain=pyo.Integers, bounds=(1, P - 1))
    model.t_total = pyo.Var(within=pyo.NonNegativeReals)

    # Objective function - sparse version
    def obj_expression(model):
        revenue = sum(model.w[j] * model.x[i, j] for (i, j) in model.ARCS)
        travel_cost = sum(
            model.c * model.d[i, j] * model.x[i, j] for (i, j) in model.ARCS
        )
        return revenue - travel_cost

    model.obj = pyo.Objective(rule=obj_expression, sense=pyo.maximize)

    # Constraints - optimized for sparse representation
    # 1. Max number of inspections
    model.max_inspections = pyo.Constraint(
        expr=sum(
            model.x[i, j] for (i, j) in model.ARCS if i != start_node and j != end_node
        )
        <= P
    )

    # 2. Total time constraint
    def total_time_rule(model):
        return model.t_total == sum(
            model.x[i, j] * (model.d[i, j] / model.v + model.tau[j])
            for (i, j) in model.ARCS
        )

    model.total_time_calc = pyo.Constraint(rule=total_time_rule)
    model.time_limit = pyo.Constraint(expr=model.t_total <= T_max)

    # 3. Flow conservation
    def flow_conservation_rule(model, k):
        if k == start_node:
            return sum(model.x[k, j] for j in model.NODES if (k, j) in model.ARCS) == 1
        elif k == end_node:
            return sum(model.x[i, k] for i in model.NODES if (i, k) in model.ARCS) == 1
        else:
            in_flow = sum(model.x[i, k] for i in model.NODES if (i, k) in model.ARCS)
            out_flow = sum(model.x[k, j] for j in model.NODES if (k, j) in model.ARCS)
            return in_flow == out_flow

    model.flow_conservation = pyo.Constraint(model.NODES, rule=flow_conservation_rule)

    # 4. MTZ constraints - only for city-to-city arcs
    if model.CITIES:

        def mtz_rule(model, i, j):
            if (
                i != j
                and (i, j) in model.ARCS
                and i in model.CITIES
                and j in model.CITIES
            ):
                return model.u[i] - model.u[j] + P * model.x[i, j] <= P - 1
            else:
                return pyo.Constraint.Skip

        model.mtz = pyo.Constraint(model.CITIES, model.CITIES, rule=mtz_rule)

    # Solve with optimized parameters
    solver = pyo.SolverFactory("cbc")
    solver.options = {
        "cuts": "on",
        "preprocess": "aggregate",
        "heuristics": "on",
        "threads": 4,
        "seconds": 60,  # Timeout after 60 seconds
    }
    results = solver.solve(model)

    # Solution extraction
    if results.solver.termination_condition == pyo.TerminationCondition.optimal:
        # Extract route from sparse arc variables
        active_arcs = [
            (i, j) for (i, j) in model.ARCS if pyo.value(model.x[i, j]) > 0.5
        ]
        route = [start_node]
        current = start_node
        while current != end_node:
            for i, j in active_arcs:
                if i == current:
                    route.append(j)
                    current = j
                    break
        return route, pyo.value(model.t_total), pyo.value(model.obj)

    return [], 0, 0


if __name__ == "__main__":
    # Sample data setup
    N = 5
    P = 3
    T_max = 100
    w = [0, 10, 20, 15, 5, 8]  # revenue per node, including dummy 0
    c = 0.5
    v = 1.0
    tau = [0, 5, 5, 5, 5, 5]
    R = 100
    r = 50

    # Example distance matrix (symmetric for simplicity)
    d = [
        [0, 10, 20, 30, 40, 50],
        [10, 0, 15, 25, 35, 45],
        [20, 15, 0, 10, 20, 30],
        [30, 25, 10, 0, 15, 25],
        [40, 35, 20, 15, 0, 10],
        [50, 45, 30, 25, 10, 0],
    ]
    # Parameters
    N = 5  # 0 is depot, 1–5 are inspection points
    P = 3  # max number of inspections
    T_max = 100  # max total time
    v = 1.0  # speed
    R = 100  # max distance from/to depot
    r = 50  # max distance between consecutive nodes
    c = 0.2  # price of 1 m

    # Revenue for each node
    w = [0, 30, 40, 25, 20, 35]  # w[0] = 0 since depot gives no reward

    # Inspection time at each node (in time units)
    tau = [0, 10, 15, 10, 5, 10]  # tau_lst[0] = 0 (depot)

    # Distance matrix (symmetric)
    d = np.array(
        [
            [0, 10, 20, 30, 40, 25],
            [10, 0, 15, 25, 35, 20],
            [20, 15, 0, 10, 20, 25],
            [30, 25, 10, 0, 15, 30],
            [40, 35, 20, 15, 0, 35],
            [25, 20, 25, 30, 35, 0],
        ]
    )

    routes, t, val = solve_routing_MILP_optimized(N, P, T_max, w, c, d, tau, v, R, r)
    print("Chosen routes:", routes)
    print("Objective:", val)

    routes, t, val = solve_routing_MILP(N, P, T_max, w, c, d, tau, v, R, r)
    print("Chosen routes:", routes)
    print("Objective:", val)
