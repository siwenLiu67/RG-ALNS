"""Unavoidable shortfall lower bound computation.

U̲_{r,B}(t) = max(0, Q_rem_r(t) − Q̅_rec_{r,B}(t))

This lower bound tells us the minimum service shortfall that entity r will
incur no matter what scheduling decisions we make from time t onward.
"""

from ..core.dataclasses import SLISPInstance
from ..core.schedule_state import ScheduleState
from .earliest_bounds import remaining_service_quantity
from .knapsack_recovery import maximum_recoverable_service_quantity


def unavoidable_shortfall_lower_bound(
    entity_id: int,
    pool_B: set[int],
    state: ScheduleState,
    instance: SLISPInstance,
    method: str = "dp",
) -> int:
    """Compute U̲_{r,B}(t): the unavoidable service shortfall lower bound.

    U̲_{r,B}(t) = max(0, Q_rem_r(t) − Q̅_rec_{r,B}(t))
    """
    q_rem = remaining_service_quantity(entity_id, state, instance)
    if q_rem <= 0:
        return 0

    q_rec_bar, _ = maximum_recoverable_service_quantity(
        entity_id, pool_B, state, instance, method=method
    )
    return max(0, q_rem - q_rec_bar)
