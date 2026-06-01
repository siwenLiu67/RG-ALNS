"""Dispatching-rule baseline scheduling algorithms.

Each rule implements the SchedulingAlgorithm signature:
  (instance, state) -> list[(job_id, op_id, machine_id, start_time)]

1. EDD: earliest effective production deadline first
2. Service-weighted deadline: score = w_r * q_j / max(eps, d_r - D_lower_j(t))
3. Shortfall-greedy: score = w_r * q_j / max(eps, w_lower_{j,B}(t)),
   boosted for entities with positive unavoidable shortfall
"""

from ..core.dataclasses import Job, Operation, SLISPInstance
from ..core.schedule_state import ScheduleState
from ..recoverability.earliest_bounds import (
    optimistic_delivery_lower_bound,
    optimistic_remaining_operation_time,
)
from ..recoverability.capacity_pool import unavoidable_pool_workload
from ..recoverability.shortfall_bounds import unavoidable_shortfall_lower_bound

EPS = 1


# ── Shared helpers ──────────────────────────────────────────────────────────

def _collect_ready_ops(
    instance: SLISPInstance, state: ScheduleState
) -> list[tuple[Job, Operation]]:
    """Return list of (job, operation) for all ready, unscheduled operations."""
    ready: list[tuple[Job, Operation]] = []
    for job in instance.jobs:
        if state.is_job_completed(job.job_id):
            continue
        if job.release_time > state.current_time:
            continue
        next_idx = state.next_op_index_for_job(job.job_id)
        if next_idx >= job.num_operations:
            continue
        op = job.operation_at(next_idx)
        if state.is_operation_completed(job.job_id, op.op_id):
            continue
        if state.is_operation_ongoing(job.job_id, op.op_id):
            continue
        ready.append((job, op))
    return ready


def _dispatch_on_idle_machines(
    instance: SLISPInstance,
    state: ScheduleState,
    ready_ops: list[tuple[Job, Operation]],
    score_fn,
) -> list[tuple[int, int, int, int]]:
    """Generic dispatcher: for each idle machine, pick the best-scoring ready op.

    score_fn(job, op, machine_id) -> float (higher = better priority).
    """
    decisions: list[tuple[int, int, int, int]] = []
    assigned_op_ids: set[tuple[int, int]] = set()

    idle_machines = [
        m.machine_id
        for m in instance.machines
        if state.is_machine_idle(m.machine_id)
    ]

    for m_id in idle_machines:
        avail = state.machine_available_times.get(m_id, 0)
        start_lower = max(state.current_time, avail)

        candidates = []
        for job, op in ready_ops:
            if (job.job_id, op.op_id) in assigned_op_ids:
                continue
            try:
                pt = op.processing_time_on(m_id)
            except KeyError:
                continue
            score = score_fn(job, op, m_id, instance, state)
            candidates.append((score, pt, job, op))

        if not candidates:
            continue

        # Sort by score descending, then processing time ascending
        candidates.sort(key=lambda x: (-x[0], x[1]))
        _, pt, job, op = candidates[0]
        decisions.append((job.job_id, op.op_id, m_id, start_lower))
        assigned_op_ids.add((job.job_id, op.op_id))

    return decisions


# ── Rule 1: EDD ─────────────────────────────────────────────────────────────

def edd_score(
    job: Job, op: Operation, machine_id: int, instance: SLISPInstance, state: ScheduleState
) -> float:
    """Lower deadline = higher priority (return negative for ascending sort)."""
    entity = instance.get_entity(job.entity_id)
    return float(-(entity.deadline - entity.transport_delay))


def edd_rule(
    instance: SLISPInstance, state: ScheduleState
) -> list[tuple[int, int, int, int]]:
    """Earliest-deadline-first dispatching rule."""
    ready = _collect_ready_ops(instance, state)
    if not ready:
        return []

    def score(job, op, mid, inst, st):
        entity = inst.get_entity(job.entity_id)
        pt = op.processing_time_on(mid)
        # Primary: effective production deadline, secondary: processing time.
        return float(-(entity.deadline - entity.transport_delay) * 10000 - pt)

    return _dispatch_on_idle_machines(instance, state, ready, score)


# ── Rule 2: Service-weighted deadline ────────────────────────────────────────

def swd_score(
    job: Job, op: Operation, machine_id: int, instance: SLISPInstance, state: ScheduleState
) -> float:
    """score = w_r * q_j / max(eps, d_r - D_lower_j(t))."""
    entity = instance.get_entity(job.entity_id)
    d_lower = optimistic_delivery_lower_bound(job, state, instance)
    slack = max(EPS, entity.deadline - d_lower)
    return entity.weight * job.quantity / slack


def swd_rule(
    instance: SLISPInstance, state: ScheduleState
) -> list[tuple[int, int, int, int]]:
    """Service-weighted deadline dispatching rule."""
    ready = _collect_ready_ops(instance, state)
    if not ready:
        return []
    return _dispatch_on_idle_machines(instance, state, ready, swd_score)


# ── Rule 3: Shortfall-greedy ─────────────────────────────────────────────────

def sfg_score(
    job: Job, op: Operation, machine_id: int, instance: SLISPInstance, state: ScheduleState
) -> float:
    """score = w_r * q_j / max(eps, w_lower_{j,B}(t)).
    Boosted if entity has positive unavoidable shortfall lower bound.
    """
    entity = instance.get_entity(job.entity_id)
    pool_B = {m.machine_id for m in instance.machines}
    w_lower = unavoidable_pool_workload(job, pool_B, state)
    base = max(EPS, w_lower)
    score = entity.weight * job.quantity / base

    # Boost if entity has positive unavoidable shortfall
    u_lower = unavoidable_shortfall_lower_bound(
        job.entity_id, pool_B, state, instance
    )
    if u_lower > 0:
        score *= 2.0

    return score


def sfg_rule(
    instance: SLISPInstance, state: ScheduleState
) -> list[tuple[int, int, int, int]]:
    """Shortfall-greedy dispatching rule."""
    ready = _collect_ready_ops(instance, state)
    if not ready:
        return []
    return _dispatch_on_idle_machines(instance, state, ready, sfg_score)
