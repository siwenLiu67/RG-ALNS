"""Recoverability-guided exact local repair for SL-ISP schedules.

This solver is intentionally not a global fallback.  It reoptimizes only a
small active job set while all other projected operations are fixed as machine
reservations.  The calling heuristic decides the active set and accepts the
repair only if the full projected objective improves.
"""

from dataclasses import dataclass
from fractions import Fraction
from math import lcm

from ortools.sat.python import cp_model

from ..core.dataclasses import ScheduledOperation, SLISPInstance
from ..core.schedule_state import ScheduleState


@dataclass
class ExactLocalRepairResult:
    """Result returned by the local exact repair model."""

    status: str
    objective_value: float | None
    best_bound: float | None
    scheduled_operations: list[ScheduledOperation]
    active_job_ids: set[int]
    wall_time_s: float


def _as_fraction(value: float | int) -> Fraction:
    return Fraction(str(value)).limit_denominator(1_000_000)


def _quantity_scale(instance: SLISPInstance) -> int:
    scale = 1
    for entity in instance.entities:
        scale = lcm(scale, _as_fraction(entity.min_fulfillment).denominator)
    return scale


def _previous_completed_end(job_id: int, prev_op_id: int, state: ScheduleState) -> int:
    end_time = state.current_time
    for sop in state.scheduled_operations:
        if sop.job_id == job_id and sop.op_id == prev_op_id:
            end_time = max(end_time, sop.end_time)
    return end_time


def _repair_horizon(
    instance: SLISPInstance,
    state: ScheduleState,
    active_job_ids: set[int],
    fixed_machine_slots: dict[int, list[tuple[int, int, int, int]]],
) -> int:
    fixed_end = max(
        (end for slots in fixed_machine_slots.values() for *_prefix, end in slots),
        default=state.current_time,
    )
    active_work = 0
    max_release = state.current_time
    for jid in active_job_ids:
        job = instance.get_job(jid)
        max_release = max(max_release, job.release_time)
        start_seq = state.next_op_index_for_job(jid)
        for seq in range(start_seq, job.num_operations):
            op = job.operation_at(seq)
            active_work += max(alt.processing_time for alt in op.alternatives)
    max_deadline = max((entity.deadline for entity in instance.entities), default=0)
    max_tau = max((entity.transport_delay for entity in instance.entities), default=0)
    return max(1, max(fixed_end, max_release, max_deadline) + active_work + max_tau + 1)


def solve_exact_local_repair_cp_sat(
    instance: SLISPInstance,
    state: ScheduleState,
    active_job_ids: set[int],
    fixed_machine_slots: dict[int, list[tuple[int, int, int, int]]],
    fixed_completion_times: dict[int, int],
    time_limit_s: float = 1.0,
    num_workers: int = 1,
    log_search_progress: bool = False,
) -> ExactLocalRepairResult:
    """Reoptimize a small active job set around fixed incumbent reservations."""

    active_job_ids = {
        jid for jid in active_job_ids
        if not state.is_job_completed(jid)
        and state.next_op_index_for_job(jid) < instance.get_job(jid).num_operations
    }
    if not active_job_ids:
        return ExactLocalRepairResult(
            status="EMPTY",
            objective_value=None,
            best_bound=None,
            scheduled_operations=[],
            active_job_ids=set(),
            wall_time_s=0.0,
        )

    model = cp_model.CpModel()
    horizon = _repair_horizon(instance, state, active_job_ids, fixed_machine_slots)

    machine_intervals: dict[int, list[cp_model.IntervalVar]] = {
        machine.machine_id: [] for machine in instance.machines
    }
    for machine_id, slots in fixed_machine_slots.items():
        machine_intervals.setdefault(machine_id, [])
        for idx, (job_id, op_id, start_time, end_time) in enumerate(slots):
            if end_time <= start_time:
                continue
            interval = model.NewFixedSizeIntervalVar(
                start_time,
                end_time - start_time,
                f"F_j{job_id}_o{op_id}_m{machine_id}_{idx}",
            )
            machine_intervals[machine_id].append(interval)

    start: dict[tuple[int, int], cp_model.IntVar] = {}
    end: dict[tuple[int, int], cp_model.IntVar] = {}
    assign: dict[tuple[int, int, int], cp_model.IntVar] = {}

    for jid in sorted(active_job_ids):
        job = instance.get_job(jid)
        start_seq = state.next_op_index_for_job(jid)
        for seq in range(start_seq, job.num_operations):
            op = job.operation_at(seq)
            op_key = (jid, op.op_id)
            start[op_key] = model.NewIntVar(state.current_time, horizon, f"S_j{jid}_o{op.op_id}")
            end[op_key] = model.NewIntVar(state.current_time, horizon, f"E_j{jid}_o{op.op_id}")
            alt_bools = []
            for alt in op.alternatives:
                x = model.NewBoolVar(f"X_j{jid}_o{op.op_id}_m{alt.machine_id}")
                alt_end = model.NewIntVar(state.current_time, horizon, f"E_j{jid}_o{op.op_id}_m{alt.machine_id}")
                interval = model.NewOptionalIntervalVar(
                    start[op_key],
                    alt.processing_time,
                    alt_end,
                    x,
                    f"I_j{jid}_o{op.op_id}_m{alt.machine_id}",
                )
                model.Add(end[op_key] == alt_end).OnlyEnforceIf(x)
                assign[(jid, op.op_id, alt.machine_id)] = x
                alt_bools.append(x)
                machine_intervals.setdefault(alt.machine_id, []).append(interval)
            model.AddExactlyOne(alt_bools)

        first_op = job.operation_at(start_seq)
        first_ready = max(state.current_time, job.release_time)
        if start_seq > 0:
            prev_op = job.operation_at(start_seq - 1)
            first_ready = max(first_ready, _previous_completed_end(jid, prev_op.op_id, state))
        model.Add(start[(jid, first_op.op_id)] >= first_ready)

        for prev_seq in range(start_seq, job.num_operations - 1):
            prev_op = job.operation_at(prev_seq)
            next_op = job.operation_at(prev_seq + 1)
            model.Add(start[(jid, next_op.op_id)] >= end[(jid, prev_op.op_id)])

    for intervals in machine_intervals.values():
        if intervals:
            model.AddNoOverlap(intervals)

    completion: dict[int, cp_model.IntVar] = {}
    delivery: dict[int, cp_model.IntVar] = {}
    tardiness: dict[int, cp_model.IntVar] = {}
    on_time: dict[int, cp_model.IntVar] = {}

    for jid in sorted(active_job_ids):
        job = instance.get_job(jid)
        entity = instance.get_entity(job.entity_id)
        last_op = job.operations[-1]
        completion[jid] = model.NewIntVar(state.current_time, horizon, f"C_j{jid}")
        delivery[jid] = model.NewIntVar(state.current_time, horizon + entity.transport_delay, f"D_j{jid}")
        tardiness[jid] = model.NewIntVar(0, horizon + entity.transport_delay, f"T_j{jid}")
        on_time[jid] = model.NewBoolVar(f"z_j{jid}")

        model.Add(completion[jid] == end[(jid, last_op.op_id)])
        model.Add(delivery[jid] == completion[jid] + entity.transport_delay)
        model.Add(tardiness[jid] >= delivery[jid] - entity.deadline)
        model.Add(tardiness[jid] >= 0)
        model.Add(delivery[jid] <= entity.deadline).OnlyEnforceIf(on_time[jid])
        model.Add(delivery[jid] >= entity.deadline + 1).OnlyEnforceIf(on_time[jid].Not())

    q_scale = _quantity_scale(instance)
    shortfall_scaled: dict[int, cp_model.IntVar] = {}
    fixed_tardiness = 0
    fixed_on_time_qty_scaled: dict[int, int] = {entity.entity_id: 0 for entity in instance.entities}

    for job in instance.jobs:
        if job.job_id in active_job_ids:
            continue
        c_time = fixed_completion_times.get(job.job_id)
        if c_time is None:
            continue
        entity = instance.get_entity(job.entity_id)
        delivery_time = c_time + entity.transport_delay
        fixed_tardiness += max(0, delivery_time - entity.deadline)
        if delivery_time <= entity.deadline:
            fixed_on_time_qty_scaled[entity.entity_id] += job.quantity * q_scale

    for entity in instance.entities:
        q_min_scaled = int(_as_fraction(entity.min_fulfillment) * q_scale)
        active_qty_scaled = sum(
            job.quantity * q_scale * on_time[job.job_id]
            for job in instance.jobs
            if job.entity_id == entity.entity_id and job.job_id in active_job_ids
        )
        u = model.NewIntVar(0, max(0, q_min_scaled), f"U_scaled_r{entity.entity_id}")
        model.Add(
            u >= q_min_scaled
            - fixed_on_time_qty_scaled.get(entity.entity_id, 0)
            - active_qty_scaled
        )
        shortfall_scaled[entity.entity_id] = u

    alpha = _as_fraction(instance.alpha)
    beta = _as_fraction(instance.beta)
    objective_coeffs = [alpha]
    entity_shortfall_coeff: dict[int, Fraction] = {}
    for entity in instance.entities:
        coeff = beta * _as_fraction(entity.weight) / q_scale
        entity_shortfall_coeff[entity.entity_id] = coeff
        objective_coeffs.append(coeff)

    obj_scale = 1
    for coeff in objective_coeffs:
        obj_scale = lcm(obj_scale, coeff.denominator)

    objective_terms = [
        int(alpha * obj_scale) * tardiness[jid]
        for jid in sorted(active_job_ids)
    ]
    objective_terms.append(int(alpha * obj_scale) * fixed_tardiness)
    objective_terms.extend(
        int(entity_shortfall_coeff[entity.entity_id] * obj_scale)
        * shortfall_scaled[entity.entity_id]
        for entity in instance.entities
    )
    model.Minimize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = num_workers
    solver.parameters.log_search_progress = log_search_progress
    solver.parameters.max_time_in_seconds = time_limit_s

    status_code = solver.Solve(model)
    status = solver.StatusName(status_code)

    if status_code not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return ExactLocalRepairResult(
            status=status,
            objective_value=None,
            best_bound=None,
            scheduled_operations=[],
            active_job_ids=active_job_ids,
            wall_time_s=solver.WallTime(),
        )

    scheduled_ops: list[ScheduledOperation] = []
    for jid in sorted(active_job_ids):
        job = instance.get_job(jid)
        start_seq = state.next_op_index_for_job(jid)
        for seq in range(start_seq, job.num_operations):
            op = job.operation_at(seq)
            selected_machine = None
            for alt in op.alternatives:
                if solver.BooleanValue(assign[(jid, op.op_id, alt.machine_id)]):
                    selected_machine = alt.machine_id
                    break
            if selected_machine is None:
                raise RuntimeError(f"No selected machine for job {jid}, op {op.op_id}")
            scheduled_ops.append(
                ScheduledOperation(
                    job_id=jid,
                    op_id=op.op_id,
                    machine_id=selected_machine,
                    start_time=solver.Value(start[(jid, op.op_id)]),
                    end_time=solver.Value(end[(jid, op.op_id)]),
                )
            )

    scheduled_ops.sort(key=lambda op: (op.start_time, op.machine_id, op.job_id, op.op_id))
    return ExactLocalRepairResult(
        status=status,
        objective_value=solver.ObjectiveValue() / obj_scale,
        best_bound=solver.BestObjectiveBound() / obj_scale,
        scheduled_operations=scheduled_ops,
        active_job_ids=active_job_ids,
        wall_time_s=solver.WallTime(),
    )
