"""Tests for Paper A online baseline grouping and behavior."""

from __future__ import annotations

from src.core.dataclasses import (
    Job,
    Machine,
    Operation,
    OperationAlternative,
    ServiceEntity,
)
from src.core.online import OnlineProblemView
from src.core.schedule_state import ScheduleState
from src.experiments.paper_a_online_protocol import (
    CurrentTimeCommitWrapper,
    create_paper_a_algorithm,
    default_paper_a_algorithm_specs,
)


def _op(job_id: int, machine_id: int = 0, pt: int = 2) -> Operation:
    return Operation(
        op_id=job_id * 10,
        job_id=job_id,
        sequence_index=0,
        alternatives=[OperationAlternative(machine_id=machine_id, processing_time=pt)],
    )


def _view() -> OnlineProblemView:
    visible = Job(0, 0, 0, 2, [_op(0)])
    entity = ServiceEntity(
        entity_id=0,
        deadline=30,
        rho=1.0,
        weight=1.0,
        total_quantity=5,
        transport_delay=0,
    )
    return OnlineProblemView(
        jobs=[visible],
        entities=[entity],
        machines=[Machine(0)],
        alpha=1.0,
        beta=1.0,
        entity_future_quantity={0: 3},
        metadata={"online_visibility": True},
    )


def _state() -> ScheduleState:
    state = ScheduleState(current_time=0)
    state.machine_available_times[0] = 0
    return state


def test_dispatching_baselines_cannot_select_not_yet_arrived_jobs():
    dispatch_keys = {"edd", "spt", "wspt", "atc", "swd", "sfg"}
    specs = {
        spec.key: spec
        for spec in default_paper_a_algorithm_specs(include_offline_oracle=False)
        if spec.key in dispatch_keys
    }

    assert set(specs) == dispatch_keys
    for spec in specs.values():
        algorithm = CurrentTimeCommitWrapper(
            create_paper_a_algorithm(spec, seed=5),
            label=spec.label,
        )
        decisions = algorithm(_view(), _state())

        assert all(job_id == 0 for job_id, _op_id, _machine_id, _start in decisions)


def test_online_legacy_rg_alns_uses_visible_backlog_only():
    spec = next(
        item for item in default_paper_a_algorithm_specs(include_offline_oracle=False)
        if item.key == "online_legacy_rg_alns"
    )
    algorithm = CurrentTimeCommitWrapper(
        create_paper_a_algorithm(spec, seed=9),
        label=spec.label,
    )

    decisions = algorithm(_view(), _state())

    assert spec.online_visibility is True
    assert spec.table_group == "main_online"
    assert spec.label == "Online-Legacy-ALNS"
    assert decisions
    assert {job_id for job_id, _op_id, _machine_id, _start in decisions} == {0}


def test_online_and_offline_legacy_rg_alns_are_clearly_separated():
    specs = default_paper_a_algorithm_specs(include_offline_oracle=True)
    online = next(spec for spec in specs if spec.key == "online_legacy_rg_alns")
    offline = next(spec for spec in specs if spec.key == "offline_legacy_rg_alns")
    main_keys = {spec.key for spec in specs if spec.table_group == "main_online"}

    assert online.online_visibility is True
    assert online.table_group == "main_online"
    assert online.label == "Online-Legacy-ALNS"
    assert offline.online_visibility is False
    assert offline.table_group == "offline_oracle"
    assert offline.label == "Offline-Legacy-ALNS"
    assert "offline_legacy_rg_alns" not in main_keys
