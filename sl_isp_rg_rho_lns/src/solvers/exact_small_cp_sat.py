"""Exact CP-SAT reference model for small SL-ISP instances.

The model is the integer CP-SAT counterpart of the manuscript MILP:
operation-to-machine assignment, non-preemptive machine capacity, job
precedence, release times, delivery tardiness, and entity-level service
shortfall are optimized under the original objective.
"""

from dataclasses import dataclass
from fractions import Fraction
from math import lcm

from ortools.sat.python import cp_model

from ..core.dataclasses import ScheduledOperation, SLISPInstance
from ..core.objective import ObjectiveResult, compute_objective
from ..core.schedule_state import ScheduleState


@dataclass
class ExactSolveResult:
    """Result returned by the exact small-instance CP-SAT solver."""

    status: str
    objective_value: float | None
    best_bound: float | None
    schedule_state: ScheduleState | None
    objective_result: ObjectiveResult | None
    scheduled_operations: list[ScheduledOperation]
    wall_time_s: float


def _as_fraction(value: float | int) -> Fraction:
    return Fraction(str(value)).limit_denominator(1_000_000)


def _safe_horizon(instance: SLISPInstance) -> int:
    """A conservative finite horizon for starts, completions, and deliveries."""
    max_release = max((job.release_time for job in instance.jobs), default=0)
    total_work = 0
    for job in instance.jobs:
        for op in job.operations:
            total_work += max(alt.processing_time for alt in op.alternatives)
    max_tau = max((entity.transport_delay for entity in instance.entities), default=0)
    max_deadline = max((entity.deadline for entity in instance.entities), default=0)
    return max(1, max_release + total_work + max_tau + max_deadline + 1)


def _quantity_scale(instance: SLISPInstance) -> int:
    """Scale service quantities so rho * Q is represented exactly as an int."""
    scale = 1
    for entity in instance.entities:
        scale = lcm(scale, _as_fraction(entity.min_fulfillment).denominator)
    return scale


def solve_exact_small_cp_sat(
    instance: SLISPInstance,
    time_limit_s: float | None = 30.0,
    num_workers: int = 1,
    log_search_progress: bool = False,
) -> ExactSolveResult:
    """Solve a fully revealed SL-ISP instance exactly with CP-SAT.

    This is intended for small validation instances.  The on-time indicator is
    reified in both directions: z_j=1 iff D_j <= d_{g(j)} for integer times.
    Service shortfall uses the continuous service threshold from
    ServiceEntity.min_fulfillment, not a truncated integer approximation.
    """
    model = cp_model.CpModel()
    horizon = _safe_horizon(instance)

    start: dict[tuple[int, int], cp_model.IntVar] = {}
    end: dict[tuple[int, int], cp_model.IntVar] = {}
    assign: dict[tuple[int, int, int], cp_model.IntVar] = {}
    machine_intervals: dict[int, list[cp_model.IntervalVar]] = {
        machine.machine_id: [] for machine in instance.machines
    }

    for job in instance.jobs:
        for op in job.operations:
            op_key = (job.job_id, op.op_id)
            start[op_key] = model.NewIntVar(0, horizon, f"S_j{job.job_id}_o{op.op_id}")
            end[op_key] = model.NewIntVar(0, horizon, f"E_j{job.job_id}_o{op.op_id}")

            alt_bools = []
            for alt in op.alternatives:
                x = model.NewBoolVar(
                    f"X_j{job.job_id}_o{op.op_id}_m{alt.machine_id}"
                )
                alt_end = model.NewIntVar(
                    0, horizon, f"E_j{job.job_id}_o{op.op_id}_m{alt.machine_id}"
                )
                interval = model.NewOptionalIntervalVar(
                    start[op_key],
                    alt.processing_time,
                    alt_end,
                    x,
                    f"I_j{job.job_id}_o{op.op_id}_m{alt.machine_id}",
                )
                model.Add(end[op_key] == alt_end).OnlyEnforceIf(x)
                assign[(job.job_id, op.op_id, alt.machine_id)] = x
                alt_bools.append(x)
                machine_intervals[alt.machine_id].append(interval)

            model.AddExactlyOne(alt_bools)

    for intervals in machine_intervals.values():
        if intervals:
            model.AddNoOverlap(intervals)

    for job in instance.jobs:
        first_key = (job.job_id, job.operations[0].op_id)
        model.Add(start[first_key] >= job.release_time)
        for prev_op, next_op in zip(job.operations, job.operations[1:]):
            model.Add(
                start[(job.job_id, next_op.op_id)] >= end[(job.job_id, prev_op.op_id)]
            )

    completion: dict[int, cp_model.IntVar] = {}
    delivery: dict[int, cp_model.IntVar] = {}
    tardiness: dict[int, cp_model.IntVar] = {}
    on_time: dict[int, cp_model.IntVar] = {}

    for job in instance.jobs:
        entity = instance.get_entity(job.entity_id)
        last_key = (job.job_id, job.operations[-1].op_id)
        completion[job.job_id] = model.NewIntVar(0, horizon, f"C_j{job.job_id}")
        delivery[job.job_id] = model.NewIntVar(0, horizon, f"D_j{job.job_id}")
        tardiness[job.job_id] = model.NewIntVar(0, horizon, f"T_j{job.job_id}")
        on_time[job.job_id] = model.NewBoolVar(f"z_j{job.job_id}")

        model.Add(completion[job.job_id] == end[last_key])
        model.Add(delivery[job.job_id] == completion[job.job_id] + entity.transport_delay)
        model.Add(tardiness[job.job_id] >= delivery[job.job_id] - entity.deadline)
        model.Add(tardiness[job.job_id] >= 0)

        model.Add(delivery[job.job_id] <= entity.deadline).OnlyEnforceIf(
            on_time[job.job_id]
        )
        model.Add(delivery[job.job_id] >= entity.deadline + 1).OnlyEnforceIf(
            on_time[job.job_id].Not()
        )

    q_scale = _quantity_scale(instance)
    shortfall_scaled: dict[int, cp_model.IntVar] = {}
    for entity in instance.entities:
        q_min_scaled = int(_as_fraction(entity.min_fulfillment) * q_scale)
        max_shortfall = max(0, q_min_scaled)
        u = model.NewIntVar(0, max_shortfall, f"U_scaled_r{entity.entity_id}")
        on_time_qty_scaled = sum(
            job.quantity * q_scale * on_time[job.job_id]
            for job in instance.jobs
            if job.entity_id == entity.entity_id
        )
        model.Add(u >= q_min_scaled - on_time_qty_scaled)
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
        int(alpha * obj_scale) * tardiness[job.job_id] for job in instance.jobs
    ]
    objective_terms.extend(
        int(entity_shortfall_coeff[entity.entity_id] * obj_scale)
        * shortfall_scaled[entity.entity_id]
        for entity in instance.entities
    )
    model.Minimize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = num_workers
    solver.parameters.log_search_progress = log_search_progress
    if time_limit_s is not None:
        solver.parameters.max_time_in_seconds = time_limit_s

    status_code = solver.Solve(model)
    status = solver.StatusName(status_code)

    if status_code not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return ExactSolveResult(
            status=status,
            objective_value=None,
            best_bound=None,
            schedule_state=None,
            objective_result=None,
            scheduled_operations=[],
            wall_time_s=solver.WallTime(),
        )

    state = ScheduleState()
    for machine in instance.machines:
        state.machine_available_times[machine.machine_id] = 0

    scheduled_ops: list[ScheduledOperation] = []
    for job in instance.jobs:
        for op in job.operations:
            selected_machine = None
            for alt in op.alternatives:
                if solver.BooleanValue(assign[(job.job_id, op.op_id, alt.machine_id)]):
                    selected_machine = alt.machine_id
                    break
            if selected_machine is None:
                raise RuntimeError(f"No selected machine for job {job.job_id}, op {op.op_id}")
            sop = ScheduledOperation(
                job_id=job.job_id,
                op_id=op.op_id,
                machine_id=selected_machine,
                start_time=solver.Value(start[(job.job_id, op.op_id)]),
                end_time=solver.Value(end[(job.job_id, op.op_id)]),
            )
            scheduled_ops.append(sop)
            state.scheduled_operations.append(sop)
            state.completed_operations.add((job.job_id, op.op_id))
            state.last_completed_op_index[job.job_id] = op.sequence_index
            state.machine_available_times[selected_machine] = max(
                state.machine_available_times[selected_machine], sop.end_time
            )

        c_j = solver.Value(completion[job.job_id])
        state.completed_jobs[job.job_id] = c_j
        entity = instance.get_entity(job.entity_id)
        if c_j + entity.transport_delay <= entity.deadline:
            state.delivered_on_time_jobs.add(job.job_id)

    scheduled_ops.sort(key=lambda op: (op.start_time, op.machine_id, op.job_id, op.op_id))
    state.scheduled_operations.sort(
        key=lambda op: (op.start_time, op.machine_id, op.job_id, op.op_id)
    )
    state.current_time = max(state.completed_jobs.values(), default=0)
    objective_result = compute_objective(instance, state)

    return ExactSolveResult(
        status=status,
        objective_value=objective_result.Z,
        best_bound=solver.BestObjectiveBound() / obj_scale,
        schedule_state=state,
        objective_result=objective_result,
        scheduled_operations=scheduled_ops,
        wall_time_s=solver.WallTime(),
    )
