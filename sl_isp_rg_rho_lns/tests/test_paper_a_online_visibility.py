"""Tests for Paper A online visibility protocol."""

from __future__ import annotations

from src.core.dataclasses import (
    Job,
    Machine,
    Operation,
    OperationAlternative,
    ServiceEntity,
    SLISPInstance,
)
from src.core.simulator import run_simulation
from src.experiments.paper_a_online_protocol import (
    CurrentTimeCommitWrapper,
    create_paper_a_algorithm,
    default_paper_a_algorithm_specs,
)


def _op(job_id: int, seq: int, machine_id: int = 0, pt: int = 1) -> Operation:
    return Operation(
        op_id=job_id * 10 + seq,
        job_id=job_id,
        sequence_index=seq,
        alternatives=[OperationAlternative(machine_id=machine_id, processing_time=pt)],
    )


def _small_dynamic_instance() -> SLISPInstance:
    entity = ServiceEntity(
        entity_id=0,
        deadline=50,
        rho=1.0,
        weight=1.0,
        total_quantity=2,
        transport_delay=0,
    )
    jobs = [
        Job(0, 0, 0, 1, [_op(0, 0)]),
        Job(1, 0, 10, 1, [_op(1, 0)]),
    ]
    return SLISPInstance(
        jobs=jobs,
        entities=[entity],
        machines=[Machine(0)],
        alpha=1.0,
        beta=1.0,
    )


def test_all_main_table_algorithms_receive_only_online_view():
    instance = _small_dynamic_instance()
    specs = [
        spec for spec in default_paper_a_algorithm_specs(include_offline_oracle=True)
        if spec.table_group == "main_online"
    ]

    assert specs
    for spec in specs:
        algorithm = create_paper_a_algorithm(spec, seed=3)
        wrapped = CurrentTimeCommitWrapper(algorithm, label=spec.label)

        run_simulation(instance, wrapped, online_visibility=spec.online_visibility)

        assert spec.online_visibility is True
        assert wrapped.observed_problem_types
        assert "SLISPInstance" not in wrapped.observed_problem_types
        assert "OnlineProblemView" in wrapped.observed_problem_types


def test_future_quantity_buffer_changes_only_when_jobs_arrive():
    instance = _small_dynamic_instance()
    snapshots: list[tuple[int, list[int], dict[int, int]]] = []

    def observer(problem, state):
        snapshots.append(
            (
                state.current_time,
                sorted(job.job_id for job in problem.jobs),
                dict(problem.entity_future_quantity),
            )
        )
        for machine in problem.machines:
            if state.is_machine_idle(machine.machine_id):
                for job in problem.jobs:
                    if job.release_time <= state.current_time and not state.is_job_completed(job.job_id):
                        next_idx = state.next_op_index_for_job(job.job_id)
                        if next_idx < job.num_operations:
                            op = job.operation_at(next_idx)
                            if (
                                not state.is_operation_completed(job.job_id, op.op_id)
                                and not state.is_operation_ongoing(job.job_id, op.op_id)
                            ):
                                return [(job.job_id, op.op_id, machine.machine_id, state.current_time)]
        return []

    run_simulation(instance, observer, online_visibility=True)

    assert (0, [0], {0: 1}) in snapshots
    assert any(time > 0 and time < 10 and future == {0: 1} for time, _jobs, future in snapshots)
    assert any(time >= 10 and jobs == [0, 1] and future == {0: 0}
               for time, jobs, future in snapshots)
