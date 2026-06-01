"""Optimistic lower-bound computations for earliest completion and delivery times.

These bounds are fundamental to the recoverability diagnosis: they tell us,
under ideal conditions (no contention), whether a job *could* still be
delivered on time.
"""

from ..core.dataclasses import Job, Operation, SLISPInstance
from ..core.schedule_state import ScheduleState


def optimistic_remaining_operation_time(
    op: Operation,
    job: Job,
    state: ScheduleState,
) -> int:
    """Optimistic residual processing time for a single operation.

    - completed operation → 0
    - ongoing operation → committed end_time − current_time
    - unstarted operation → minimum processing time among eligible machines
    """
    op_key = (op.job_id, op.op_id)

    if op_key in state.completed_operations:
        return 0

    if op_key in state.ongoing_operations:
        ongoing = state.ongoing_operations[op_key]
        return max(0, ongoing.end_time - state.current_time)

    return op.min_processing_time


def optimistic_job_completion_lower_bound(
    job: Job,
    state: ScheduleState,
) -> int:
    """Optimistic lower bound on the completion time of a job.

    C̲_j(t) = max(t, r_j) + Σ optimistic remaining operation times.
    """
    base = max(state.current_time, job.release_time)
    residual = 0
    for op in job.operations:
        residual += optimistic_remaining_operation_time(op, job, state)
    return base + residual


def optimistic_delivery_lower_bound(
    job: Job,
    state: ScheduleState,
    instance: SLISPInstance,
) -> int:
    """Optimistic lower bound on the delivery time of a job.

    D̲_j(t) = C̲_j(t) + τ_{g(j)}.
    """
    entity = instance.get_entity(job.entity_id)
    c_lower = optimistic_job_completion_lower_bound(job, state)
    return c_lower + entity.transport_delay


def secured_quantity(
    entity_id: int,
    state: ScheduleState,
    instance: SLISPInstance,
) -> int:
    """Sum of quantities of jobs whose production is complete and delivered on time.

    Q_sec_r(t) = Σ_{j: C_j ≤ t, C_j + τ_r ≤ d_r}  q_j.
    """
    entity = instance.get_entity(entity_id)
    total = 0
    for job in instance.jobs:
        if job.entity_id != entity_id:
            continue
        c_j = state.completed_jobs.get(job.job_id)
        if c_j is None:
            continue
        delivery = c_j + entity.transport_delay
        if delivery <= entity.deadline:
            total += job.quantity
    return total


def remaining_service_quantity(
    entity_id: int,
    state: ScheduleState,
    instance: SLISPInstance,
) -> int:
    """Remaining service requirement for an entity.

    Q_rem_r(t) = max(0, Q_min_r − Q_sec_r(t)).
    """
    entity = instance.get_entity(entity_id)
    secured = secured_quantity(entity_id, state, instance)
    return max(0, entity.min_fulfillment - secured)


def eligible_recovery_jobs(
    entity_id: int,
    state: ScheduleState,
    instance: SLISPInstance,
) -> list[int]:
    """Return the list of job_ids in the eligible recovery set E_r(t).

    E_r(t) = { j ∈ J_open_r(t) : D̲_j(t) ≤ d_r }.
    """
    entity = instance.get_entity(entity_id)
    eligible: list[int] = []
    for job in instance.jobs:
        if job.entity_id != entity_id:
            continue
        if state.is_job_completed(job.job_id):
            continue
        d_lower = optimistic_delivery_lower_bound(job, state, instance)
        if d_lower <= entity.deadline:
            eligible.append(job.job_id)
    return eligible
