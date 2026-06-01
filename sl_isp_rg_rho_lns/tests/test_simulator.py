"""Tests for the event-driven simulator, schedule state, and objective."""

import pytest
from src.core.dataclasses import (
    Job,
    Machine,
    Operation,
    OperationAlternative,
    ScheduledOperation,
    ServiceEntity,
    SLISPInstance,
)
from src.core.schedule_state import ScheduleState
from src.core.event_queue import Event, EventQueue, EventType
from src.core.objective import ObjectiveResult, compute_objective
from src.core.simulator import run_simulation


# --- Tiny hand-built instance for testing ---

def make_tiny_instance(
    release_times: list[int] | None = None,
) -> SLISPInstance:
    """Create a minimal 2-job, 1-entity, 2-machine instance for testing.

    Job 0: entity 0, 1 op, eligible on machine 0 (pt=5)
    Job 1: entity 0, 1 op, eligible on machine 1 (pt=10)

    Entity: deadline=20, rho=1.0, weight=1.0, transport_delay=0
    """
    if release_times is None:
        release_times = [0, 0]

    entities = [
        ServiceEntity(
            entity_id=0,
            deadline=20,
            rho=1.0,
            weight=1.0,
            total_quantity=10 + 20,  # q0 + q1
            transport_delay=0,
        )
    ]

    machines = [Machine(machine_id=0), Machine(machine_id=1)]

    jobs = [
        Job(
            job_id=0,
            entity_id=0,
            release_time=release_times[0],
            quantity=10,
            operations=[
                Operation(
                    op_id=0,
                    job_id=0,
                    sequence_index=0,
                    alternatives=[OperationAlternative(machine_id=0, processing_time=5)],
                )
            ],
        ),
        Job(
            job_id=1,
            entity_id=0,
            release_time=release_times[1],
            quantity=20,
            operations=[
                Operation(
                    op_id=100,
                    job_id=1,
                    sequence_index=0,
                    alternatives=[OperationAlternative(machine_id=1, processing_time=10)],
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
        metadata={"test": True},
    )


def make_multi_op_instance() -> SLISPInstance:
    """Create a 2-job instance with 2 operations each.

    Job 0: op0 on m0 (pt=3), op1 on m0 or m1 (pt=4 or 5)
    Job 1: op100 on m1 (pt=6), op101 on m0 (pt=2)

    Entity: deadline=30, rho=1.0, weight=1.0, transport_delay=2
    """
    entities = [
        ServiceEntity(
            entity_id=0,
            deadline=30,
            rho=1.0,
            weight=1.0,
            total_quantity=15 + 25,
            transport_delay=2,
        )
    ]

    machines = [Machine(machine_id=0), Machine(machine_id=1)]

    jobs = [
        Job(
            job_id=0,
            entity_id=0,
            release_time=0,
            quantity=15,
            operations=[
                Operation(
                    op_id=0,
                    job_id=0,
                    sequence_index=0,
                    alternatives=[OperationAlternative(machine_id=0, processing_time=3)],
                ),
                Operation(
                    op_id=1,
                    job_id=0,
                    sequence_index=1,
                    alternatives=[
                        OperationAlternative(machine_id=0, processing_time=4),
                        OperationAlternative(machine_id=1, processing_time=5),
                    ],
                ),
            ],
        ),
        Job(
            job_id=1,
            entity_id=0,
            release_time=0,
            quantity=25,
            operations=[
                Operation(
                    op_id=100,
                    job_id=1,
                    sequence_index=0,
                    alternatives=[OperationAlternative(machine_id=1, processing_time=6)],
                ),
                Operation(
                    op_id=101,
                    job_id=1,
                    sequence_index=1,
                    alternatives=[OperationAlternative(machine_id=0, processing_time=2)],
                ),
            ],
        ),
    ]

    return SLISPInstance(
        jobs=jobs,
        entities=entities,
        machines=machines,
        alpha=1.0,
        beta=2.0,
    )


class TestEventQueue:
    def test_push_pop_order(self):
        eq = EventQueue()
        eq.push(Event(time=10, event_type=EventType.JOB_ARRIVAL, job_id=1))
        eq.push(Event(time=5, event_type=EventType.JOB_ARRIVAL, job_id=0))
        eq.push(Event(time=5, event_type=EventType.OP_COMPLETION, job_id=0, op_id=0, machine_id=0))

        # OP_COMPLETION should come before JOB_ARRIVAL at same time
        # due to enum ordering (OP_COMPLETION < JOB_ARRIVAL)
        e1 = eq.pop()
        assert e1.time == 5
        assert e1.event_type == EventType.OP_COMPLETION

        e2 = eq.pop()
        assert e2.time == 5
        assert e2.event_type == EventType.JOB_ARRIVAL

        e3 = eq.pop()
        assert e3.time == 10

    def test_empty_queue_pop_raises(self):
        eq = EventQueue()
        with pytest.raises(IndexError):
            eq.pop()

    def test_peek(self):
        eq = EventQueue()
        assert eq.peek() is None
        eq.push(Event(time=5, event_type=EventType.JOB_ARRIVAL, job_id=0))
        assert eq.peek() is not None
        assert eq.peek().time == 5

    def test_is_empty(self):
        eq = EventQueue()
        assert eq.is_empty
        eq.push(Event(time=0, event_type=EventType.JOB_ARRIVAL, job_id=0))
        assert not eq.is_empty


class TestScheduleState:
    def test_initial_state(self):
        state = ScheduleState()
        assert state.current_time == 0
        assert state.is_machine_idle(0)  # no machine times set, default is 0

    def test_mark_operation_started(self):
        state = ScheduleState()
        state.mark_operation_started(
            job_id=0, op_id=0, machine_id=1, start_time=5, end_time=12
        )
        assert state.is_operation_ongoing(0, 0)
        assert not state.is_machine_idle(1)  # machine 1 busy until 12
        state.current_time = 12
        assert state.is_machine_idle(1)  # now it's free

    def test_mark_operation_completed(self):
        state = ScheduleState()
        state.mark_operation_started(0, 0, 1, 0, 5)
        state.mark_operation_completed(0, 0, 0)
        assert state.is_operation_completed(0, 0)
        assert not state.is_operation_ongoing(0, 0)
        assert state.next_op_index_for_job(0) == 1

    def test_job_completion_tracking(self):
        state = ScheduleState()
        state.mark_job_completed(3, 100)
        assert state.is_job_completed(3)
        assert state.completed_jobs[3] == 100

    def test_delivered_on_time(self):
        state = ScheduleState()
        state.mark_delivered_on_time(5)
        assert 5 in state.delivered_on_time_jobs


class TestObjective:
    def test_compute_objective_all_on_time(self):
        """Both jobs complete well before the deadline of 20."""
        inst = make_tiny_instance()
        state = ScheduleState()
        state.mark_job_completed(0, 5)
        state.mark_job_completed(1, 10)
        # Delivery times: D0=5, D1=10, both <= deadline 20
        state.mark_delivered_on_time(0)
        state.mark_delivered_on_time(1)

        result = compute_objective(inst, state)
        assert result.total_tardiness == 0
        assert result.weighted_service_shortfall == 0.0
        assert result.Z == 0.0
        assert result.zero_shortfall_entity_rate == 1.0

    def test_compute_objective_with_tardiness(self):
        """Both jobs complete after deadline."""
        inst = make_tiny_instance()
        state = ScheduleState()
        state.mark_job_completed(0, 30)  # D0=30, T0=10
        state.mark_job_completed(1, 40)  # D1=40, T1=20

        result = compute_objective(inst, state)
        assert result.total_tardiness == 30  # 10 + 20
        # On-time quantity = 0, shortfall = min_fulfillment = 30
        assert result.weighted_service_shortfall == 30.0
        expected_z = 1.0 * 30 + 1.0 * 30.0  # alpha=1, beta=1
        assert result.Z == expected_z

    def test_compute_objective_incomplete_schedule(self):
        inst = make_tiny_instance()
        state = ScheduleState()
        # Only one job completed
        state.mark_job_completed(0, 5)
        with pytest.raises(ValueError):
            compute_objective(inst, state)

    def test_partial_on_time_shortfall(self):
        """One job on time, one late -> partial shortfall."""
        inst = make_tiny_instance()
        state = ScheduleState()
        state.mark_job_completed(0, 5)    # q=10, on time
        state.mark_job_completed(1, 25)   # q=20, late (D1=25 > 20)
        state.mark_delivered_on_time(0)

        result = compute_objective(inst, state)
        # T0=0, T1=max(0,25-20)=5
        assert result.total_tardiness == 5
        # On-time = 10, min = 30, shortfall = 20
        assert result.weighted_service_shortfall == 20.0

    def test_fractional_service_threshold_is_not_truncated(self):
        """The paper model uses rho * Q, not int(rho * Q), for shortfall."""
        jobs = [
            Job(
                job_id=0,
                entity_id=0,
                release_time=0,
                quantity=1,
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
                release_time=0,
                quantity=2,
                operations=[
                    Operation(
                        op_id=100,
                        job_id=1,
                        sequence_index=0,
                        alternatives=[OperationAlternative(machine_id=0, processing_time=10)],
                    )
                ],
            ),
        ]
        inst = SLISPInstance(
            jobs=jobs,
            entities=[
                ServiceEntity(
                    entity_id=0,
                    deadline=5,
                    rho=0.5,
                    weight=1.0,
                    total_quantity=3,
                    transport_delay=0,
                )
            ],
            machines=[Machine(machine_id=0)],
            alpha=1.0,
            beta=1.0,
        )
        state = ScheduleState()
        state.mark_job_completed(0, 1)
        state.mark_job_completed(1, 11)

        result = compute_objective(inst, state)

        assert result.per_entity_shortfall[0] == 0.5
        assert result.weighted_service_shortfall == 0.5


class TestSimulator:
    def test_simple_two_job_simulation(self):
        """Run the EDF dispatcher on the tiny instance."""
        inst = make_tiny_instance()
        state, result = run_simulation(inst)

        # Both jobs should be completed
        assert state.is_job_completed(0)
        assert state.is_job_completed(1)

        # Job 0: pt=5, Job 1: pt=10, both start at t=0 on separate machines
        assert state.completed_jobs[0] == 5
        assert state.completed_jobs[1] == 10

        # Both delivered on time (5 <= 20, 10 <= 20)
        assert result.total_tardiness == 0
        assert result.Z == 0.0

    def test_simulation_with_delayed_release(self):
        """Job 1 arrives later, so it finishes later."""
        inst = make_tiny_instance(release_times=[0, 20])
        state, result = run_simulation(inst)

        assert state.is_job_completed(0)
        assert state.is_job_completed(1)
        # Job 1 starts at t=20, finishes at t=30
        assert state.completed_jobs[1] == 30
        # D1 = 30 > 20, so tardy
        assert result.total_tardiness == 10  # max(0, 30-20) = 10

    def test_multi_op_simulation(self):
        """Run simulation with multi-operation jobs and precedence."""
        inst = make_multi_op_instance()
        state, result = run_simulation(inst)

        assert state.is_job_completed(0)
        assert state.is_job_completed(1)

        # Precedence must be respected: job 0 op0 before op1, job 1 op100 before op101
        ops = state.scheduled_operations

        # Get operations for each job
        j0_ops = sorted(
            [s for s in ops if s.job_id == 0], key=lambda s: s.start_time
        )
        j1_ops = sorted(
            [s for s in ops if s.job_id == 1], key=lambda s: s.start_time
        )

        # Precedence: op1 must start after op0 ends for job 0
        assert j0_ops[0].op_id == 0  # first op
        assert j0_ops[1].op_id == 1  # second op
        assert j0_ops[1].start_time >= j0_ops[0].end_time

        # Precedence for job 1
        assert j1_ops[0].op_id == 100
        assert j1_ops[1].op_id == 101
        assert j1_ops[1].start_time >= j1_ops[0].end_time

        # No overlapping operations on the same machine
        for m in inst.machines:
            m_ops = sorted(
                [s for s in ops if s.machine_id == m.machine_id],
                key=lambda s: s.start_time,
            )
            for i in range(len(m_ops) - 1):
                assert m_ops[i].end_time <= m_ops[i + 1].start_time, (
                    f"Machine {m.machine_id}: overlapping ops "
                    f"{m_ops[i]} and {m_ops[i+1]}"
                )

    def test_all_jobs_have_completion_times(self):
        """After simulation, every job must have a recorded completion time."""
        inst = make_tiny_instance()
        state, _ = run_simulation(inst)
        for job in inst.jobs:
            assert state.is_job_completed(job.job_id), (
                f"Job {job.job_id} was not completed"
            )

    def test_trivial_rule_produces_feasible_schedule(self):
        """The built-in EDF rule must produce a feasible schedule for every op."""
        inst = make_multi_op_instance()
        state, _ = run_simulation(inst)

        total_ops = sum(j.num_operations for j in inst.jobs)
        completed = len(state.completed_operations)
        assert completed == total_ops, (
            f"Only {completed}/{total_ops} operations completed"
        )

    def test_no_machine_double_booking(self):
        """At any point in time, each machine processes at most one operation."""
        inst = make_multi_op_instance()
        state, _ = run_simulation(inst)

        # Group scheduled ops by machine and check for overlaps
        for m in inst.machines:
            m_ops = sorted(
                [s for s in state.scheduled_operations if s.machine_id == m.machine_id],
                key=lambda s: s.start_time,
            )
            for i in range(len(m_ops) - 1):
                assert m_ops[i].end_time <= m_ops[i + 1].start_time, (
                    f"Machine {m.machine_id} double-booked: "
                    f"{m_ops[i]} overlaps {m_ops[i+1]}"
                )
