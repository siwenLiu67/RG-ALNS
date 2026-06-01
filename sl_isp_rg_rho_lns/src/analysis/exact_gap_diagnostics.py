"""Diagnostics for explaining the gap between exact and heuristic schedules."""

from collections import Counter

from ..core.dataclasses import ScheduledOperation, SLISPInstance
from ..core.schedule_state import ScheduleState


def _completion_times(state: ScheduleState) -> dict[int, int]:
    return dict(state.completed_jobs)


def _job_tardiness(instance: SLISPInstance, completions: dict[int, int]) -> dict[int, int]:
    tardiness: dict[int, int] = {}
    for job in instance.jobs:
        c_time = completions.get(job.job_id)
        if c_time is None:
            continue
        entity = instance.get_entity(job.entity_id)
        tardiness[job.job_id] = max(0, c_time + entity.transport_delay - entity.deadline)
    return tardiness


def _on_time_jobs(instance: SLISPInstance, completions: dict[int, int]) -> set[int]:
    result: set[int] = set()
    for job in instance.jobs:
        c_time = completions.get(job.job_id)
        if c_time is None:
            continue
        entity = instance.get_entity(job.entity_id)
        if c_time + entity.transport_delay <= entity.deadline:
            result.add(job.job_id)
    return result


def _on_time_quantities(
    instance: SLISPInstance,
    on_time_jobs: set[int],
) -> dict[int, int]:
    quantities = {entity.entity_id: 0 for entity in instance.entities}
    for job in instance.jobs:
        if job.job_id in on_time_jobs:
            quantities[job.entity_id] += job.quantity
    return quantities


def _shortfalls(
    instance: SLISPInstance,
    on_time_qty: dict[int, int],
) -> dict[int, float]:
    return {
        entity.entity_id: max(
            0.0,
            entity.min_fulfillment - on_time_qty.get(entity.entity_id, 0),
        )
        for entity in instance.entities
    }


def _wasted_on_time_quantity(
    instance: SLISPInstance,
    on_time_qty: dict[int, int],
) -> dict[int, float]:
    return {
        entity.entity_id: max(
            0.0,
            on_time_qty.get(entity.entity_id, 0) - entity.min_fulfillment,
        )
        for entity in instance.entities
    }


def _machine_slots(state: ScheduleState) -> dict[int, list[ScheduledOperation]]:
    slots: dict[int, list[ScheduledOperation]] = {}
    for sop in state.scheduled_operations:
        slots.setdefault(sop.machine_id, []).append(sop)
    for machine_id in slots:
        slots[machine_id].sort(
            key=lambda op: (op.start_time, op.end_time, op.job_id, op.op_id)
        )
    return slots


def _neighbor_blockers(
    state: ScheduleState,
    target_jobs: set[int],
    max_predecessors: int = 2,
    max_successors: int = 1,
) -> dict[int, list[int]]:
    """Return nearby same-machine jobs around each target job in a schedule."""
    blockers: dict[int, Counter[int]] = {jid: Counter() for jid in target_jobs}
    slots_by_machine = _machine_slots(state)
    for slots in slots_by_machine.values():
        for idx, sop in enumerate(slots):
            if sop.job_id not in target_jobs:
                continue
            start_idx = max(0, idx - max_predecessors)
            end_idx = min(len(slots), idx + max_successors + 1)
            for n_idx in range(start_idx, end_idx):
                if n_idx == idx:
                    continue
                neighbor = slots[n_idx]
                if neighbor.job_id == sop.job_id:
                    continue
                blockers[sop.job_id][neighbor.job_id] += 1
    return {
        jid: [
            blocker_jid
            for blocker_jid, _count in counter.most_common()
        ]
        for jid, counter in blockers.items()
    }


def diagnose_exact_gap(
    instance: SLISPInstance,
    exact_state: ScheduleState,
    heuristic_state: ScheduleState,
) -> dict:
    """Explain where a heuristic schedule differs from an exact reference.

    The returned dictionary is intentionally JSON-friendly so experiments can
    persist it directly.  It highlights service-cover mismatches, tardiness
    deltas, wasted on-time quantity, and same-machine neighbors that may be
    blocking jobs that exact keeps on time but the heuristic misses.
    """
    exact_completion = _completion_times(exact_state)
    heuristic_completion = _completion_times(heuristic_state)
    exact_on_time = _on_time_jobs(instance, exact_completion)
    heuristic_on_time = _on_time_jobs(instance, heuristic_completion)
    exact_qty = _on_time_quantities(instance, exact_on_time)
    heuristic_qty = _on_time_quantities(instance, heuristic_on_time)
    exact_tardiness = _job_tardiness(instance, exact_completion)
    heuristic_tardiness = _job_tardiness(instance, heuristic_completion)

    exact_only_on_time = sorted(exact_on_time - heuristic_on_time)
    heuristic_only_on_time = sorted(heuristic_on_time - exact_on_time)
    tardiness_delta = {
        job.job_id: heuristic_tardiness.get(job.job_id, 0)
        - exact_tardiness.get(job.job_id, 0)
        for job in instance.jobs
        if heuristic_tardiness.get(job.job_id, 0)
        != exact_tardiness.get(job.job_id, 0)
    }

    return {
        "exact_only_on_time_jobs": exact_only_on_time,
        "heuristic_only_on_time_jobs": heuristic_only_on_time,
        "exact_on_time_quantity": exact_qty,
        "heuristic_on_time_quantity": heuristic_qty,
        "exact_shortfall": _shortfalls(instance, exact_qty),
        "heuristic_shortfall": _shortfalls(instance, heuristic_qty),
        "exact_wasted_on_time_quantity": _wasted_on_time_quantity(instance, exact_qty),
        "heuristic_wasted_on_time_quantity": _wasted_on_time_quantity(
            instance, heuristic_qty
        ),
        "per_job_tardiness_delta_heuristic_minus_exact": tardiness_delta,
        "heuristic_blockers_for_exact_only_on_time_jobs": _neighbor_blockers(
            heuristic_state,
            set(exact_only_on_time),
        ),
    }
