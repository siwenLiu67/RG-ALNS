"""Tests for online algorithm visibility in the event-driven simulator."""

from src.core.dataclasses import (
    Job,
    Machine,
    Operation,
    OperationAlternative,
    ServiceEntity,
    SLISPInstance,
)
from src.core.event_queue import EventType
from src.core.online import OnlineProblemView
from src.core.schedule_state import ScheduleState
from src.core.simulator import run_simulation
from src.algorithms.rg_rho_lns_fast import (
    FastSchedule,
    _classify_entities_and_intensity,
    _fast_eval_wsf,
)
from src.recoverability.shortfall_bounds import current_information_shortfall_risk


def make_two_arrival_instance() -> SLISPInstance:
    entities = [
        ServiceEntity(
            entity_id=0,
            deadline=50,
            rho=1.0,
            weight=1.0,
            total_quantity=12,
            transport_delay=0,
        )
    ]
    machines = [Machine(machine_id=0)]
    jobs = [
        Job(
            job_id=0,
            entity_id=0,
            release_time=0,
            quantity=5,
            operations=[
                Operation(
                    op_id=0,
                    job_id=0,
                    sequence_index=0,
                    alternatives=[OperationAlternative(machine_id=0, processing_time=1)],
                )
            ],
        ),
        Job(
            job_id=1,
            entity_id=0,
            release_time=10,
            quantity=7,
            operations=[
                Operation(
                    op_id=100,
                    job_id=1,
                    sequence_index=0,
                    alternatives=[OperationAlternative(machine_id=0, processing_time=1)],
                )
            ],
        ),
    ]
    return SLISPInstance(
        jobs=jobs,
        entities=entities,
        machines=machines,
        alpha=1.0,
        beta=1.0,
    )


def test_online_problem_view_exposes_instance_like_read_api():
    instance = make_two_arrival_instance()
    future_quantity = {0: 7}

    view = OnlineProblemView(
        jobs=[instance.get_job(0)],
        entities=instance.entities,
        machines=instance.machines,
        alpha=instance.alpha,
        beta=instance.beta,
        entity_future_quantity=future_quantity,
    )
    future_quantity[0] = 0

    assert view.num_jobs == 1
    assert view.num_machines == 1
    assert view.num_entities == 1
    assert view.get_job(0).quantity == 5
    assert view.get_entity(0).min_fulfillment == 12
    assert [job.job_id for job in view.jobs_of_entity(0)] == [0]
    assert view.entity_future_quantity == {0: 7}


def test_current_information_shortfall_risk_uses_known_future_quantity_buffer():
    instance = make_two_arrival_instance()
    state = ScheduleState()
    state.current_time = 0
    state.machine_available_times[0] = 0
    pool_b = {0}

    view_with_future = OnlineProblemView(
        jobs=[instance.get_job(0)],
        entities=instance.entities,
        machines=instance.machines,
        alpha=instance.alpha,
        beta=instance.beta,
        entity_future_quantity={0: 7},
    )
    view_without_future = OnlineProblemView(
        jobs=[instance.get_job(0)],
        entities=instance.entities,
        machines=instance.machines,
        alpha=instance.alpha,
        beta=instance.beta,
        entity_future_quantity={0: 0},
    )

    assert current_information_shortfall_risk(0, pool_b, state, view_with_future) == 0
    assert current_information_shortfall_risk(0, pool_b, state, view_without_future) == 7


def test_entity_classification_treats_known_future_quantity_as_arrival_buffer():
    instance = make_two_arrival_instance()
    state = ScheduleState()
    state.current_time = 0
    state.machine_available_times[0] = 0
    view = OnlineProblemView(
        jobs=[instance.get_job(0)],
        entities=instance.entities,
        machines=instance.machines,
        alpha=instance.alpha,
        beta=instance.beta,
        entity_future_quantity={0: 7},
    )

    classifications, intensity = _classify_entities_and_intensity(view, state, {0})

    assert classifications[0]["class"] == "arrival_dependent_recoverable"
    assert classifications[0]["q_future"] == 7
    assert intensity == 0.4


def test_projected_wsf_uses_known_future_quantity_buffer_in_online_view():
    instance = make_two_arrival_instance()
    state = ScheduleState()
    state.current_time = 0
    state.machine_available_times[0] = 0
    schedule = FastSchedule()
    schedule.add_op(job_id=0, op_id=0, machine_id=0, start=0, end=1)

    view_with_future = OnlineProblemView(
        jobs=[instance.get_job(0)],
        entities=instance.entities,
        machines=instance.machines,
        alpha=instance.alpha,
        beta=instance.beta,
        entity_future_quantity={0: 7},
    )
    view_without_future = OnlineProblemView(
        jobs=[instance.get_job(0)],
        entities=instance.entities,
        machines=instance.machines,
        alpha=instance.alpha,
        beta=instance.beta,
        entity_future_quantity={0: 0},
    )

    assert _fast_eval_wsf(schedule, view_with_future, state) == 0.0
    assert _fast_eval_wsf(schedule, view_without_future, state) == 7.0


def test_online_simulation_hides_unreleased_jobs_and_tracks_future_quantity():
    instance = make_two_arrival_instance()
    snapshots: list[tuple[int, list[int], dict[int, int]]] = []

    def visible_greedy_algorithm(problem, state: ScheduleState):
        snapshots.append(
            (
                state.current_time,
                [job.job_id for job in problem.jobs],
                dict(problem.entity_future_quantity),
            )
        )

        decisions = []
        assigned_ops: set[tuple[int, int]] = set()
        assigned_machines: set[int] = set()
        for machine in problem.machines:
            if not state.is_machine_idle(machine.machine_id):
                continue
            for job in sorted(problem.jobs, key=lambda item: item.job_id):
                if state.is_job_completed(job.job_id) or job.release_time > state.current_time:
                    continue
                next_idx = state.next_op_index_for_job(job.job_id)
                if next_idx >= job.num_operations:
                    continue
                op = job.operation_at(next_idx)
                op_key = (job.job_id, op.op_id)
                if op_key in assigned_ops or machine.machine_id in assigned_machines:
                    continue
                if state.is_operation_completed(job.job_id, op.op_id):
                    continue
                if state.is_operation_ongoing(job.job_id, op.op_id):
                    continue
                try:
                    op.processing_time_on(machine.machine_id)
                except KeyError:
                    continue
                decisions.append((job.job_id, op.op_id, machine.machine_id, state.current_time))
                assigned_ops.add(op_key)
                assigned_machines.add(machine.machine_id)
                break
        return decisions

    _state, result = run_simulation(
        instance,
        visible_greedy_algorithm,
        online_visibility=True,
    )

    assert all(1 not in job_ids for time, job_ids, _future in snapshots if time < 10)
    assert (0, [0], {0: 7}) in snapshots
    assert any(time == 10 and job_ids == [0, 1] and future == {0: 0}
               for time, job_ids, future in snapshots)
    assert result.Z == 0.0


def test_online_simulation_hides_future_arrival_events_from_algorithm_state():
    instance = make_two_arrival_instance()
    observed_next_events: list[EventType | None] = []

    def inspecting_greedy_algorithm(problem, state: ScheduleState):
        next_event = state.event_queue.peek()
        observed_next_events.append(None if next_event is None else next_event.event_type)

        for machine in problem.machines:
            if not state.is_machine_idle(machine.machine_id):
                continue
            for job in sorted(problem.jobs, key=lambda item: item.job_id):
                if state.is_job_completed(job.job_id) or job.release_time > state.current_time:
                    continue
                next_idx = state.next_op_index_for_job(job.job_id)
                if next_idx >= job.num_operations:
                    continue
                op = job.operation_at(next_idx)
                if state.is_operation_completed(job.job_id, op.op_id):
                    continue
                if state.is_operation_ongoing(job.job_id, op.op_id):
                    continue
                try:
                    op.processing_time_on(machine.machine_id)
                except KeyError:
                    continue
                return [(job.job_id, op.op_id, machine.machine_id, state.current_time)]
        return []

    run_simulation(
        instance,
        inspecting_greedy_algorithm,
        online_visibility=True,
    )

    assert EventType.JOB_ARRIVAL not in observed_next_events
