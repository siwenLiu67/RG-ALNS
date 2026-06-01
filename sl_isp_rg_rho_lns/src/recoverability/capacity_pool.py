"""Resource-pool capacity and unavoidable workload computations.

The resource pool B ⊆ M is a set of bottleneck machines.  These functions
compute (a) how much total processing time is available on B before a deadline,
and (b) how much work each job *must* perform on B (cannot be routed elsewhere).
"""

from ..core.dataclasses import Job, SLISPInstance
from ..core.schedule_state import ScheduleState


def available_pool_capacity(
    pool_B: set[int],
    entity_id: int,
    state: ScheduleState,
    instance: SLISPInstance,
) -> int:
    """Total available processing time on machines in pool B before the entity deadline.

    Cap_B(t, d_r) = Σ_{h∈B}  max(0, d_r − a_h(t))

    where a_h(t) is the earliest time machine h becomes available:
      - t         if h is idle at t
      - f_h(t)    if h is currently processing a non-preemptive operation
    """
    entity = instance.get_entity(entity_id)
    d_r = entity.deadline
    total = 0
    for h in pool_B:
        a_h = state.machine_available_times.get(h, 0)
        earliest_available = max(state.current_time, a_h)
        total += max(0, d_r - earliest_available)
    return total


def unavoidable_pool_workload(
    job: Job,
    pool_B: set[int],
    state: ScheduleState,
) -> int:
    """Minimum processing time that job *must* consume on machines in pool B.

    w̲_{j,B}(t) = Σ_o  w̲_{jo,B}(t)  where:

    - completed operation           → 0
    - ongoing op on h ∈ B          → remaining processing time on h
    - ongoing op on h ∉ B          → 0
    - unstarted op, all eligible    machines ⊆ B → min processing time
    - otherwise                     → 0
    """
    total = 0
    for op in job.operations:
        op_key = (op.job_id, op.op_id)

        # Completed → 0
        if op_key in state.completed_operations:
            continue

        # Ongoing
        if op_key in state.ongoing_operations:
            ongoing = state.ongoing_operations[op_key]
            if ongoing.machine_id in pool_B:
                remaining = max(0, ongoing.end_time - state.current_time)
                total += remaining
            continue

        # Unstarted: count min processing time only if ALL eligible machines are in B
        eligible_set = set(alt.machine_id for alt in op.alternatives)
        if eligible_set.issubset(pool_B):
            total += op.min_processing_time

    return total
