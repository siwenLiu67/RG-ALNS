"""Tests for exact-vs-heuristic gap diagnostics."""

from src.analysis.exact_gap_diagnostics import diagnose_exact_gap
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


def test_gap_diagnostics_identifies_exact_only_on_time_job_and_blocker():
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
                    alternatives=[OperationAlternative(machine_id=0, processing_time=4)],
                )
            ],
        ),
        Job(
            job_id=1,
            entity_id=1,
            release_time=0,
            quantity=1,
            operations=[
                Operation(
                    op_id=10,
                    job_id=1,
                    sequence_index=0,
                    alternatives=[OperationAlternative(machine_id=0, processing_time=2)],
                )
            ],
        ),
    ]
    inst = SLISPInstance(
        jobs=jobs,
        entities=[
            ServiceEntity(
                entity_id=0,
                deadline=100,
                rho=1.0,
                weight=1.0,
                total_quantity=1,
                transport_delay=0,
            ),
            ServiceEntity(
                entity_id=1,
                deadline=3,
                rho=1.0,
                weight=1.0,
                total_quantity=1,
                transport_delay=0,
            ),
        ],
        machines=[Machine(machine_id=0)],
        alpha=1.0,
        beta=1.0,
    )
    exact_state = ScheduleState()
    exact_state.scheduled_operations = [
        ScheduledOperation(1, 10, 0, 0, 2),
        ScheduledOperation(0, 0, 0, 2, 6),
    ]
    exact_state.completed_jobs = {0: 6, 1: 2}

    heuristic_state = ScheduleState()
    heuristic_state.scheduled_operations = [
        ScheduledOperation(0, 0, 0, 0, 4),
        ScheduledOperation(1, 10, 0, 4, 6),
    ]
    heuristic_state.completed_jobs = {0: 4, 1: 6}

    diag = diagnose_exact_gap(inst, exact_state, heuristic_state)

    assert diag["exact_only_on_time_jobs"] == [1]
    assert diag["heuristic_blockers_for_exact_only_on_time_jobs"][1] == [0]
    assert diag["per_job_tardiness_delta_heuristic_minus_exact"][1] == 3
