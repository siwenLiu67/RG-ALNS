"""Tests for the exact small-instance CP-SAT reference model."""

import pytest

from src.core.dataclasses import (
    Job,
    Machine,
    Operation,
    OperationAlternative,
    ServiceEntity,
    SLISPInstance,
)
from src.solvers.exact_small_cp_sat import solve_exact_small_cp_sat


def _one_op_job(job_id: int, quantity: int, processing_time: int) -> Job:
    return Job(
        job_id=job_id,
        entity_id=0,
        release_time=0,
        quantity=quantity,
        operations=[
            Operation(
                op_id=job_id * 100,
                job_id=job_id,
                sequence_index=0,
                alternatives=[
                    OperationAlternative(machine_id=0, processing_time=processing_time)
                ],
            )
        ],
    )


def test_exact_solver_uses_fractional_shortfall_threshold():
    """Best schedule has one on-time job and a 0.25 fractional shortfall."""
    jobs = [
        _one_op_job(job_id=0, quantity=2, processing_time=2),
        _one_op_job(job_id=1, quantity=1, processing_time=10),
    ]
    inst = SLISPInstance(
        jobs=jobs,
        entities=[
            ServiceEntity(
                entity_id=0,
                deadline=3,
                rho=0.75,
                weight=1.0,
                total_quantity=3,
                transport_delay=0,
            )
        ],
        machines=[Machine(machine_id=0)],
        alpha=1.0,
        beta=1.0,
    )

    result = solve_exact_small_cp_sat(inst, time_limit_s=10)

    assert result.status == "OPTIMAL"
    assert result.objective_result is not None
    assert result.schedule_state is not None
    assert result.schedule_state.completed_jobs[0] == 2
    assert result.schedule_state.completed_jobs[1] == 12
    assert result.objective_result.total_tardiness == 9
    assert result.objective_result.per_entity_shortfall[0] == pytest.approx(0.25)
    assert result.objective_value == pytest.approx(9.25)


def test_exact_solver_respects_release_precedence_and_machine_capacity():
    jobs = [
        Job(
            job_id=0,
            entity_id=0,
            release_time=5,
            quantity=1,
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
                    alternatives=[OperationAlternative(machine_id=0, processing_time=4)],
                ),
            ],
        ),
        _one_op_job(job_id=1, quantity=1, processing_time=2),
    ]
    inst = SLISPInstance(
        jobs=jobs,
        entities=[
            ServiceEntity(
                entity_id=0,
                deadline=20,
                rho=1.0,
                weight=1.0,
                total_quantity=2,
                transport_delay=0,
            )
        ],
        machines=[Machine(machine_id=0)],
        alpha=1.0,
        beta=1.0,
    )

    result = solve_exact_small_cp_sat(inst, time_limit_s=10)

    assert result.status == "OPTIMAL"
    assert result.schedule_state is not None
    ops = result.scheduled_operations
    assert all(op.start_time >= 0 for op in ops)
    assert result.schedule_state.completed_jobs[0] >= 12
    first = next(op for op in ops if op.job_id == 0 and op.op_id == 0)
    second = next(op for op in ops if op.job_id == 0 and op.op_id == 1)
    assert first.start_time >= 5
    assert second.start_time >= first.end_time
