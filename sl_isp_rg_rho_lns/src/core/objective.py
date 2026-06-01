"""Objective function computation for the SL-ISP problem."""

from dataclasses import dataclass

from .dataclasses import SLISPInstance
from .schedule_state import ScheduleState


@dataclass
class ObjectiveResult:
    """Result of evaluating the objective function on a schedule."""

    total_tardiness: int
    weighted_service_shortfall: float
    Z: float
    zero_shortfall_entity_rate: float
    per_entity_shortfall: dict[int, float]
    per_job_tardiness: dict[int, int]
    per_entity_on_time_quantity: dict[int, int]


def compute_objective(
    instance: SLISPInstance, state: ScheduleState
) -> ObjectiveResult:
    """Compute the full objective from a final ScheduleState.

    Z = alpha * sum_j T_j + beta * sum_r w_r * U_r

    where:
      T_j = max(0, D_j - d_{g(j)})    job delivery tardiness
      D_j = C_j + tau_{g(j)}          delivery time
      U_r = max(0, Q_min_r - Q_on_time_r)   entity service shortfall
    """
    per_job_tardiness: dict[int, int] = {}
    per_entity_on_time_qty: dict[int, int] = {e.entity_id: 0 for e in instance.entities}
    per_entity_shortfall: dict[int, float] = {}

    for job in instance.jobs:
        entity = instance.get_entity(job.entity_id)
        c_j = state.completed_jobs.get(job.job_id)
        if c_j is None:
            raise ValueError(
                f"Job {job.job_id} has no completion time; schedule is incomplete"
            )
        d_j = c_j + entity.transport_delay
        t_j = max(0, d_j - entity.deadline)
        per_job_tardiness[job.job_id] = t_j

        if d_j <= entity.deadline:
            per_entity_on_time_qty[entity.entity_id] += job.quantity

    total_tardiness = sum(per_job_tardiness.values())

    weighted_shortfall = 0.0
    zero_shortfall_count = 0

    for entity in instance.entities:
        on_time = per_entity_on_time_qty[entity.entity_id]
        shortfall = max(0.0, float(entity.min_fulfillment - on_time))
        per_entity_shortfall[entity.entity_id] = shortfall
        weighted_shortfall += entity.weight * shortfall
        if shortfall == 0.0:
            zero_shortfall_count += 1

    zsr = zero_shortfall_count / instance.num_entities if instance.num_entities > 0 else 0.0

    Z = instance.alpha * total_tardiness + instance.beta * weighted_shortfall

    return ObjectiveResult(
        total_tardiness=total_tardiness,
        weighted_service_shortfall=weighted_shortfall,
        Z=Z,
        zero_shortfall_entity_rate=zsr,
        per_entity_shortfall=per_entity_shortfall,
        per_job_tardiness=per_job_tardiness,
        per_entity_on_time_quantity=per_entity_on_time_qty,
    )
