"""Tests for Paper A current-time execution policy."""

from __future__ import annotations

import pytest

from src.core.dataclasses import (
    Job,
    Machine,
    Operation,
    OperationAlternative,
    ScheduledOperation,
    ServiceEntity,
)
from src.core.online import OnlineProblemView
from src.core.schedule_state import ScheduleState
from src.experiments.paper_a_online_protocol import (
    DecisionValidationError,
    extract_current_feasible_decisions,
    validate_current_decisions,
)


def _op(job_id: int, seq: int, machine_id: int = 0, pt: int = 2) -> Operation:
    return Operation(
        op_id=job_id * 10 + seq,
        job_id=job_id,
        sequence_index=seq,
        alternatives=[OperationAlternative(machine_id=machine_id, processing_time=pt)],
    )


def _job(job_id: int, release_time: int, machine_id: int = 0) -> Job:
    return Job(
        job_id=job_id,
        entity_id=0,
        release_time=release_time,
        quantity=1,
        operations=[_op(job_id, 0, machine_id)],
    )


def _view() -> OnlineProblemView:
    visible_job = _job(0, 0)
    entity = ServiceEntity(
        entity_id=0,
        deadline=30,
        rho=1.0,
        weight=1.0,
        total_quantity=2,
        transport_delay=0,
    )
    return OnlineProblemView(
        jobs=[visible_job],
        entities=[entity],
        machines=[Machine(0)],
        alpha=1.0,
        beta=1.0,
        entity_future_quantity={0: 1},
        metadata={"online_visibility": True},
    )


def _state(time: int = 0) -> ScheduleState:
    state = ScheduleState(current_time=time)
    state.machine_available_times[0] = 0
    return state


def test_validate_current_decisions_accepts_only_current_feasible_operations():
    view = _view()
    state = _state()

    decisions = validate_current_decisions([(0, 0, 0, 0)], view, state)

    assert decisions == [(0, 0, 0, 0)]


def test_validate_current_decisions_rejects_future_job_and_future_start():
    view = _view()
    state = _state()

    with pytest.raises(DecisionValidationError, match="visible"):
        validate_current_decisions([(99, 990, 0, 0)], view, state)

    with pytest.raises(DecisionValidationError, match="current time"):
        validate_current_decisions([(0, 0, 0, 3)], view, state)


def test_validate_current_decisions_rejects_busy_machine_or_not_next_operation():
    view = _view()
    state = _state()
    state.machine_available_times[0] = 5

    with pytest.raises(DecisionValidationError, match="busy machine"):
        validate_current_decisions([(0, 0, 0, 0)], view, state)

    state.machine_available_times[0] = 0
    state.last_completed_op_index[0] = 0

    with pytest.raises(DecisionValidationError, match="next operation"):
        validate_current_decisions([(0, 0, 0, 0)], view, state)


def test_extract_current_feasible_decisions_filters_local_plan_to_current_time():
    view = _view()
    state = _state()
    local_plan = [
        ScheduledOperation(job_id=0, op_id=0, machine_id=0, start_time=0, end_time=2),
        ScheduledOperation(job_id=99, op_id=990, machine_id=0, start_time=0, end_time=2),
        ScheduledOperation(job_id=0, op_id=0, machine_id=0, start_time=2, end_time=4),
    ]

    decisions = extract_current_feasible_decisions(local_plan, view, state)

    assert decisions == [(0, 0, 0, 0)]
