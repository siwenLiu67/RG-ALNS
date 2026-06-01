"""0-1 knapsack solver for maximum recoverable service quantity.

The recoverability knapsack is:

  maximize   Σ q_j · z_j
  subject to Σ w̲_{j,B}(t) · z_j  ≤  Cap_B(t, d_r)
             z_j ∈ {0, 1}

Solved via exact dynamic programming by default, with an API that permits
a MILP/CP-SAT fallback later.
"""

from ..core.dataclasses import SLISPInstance
from ..core.schedule_state import ScheduleState
from .capacity_pool import available_pool_capacity, unavoidable_pool_workload
from .earliest_bounds import eligible_recovery_jobs


def _solve_knapsack_dp(
    items: list[tuple[int, int, int]],  # (job_id, value, weight)
    capacity: int,
) -> tuple[int, set[int]]:
    """Solve 0-1 knapsack via 1D dynamic programming with backtracking.

    Args:
        items: list of (job_id, value, weight) triples.
        capacity: integer knapsack capacity.

    Returns:
        (max_value, set of selected job_ids).
    """
    n = len(items)
    if n == 0 or capacity <= 0:
        return 0, set()

    # 1D DP: dp[w] = max value for capacity w (using processed items)
    dp = [0] * (capacity + 1)
    # Track which items are used: choice[i][w] = True if item i is selected at capacity w
    choice: list[list[bool]] = [[False] * (capacity + 1) for _ in range(n)]

    for i, (_job_id, value, weight) in enumerate(items):
        if weight <= 0:
            # Zero-weight items are always taken
            for w in range(capacity + 1):
                dp[w] += value
                choice[i][w] = True
            continue

        for w in range(capacity, weight - 1, -1):
            new_val = dp[w - weight] + value
            if new_val > dp[w]:
                dp[w] = new_val
                choice[i][w] = True

    # Backtrack to find selected items
    max_value = dp[capacity]
    selected: set[int] = set()
    w = capacity
    for i in range(n - 1, -1, -1):
        if choice[i][w]:
            job_id, _value, weight = items[i]
            selected.add(job_id)
            if weight > 0:
                w -= weight
            # If weight == 0, w stays the same (already accounted)

    return max_value, selected


def maximum_recoverable_service_quantity(
    entity_id: int,
    pool_B: set[int],
    state: ScheduleState,
    instance: SLISPInstance,
    method: str = "dp",
) -> tuple[int, set[int]]:
    """Compute the maximum recoverable service quantity Q̅_rec_{r,B}(t).

    Solves the 0-1 knapsack over eligible recovery jobs.

    Args:
        entity_id: the service entity r.
        pool_B: the set of machine ids forming the bottleneck pool.
        state: current schedule state.
        instance: the problem instance.
        method: solver method, "dp" (default) or "cp_sat" (future).

    Returns:
        (Q_rec_bar, selected_job_ids) — max recoverable quantity and the set
        of job ids that achieve it.
    """
    eligible = eligible_recovery_jobs(entity_id, state, instance)
    if not eligible:
        return 0, set()

    capacity = available_pool_capacity(pool_B, entity_id, state, instance)
    if capacity <= 0:
        return 0, set()

    # Build items
    items: list[tuple[int, int, int]] = []  # (job_id, value=q_j, weight=w_lower)
    for job_id in eligible:
        job = instance.get_job(job_id)
        weight = unavoidable_pool_workload(job, pool_B, state)
        items.append((job_id, job.quantity, weight))

    if method == "dp":
        max_val, selected = _solve_knapsack_dp(items, capacity)
    else:
        raise ValueError(f"Unknown knapsack method: {method}")

    return max_val, selected


def exclusion_recoverable_quantity(
    entity_id: int,
    excluded_job_id: int,
    pool_B: set[int],
    state: ScheduleState,
    instance: SLISPInstance,
    method: str = "dp",
) -> int:
    """Compute Q̅_rec^{-j}_{r,B}(t): max recoverable quantity excluding job j.

    Re-runs the knapsack with the specified job removed from the eligible set.
    """
    eligible = eligible_recovery_jobs(entity_id, state, instance)
    eligible_filtered = [j for j in eligible if j != excluded_job_id]

    if not eligible_filtered:
        return 0

    capacity = available_pool_capacity(pool_B, entity_id, state, instance)
    if capacity <= 0:
        return 0

    items: list[tuple[int, int, int]] = []
    for job_id in eligible_filtered:
        job = instance.get_job(job_id)
        weight = unavoidable_pool_workload(job, pool_B, state)
        items.append((job_id, job.quantity, weight))

    if method == "dp":
        max_val, _ = _solve_knapsack_dp(items, capacity)
    else:
        raise ValueError(f"Unknown knapsack method: {method}")

    return max_val
