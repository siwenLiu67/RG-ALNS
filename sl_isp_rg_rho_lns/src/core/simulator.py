"""Event-driven scheduling simulator for the SL-ISP problem."""

from collections.abc import Callable

from .dataclasses import Job, Operation, ScheduledOperation, SLISPInstance
from .event_queue import Event, EventQueue, EventType
from .objective import ObjectiveResult, compute_objective
from .schedule_state import ScheduleState

# Scheduling algorithm signature:
#   (instance, state) -> list of (job_id, op_id, machine_id, start_time)
SchedulingAlgorithm = Callable[
    [SLISPInstance, ScheduleState], list[tuple[int, int, int, int]]
]


def _edf_dispatching_rule(
    instance: SLISPInstance, state: ScheduleState
) -> list[tuple[int, int, int, int]]:
    """Earliest-effective-deadline-first dispatching rule.

    For each idle machine, pick the ready operation whose entity has the
    earliest production-side cutoff.  Tie-break by shortest processing time.
    """
    decisions: list[tuple[int, int, int, int]] = []

    # Collect ready operations
    ready_ops: list[tuple[Job, Operation]] = []
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
        ready_ops.append((job, op))

    if not ready_ops:
        return decisions

    # For each idle machine, select the best ready operation
    idle_machines = [
        m.machine_id
        for m in instance.machines
        if state.is_machine_idle(m.machine_id)
    ]
    assigned_ops: set[tuple[int, int]] = set()

    for m_id in idle_machines:
        avail = state.machine_available_times.get(m_id, 0)
        start_lower = max(state.current_time, avail)

        # Find eligible ready operations
        candidates: list[tuple[Job, Operation, int]] = []  # (job, op, proc_time)
        for job, op in ready_ops:
            if (job.job_id, op.op_id) in assigned_ops:
                continue
            try:
                pt = op.processing_time_on(m_id)
            except KeyError:
                continue
            candidates.append((job, op, pt))

        if not candidates:
            continue

        # Sort by (entity deadline, processing time)
        def sort_key(item: tuple[Job, Operation, int]) -> tuple[int, int]:
            job, _op, pt = item
            entity = instance.get_entity(job.entity_id)
            return (entity.deadline - entity.transport_delay, pt)

        candidates.sort(key=sort_key)
        job, op, pt = candidates[0]

        decisions.append((job.job_id, op.op_id, m_id, start_lower))
        assigned_ops.add((job.job_id, op.op_id))

    return decisions


def run_simulation(
    instance: SLISPInstance,
    algorithm: SchedulingAlgorithm | None = None,
) -> tuple[ScheduleState, ObjectiveResult]:
    """Run the event-driven scheduling simulation on the given instance.

    If no algorithm is provided, the built-in EDF dispatching rule is used.

    Returns the final ScheduleState and the computed ObjectiveResult.
    """
    if algorithm is None:
        algorithm = _edf_dispatching_rule

    state = ScheduleState()

    # Initialize machine available times to 0
    for m in instance.machines:
        state.machine_available_times[m.machine_id] = 0

    # Seed the event queue with job arrival events
    for job in instance.jobs:
        state.event_queue.push(
            Event(
                time=job.release_time,
                event_type=EventType.JOB_ARRIVAL,
                job_id=job.job_id,
            )
        )

    # Track which jobs have been released (arrived)
    arrived_jobs: set[int] = set()

    def process_event(event: Event) -> None:
        if event.event_type == EventType.JOB_ARRIVAL:
            arrived_jobs.add(event.job_id)

        elif event.event_type == EventType.OP_COMPLETION:
            job = instance.get_job(event.job_id)
            op = _find_op_by_id(job, event.op_id)

            state.mark_operation_completed(event.job_id, event.op_id, op.sequence_index)

            # Check if this was the job's last operation
            if op.sequence_index == job.num_operations - 1:
                state.mark_job_completed(event.job_id, event.time)

                # Check if delivered on time
                entity = instance.get_entity(job.entity_id)
                delivery_time = event.time + entity.transport_delay
                if delivery_time <= entity.deadline:
                    state.mark_delivered_on_time(event.job_id)

    while state.event_queue:
        event = state.event_queue.pop()
        state.current_time = event.time
        process_event(event)

        while state.event_queue:
            next_event = state.event_queue.peek()
            if next_event is None or next_event.time != state.current_time:
                break
            process_event(state.event_queue.pop())

        # After processing all events at this timestamp, run the scheduling algorithm
        _dispatch_cycle(instance, state, algorithm)

    # After all events processed, compute the objective
    result = compute_objective(instance, state)
    return state, result


def _find_op_by_id(job: Job, op_id: int) -> Operation:
    """Find an operation by ID within a job."""
    for op in job.operations:
        if op.op_id == op_id:
            return op
    raise KeyError(f"Operation {op_id} not found in job {job.job_id}")


def _validate_decision(
    instance: SLISPInstance,
    state: ScheduleState,
    decision: tuple[int, int, int, int],
    assigned_ops: set[tuple[int, int]],
    assigned_machines: set[int],
) -> Operation:
    """Validate a dispatch decision before mutating simulator state."""
    job_id, op_id, machine_id, start_time = decision
    try:
        job = instance.get_job(job_id)
        op = _find_op_by_id(job, op_id)
    except KeyError as exc:
        raise ValueError(f"Invalid scheduling decision {decision}: {exc}") from exc

    op_key = (job_id, op_id)
    if op_key in assigned_ops:
        raise ValueError(f"Duplicate operation decision in one dispatch cycle: {decision}")
    if machine_id in assigned_machines:
        raise ValueError(f"Duplicate machine decision in one dispatch cycle: {decision}")
    if state.is_job_completed(job_id):
        raise ValueError(f"Decision schedules completed job {job_id}")
    if state.is_operation_completed(job_id, op_id):
        raise ValueError(f"Decision schedules completed operation {(job_id, op_id)}")
    if state.is_operation_ongoing(job_id, op_id):
        raise ValueError(f"Decision schedules ongoing operation {(job_id, op_id)}")
    if job.release_time > state.current_time:
        raise ValueError(f"Decision schedules unreleased job {job_id} at time {state.current_time}")
    if start_time != state.current_time:
        raise ValueError(
            f"Decision start time {start_time} must equal current time {state.current_time}"
        )
    if not state.is_machine_idle(machine_id):
        raise ValueError(f"Decision schedules busy machine {machine_id}")
    next_idx = state.next_op_index_for_job(job_id)
    if op.sequence_index != next_idx:
        raise ValueError(
            f"Decision schedules operation {(job_id, op_id)} but next sequence is {next_idx}"
        )
    try:
        op.processing_time_on(machine_id)
    except KeyError as exc:
        raise ValueError(f"Machine {machine_id} is not eligible for operation {(job_id, op_id)}") from exc
    return op


def _dispatch_cycle(
    instance: SLISPInstance,
    state: ScheduleState,
    algorithm: SchedulingAlgorithm,
) -> None:
    """Run scheduling algorithm and post OP_COMPLETION events for new assignments.

    Repeats while the algorithm continues to produce scheduling decisions,
    since completing one round of dispatch may free up decisions for more ops.
    """
    MAX_ITERATIONS = 10_000  # safety bound

    for _ in range(MAX_ITERATIONS):
        decisions = algorithm(instance, state)
        if not decisions:
            break

        assigned_ops: set[tuple[int, int]] = set()
        assigned_machines: set[int] = set()
        for job_id, op_id, machine_id, start_time in decisions:
            op = _validate_decision(
                instance,
                state,
                (job_id, op_id, machine_id, start_time),
                assigned_ops,
                assigned_machines,
            )
            proc_time = op.processing_time_on(machine_id)
            end_time = start_time + proc_time
            assigned_ops.add((job_id, op_id))
            assigned_machines.add(machine_id)

            state.mark_operation_started(
                job_id=job_id,
                op_id=op_id,
                machine_id=machine_id,
                start_time=start_time,
                end_time=end_time,
            )

            state.event_queue.push(
                Event(
                    time=end_time,
                    event_type=EventType.OP_COMPLETION,
                    job_id=job_id,
                    op_id=op_id,
                    machine_id=machine_id,
                )
            )
