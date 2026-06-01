"""Mandatory rescue job identification and classification.

A job j is mandatory for entity r if the entity's remaining service
requirement *can* be met with j but *cannot* be met without j.
"""

from ..core.dataclasses import SLISPInstance
from ..core.schedule_state import ScheduleState
from .earliest_bounds import eligible_recovery_jobs, remaining_service_quantity
from .knapsack_recovery import exclusion_recoverable_quantity, maximum_recoverable_service_quantity


def mandatory_rescue_jobs(
    entity_id: int,
    pool_B: set[int],
    state: ScheduleState,
    instance: SLISPInstance,
    method: str = "dp",
) -> list[int]:
    """Return the list of job_ids in the mandatory rescue set M_r(t).

    A job j is mandatory if:
      Q̅_rec_{r,B}(t)  ≥ Q_rem_r(t)
      AND
      Q̅_rec^{-j}_{r,B}(t) < Q_rem_r(t)

    In other words: recovery is currently achievable, but removing j makes it
    impossible.
    """
    q_rem = remaining_service_quantity(entity_id, state, instance)
    if q_rem <= 0:
        return []

    q_rec_bar, _ = maximum_recoverable_service_quantity(
        entity_id, pool_B, state, instance, method=method
    )
    if q_rec_bar < q_rem:
        # Recovery is not even possible with all jobs
        return []

    eligible = eligible_recovery_jobs(entity_id, state, instance)
    mandatory: list[int] = []

    for job_id in eligible:
        q_rec_excl = exclusion_recoverable_quantity(
            entity_id, job_id, pool_B, state, instance, method=method
        )
        if q_rec_excl < q_rem:
            mandatory.append(job_id)

    return mandatory


def classify_mandatory_type(
    job_id: int,
    entity_id: int,
    pool_B: set[int],
    state: ScheduleState,
    instance: SLISPInstance,
    method: str = "dp",
) -> str:
    """Classify a mandatory job as quantity- or capacity-mandatory.

    Returns one of:
      - "quantity_mandatory": sum of other jobs' quantities < Q_rem_r(t).
          Even with unlimited capacity, the entity cannot meet its requirement
          without this job.
      - "capacity_mandatory": sum of other jobs' quantities ≥ Q_rem_r(t), but
          the knapsack capacity constraint prevents recovery without this job.
      - "not_mandatory": the job is not mandatory (removing it still allows
          recovery, or recovery is already impossible).
    """
    q_rem = remaining_service_quantity(entity_id, state, instance)
    if q_rem <= 0:
        return "not_mandatory"

    eligible = eligible_recovery_jobs(entity_id, state, instance)

    # Compute total quantity of all eligible jobs EXCEPT this one
    other_quantity = 0
    for eid in eligible:
        if eid == job_id:
            continue
        other_quantity += instance.get_job(eid).quantity

    if other_quantity < q_rem:
        return "quantity_mandatory"

    # Check capacity-mandatory
    q_rec_excl = exclusion_recoverable_quantity(
        entity_id, job_id, pool_B, state, instance, method=method
    )
    if q_rec_excl < q_rem:
        return "capacity_mandatory"

    return "not_mandatory"
