"""Tests for Recoverability-Guided Reactive ALNS (RG-RALNS)."""

from __future__ import annotations

from src.algorithms.rg_ralns import (
    CandidateEvaluation,
    RGRALNS,
    RGRALNSConfig,
    compute_recoverability_diagnostics,
    collect_ready_operations,
    construct_affected_set,
    lightweight_rg_dispatch,
    _accept_candidate,
    _repair_service_safe_edd_spt,
    _should_trigger_due_to_bottleneck_competition,
    _should_trigger_due_to_cover_violation,
    _should_trigger_due_to_high_risk_arrival,
    _should_trigger_due_to_mandatory_ready,
    _should_trigger_due_to_shortfall,
)
from src.core.dataclasses import (
    Job,
    Machine,
    Operation,
    OperationAlternative,
    ScheduledOperation,
    ServiceEntity,
    SLISPInstance,
)
from src.core.online import OnlineProblemView
from src.core.schedule_state import ScheduleState
from src.core.simulator import run_simulation


def _op(job_id: int, seq: int, *alts: tuple[int, int]) -> Operation:
    return Operation(
        op_id=job_id * 10 + seq,
        job_id=job_id,
        sequence_index=seq,
        alternatives=[
            OperationAlternative(machine_id=machine_id, processing_time=pt)
            for machine_id, pt in alts
        ],
    )


def _job(
    job_id: int,
    entity_id: int,
    release: int,
    quantity: int,
    *alts: tuple[int, int],
) -> Job:
    return Job(
        job_id=job_id,
        entity_id=entity_id,
        release_time=release,
        quantity=quantity,
        operations=[_op(job_id, 0, *alts)],
    )


def _state(time: int = 0, machines: tuple[int, ...] = (0, 1)) -> ScheduleState:
    state = ScheduleState(current_time=time)
    state.machine_available_times = {machine_id: 0 for machine_id in machines}
    return state


def _online_view(
    jobs: list[Job],
    entities: list[ServiceEntity],
    machines: list[Machine],
    future: dict[int, int] | None = None,
) -> OnlineProblemView:
    return OnlineProblemView(
        jobs=jobs,
        entities=entities,
        machines=machines,
        alpha=1.0,
        beta=1.0,
        entity_future_quantity=future or {},
        metadata={"online_visibility": True},
    )


def test_rg_ralns_tuning_parameters_default_to_service_safe_strict_modes():
    config = RGRALNSConfig()

    assert config.acceptance_mode == "service_safe_z"
    assert config.bottleneck_trigger_mode == "strict"


def test_service_safe_acceptance_prioritizes_z_when_wsf_is_zero():
    incumbent = CandidateEvaluation(
        z=100.0,
        tt=100.0,
        wsf=0.0,
        risk_by_entity={0: 0.0},
        instability=0.0,
    )
    lower_z = CandidateEvaluation(
        z=95.0,
        tt=95.0,
        wsf=0.0,
        risk_by_entity={0: 0.0},
        instability=5.0,
    )
    higher_wsf = CandidateEvaluation(
        z=80.0,
        tt=79.0,
        wsf=1.0,
        risk_by_entity={0: 0.0},
        instability=0.0,
    )

    assert _accept_candidate(lower_z, incumbent, 1e-9, "service_safe_z")
    assert not _accept_candidate(higher_wsf, incumbent, 1e-9, "service_safe_z")


def test_service_safe_repair_keeps_cover_then_orders_remaining_by_edd_spt():
    entity = ServiceEntity(0, deadline=40, rho=0.5, weight=1.0, total_quantity=4, transport_delay=0)
    early_short = _job(0, 0, 0, 1, (0, 2))
    late_long = _job(1, 0, 0, 1, (0, 9))
    cover = _job(2, 0, 0, 1, (0, 5))
    view = _online_view([late_long, early_short, cover], [entity], [Machine(0)], future={0: 0})
    state = _state(machines=(0,))
    diagnostics = compute_recoverability_diagnostics(view, state)
    diagnostics.cover_jobs = {2}
    diagnostics.by_entity[0].cover_jobs = [2]

    order = _repair_service_safe_edd_spt(
        kept=[1],
        removed=[2, 0],
        problem=view,
        state=state,
        diagnostics=diagnostics,
    )

    assert order == [2, 0, 1]


def test_future_job_details_are_not_available_to_diagnostics():
    entity = ServiceEntity(0, deadline=20, rho=1.0, weight=1.0, total_quantity=12, transport_delay=0)
    visible = _job(0, 0, 0, 5, (0, 2))
    future = _job(99, 0, 10, 7, (0, 9999))
    view = _online_view([visible], [entity], [Machine(0)], future={0: future.quantity})

    diagnostics = compute_recoverability_diagnostics(view, _state(machines=(0,)))

    assert {job.job_id for job in view.jobs} == {0}
    assert diagnostics.by_entity[0].q_future == 7
    assert diagnostics.by_entity[0].visible_recoverable_jobs == {0}
    assert 99 not in diagnostics.visible_job_ids
    assert 99 not in diagnostics.mandatory_jobs
    assert 99 not in diagnostics.cover_jobs


def test_future_quantity_buffer_is_updated_by_online_simulator_only_on_arrival():
    entity = ServiceEntity(0, deadline=50, rho=1.0, weight=1.0, total_quantity=12, transport_delay=0)
    machines = [Machine(0)]
    instance = SLISPInstance(
        jobs=[
            _job(0, 0, 0, 5, (0, 2)),
            _job(1, 0, 10, 7, (0, 2)),
        ],
        entities=[entity],
        machines=machines,
        alpha=1.0,
        beta=1.0,
    )
    algo = RGRALNS(RGRALNSConfig(H_A=4, N_A=0, random_seed=7))

    run_simulation(instance, algo, online_visibility=True)

    history = [(item["time"], item["q_future"][0]) for item in algo.diagnostic_history]
    assert (0, 7) in history
    assert any(time > 0 and time < 10 and q_future == 7 for time, q_future in history)
    assert any(time >= 10 and q_future == 0 for time, q_future in history)


def test_diagnostics_compute_mandatory_cover_and_class_from_visible_jobs():
    entity = ServiceEntity(0, deadline=20, rho=1.0, weight=1.0, total_quantity=12, transport_delay=0)
    visible = _job(0, 0, 0, 5, (0, 2))
    view = _online_view([visible], [entity], [Machine(0)], future={0: 7})

    diagnostics = compute_recoverability_diagnostics(view, _state(machines=(0,)))
    entity_diag = diagnostics.by_entity[0]

    assert entity_diag.q_sec == 0
    assert entity_diag.q_rem == 12
    assert entity_diag.q_rec == 5
    assert entity_diag.q_future == 7
    assert entity_diag.u_info == 0
    assert entity_diag.q_cover == 5
    assert entity_diag.mandatory_jobs == {0}
    assert entity_diag.cover_jobs == [0]
    assert entity_diag.recoverability_class == "arrival_dependent"


def test_heuristic_service_cover_is_deterministic_without_exact_set_cover():
    entity = ServiceEntity(0, deadline=30, rho=1.0, weight=1.0, total_quantity=10, transport_delay=0)
    jobs = [
        _job(0, 0, 0, 4, (0, 2)),
        _job(1, 0, 0, 7, (0, 4)),
        _job(2, 0, 0, 3, (0, 1)),
    ]
    view = _online_view(jobs, [entity], [Machine(0)], future={0: 0})

    first = compute_recoverability_diagnostics(view, _state(machines=(0,)))
    second = compute_recoverability_diagnostics(view, _state(machines=(0,)))

    assert first.by_entity[0].cover_jobs == [1, 2]
    assert second.by_entity[0].cover_jobs == [1, 2]


def test_trigger_conditions_are_deterministic_and_independent():
    entity = ServiceEntity(0, deadline=20, rho=1.0, weight=1.0, total_quantity=12, transport_delay=0)
    visible = _job(0, 0, 0, 5, (0, 2))
    view = _online_view([visible], [entity], [Machine(0)], future={0: 0})
    state = _state(machines=(0,))
    diagnostics = compute_recoverability_diagnostics(view, state, newly_arrived_job_ids={0})
    ready_ops = collect_ready_operations(view, state)

    assert _should_trigger_due_to_shortfall(diagnostics)
    assert _should_trigger_due_to_mandatory_ready(diagnostics, ready_ops)
    assert _should_trigger_due_to_high_risk_arrival(diagnostics)
    cover_entity_0 = ServiceEntity(0, deadline=20, rho=1.0, weight=1.0, total_quantity=1, transport_delay=0)
    cover_entity_1 = ServiceEntity(1, deadline=25, rho=1.0, weight=1.0, total_quantity=1, transport_delay=0)
    cover_view = _online_view(
        [
            _job(0, 0, 0, 1, (0, 2)),
            _job(1, 1, 0, 1, (0, 2)),
        ],
        [cover_entity_0, cover_entity_1],
        [Machine(0)],
        future={0: 0, 1: 0},
    )
    cover_diag = compute_recoverability_diagnostics(cover_view, state)
    cover_ready = collect_ready_operations(cover_view, state)

    assert _should_trigger_due_to_cover_violation(cover_view, state, cover_diag, cover_ready)

    low_entity = ServiceEntity(1, deadline=30, rho=0.5, weight=1.0, total_quantity=2, transport_delay=0)
    competitor = _job(1, 1, 0, 1, (0, 4))
    low_surplus = _job(2, 1, 0, 1, (0, 3))
    mixed_view = _online_view([visible, competitor, low_surplus], [entity, low_entity], [Machine(0)], future={0: 0, 1: 0})
    mixed_diag = compute_recoverability_diagnostics(mixed_view, state)
    mixed_ready = collect_ready_operations(mixed_view, state)

    assert _should_trigger_due_to_bottleneck_competition(mixed_view, state, mixed_diag, mixed_ready)


def test_strict_bottleneck_trigger_ignores_short_low_risk_competitor():
    high_entity = ServiceEntity(0, deadline=20, rho=1.0, weight=1.0, total_quantity=12, transport_delay=0)
    low_entity = ServiceEntity(1, deadline=40, rho=0.5, weight=1.0, total_quantity=2, transport_delay=0)
    mandatory = _job(0, 0, 0, 5, (0, 5))
    short_competitor = _job(1, 1, 0, 1, (0, 1))
    low_surplus = _job(2, 1, 0, 1, (1, 6))
    view = _online_view(
        [mandatory, short_competitor, low_surplus],
        [high_entity, low_entity],
        [Machine(0), Machine(1)],
        future={0: 0, 1: 0},
    )
    state = _state(machines=(0, 1))
    diagnostics = compute_recoverability_diagnostics(view, state)
    ready_ops = collect_ready_operations(view, state)

    assert _should_trigger_due_to_bottleneck_competition(
        view, state, diagnostics, ready_ops, mode="normal"
    )
    assert not _should_trigger_due_to_bottleneck_competition(
        view, state, diagnostics, ready_ops, mode="strict"
    )


def test_affected_set_excludes_future_jobs_and_respects_cap():
    entity = ServiceEntity(0, deadline=30, rho=1.0, weight=1.0, total_quantity=29, transport_delay=0)
    jobs = [
        _job(0, 0, 0, 5, (0, 2)),
        _job(1, 0, 0, 5, (0, 3)),
        _job(2, 0, 0, 5, (0, 4)),
        _job(3, 0, 0, 5, (0, 5)),
        _job(4, 0, 0, 5, (0, 6)),
    ]
    hidden_future = _job(99, 0, 10, 4, (0, 1))
    view = _online_view(jobs, [entity], [Machine(0)], future={0: hidden_future.quantity})
    state = _state(machines=(0,))
    diagnostics = compute_recoverability_diagnostics(view, state, newly_arrived_job_ids={0, 1, 2, 3, 4})
    ready_ops = collect_ready_operations(view, state)

    affected = construct_affected_set(view, state, diagnostics, ready_ops, H_A=2)

    assert len(affected) == 2
    assert 99 not in affected
    assert affected.issubset({0, 1, 2, 3, 4})
    assert diagnostics.mandatory_jobs.intersection(affected)


def test_affected_set_freezes_completed_and_ongoing_jobs():
    entity = ServiceEntity(0, deadline=30, rho=1.0, weight=1.0, total_quantity=15, transport_delay=0)
    jobs = [
        _job(0, 0, 0, 5, (0, 2)),
        _job(1, 0, 0, 5, (1, 6)),
        _job(2, 0, 0, 5, (0, 3), (1, 3)),
    ]
    view = _online_view(jobs, [entity], [Machine(0), Machine(1)], future={0: 0})
    state = _state(machines=(0, 1))
    state.completed_jobs[0] = 4
    state.completed_operations.add((0, 0))
    state.last_completed_op_index[0] = 0
    state.ongoing_operations[(1, 10)] = ScheduledOperation(1, 10, 1, 0, 6)
    state.machine_available_times[1] = 6

    diagnostics = compute_recoverability_diagnostics(view, state, newly_arrived_job_ids={0, 1, 2})
    ready_ops = collect_ready_operations(view, state)
    affected = construct_affected_set(view, state, diagnostics, ready_ops, H_A=5)

    assert 0 not in affected
    assert 1 not in affected
    assert 2 in affected


def test_lightweight_rg_dispatch_runs_when_no_trigger_holds():
    entity = ServiceEntity(0, deadline=30, rho=0.5, weight=1.0, total_quantity=2, transport_delay=0)
    jobs = [
        _job(0, 0, 0, 1, (0, 5)),
        _job(1, 0, 0, 1, (0, 2)),
    ]
    view = _online_view(jobs, [entity], [Machine(0)], future={0: 0})
    state = _state(machines=(0,))
    diagnostics = compute_recoverability_diagnostics(view, state)
    ready_ops = collect_ready_operations(view, state)

    assert not _should_trigger_due_to_shortfall(diagnostics)
    decision = lightweight_rg_dispatch(view, state, diagnostics, ready_ops)

    assert decision == [(1, 10, 0, 0)]


def test_local_alns_runs_only_on_affected_set():
    entity = ServiceEntity(0, deadline=30, rho=1.0, weight=1.0, total_quantity=12, transport_delay=0)
    visible = _job(0, 0, 0, 5, (0, 2))
    hidden_future = _job(99, 0, 20, 7, (0, 1))
    view = _online_view([visible], [entity], [Machine(0)], future={0: hidden_future.quantity})
    state = _state(machines=(0,))
    algo = RGRALNS(RGRALNSConfig(H_A=4, N_A=3, random_seed=11))

    decisions = algo(view, state)

    assert decisions == [(0, 0, 0, 0)]
    assert algo.last_triggered
    assert algo.last_affected_set == {0}
    assert set(algo.last_local_job_order).issubset(algo.last_affected_set)
    assert 99 not in algo.last_affected_set


def test_execution_policy_returns_only_current_feasible_operations():
    entity = ServiceEntity(0, deadline=30, rho=0.5, weight=1.0, total_quantity=2, transport_delay=0)
    jobs = [
        _job(0, 0, 0, 1, (0, 5)),
        _job(1, 0, 0, 1, (1, 2)),
        _job(99, 0, 20, 1, (0, 1)),
    ]
    view = _online_view(jobs[:2], [entity], [Machine(0), Machine(1)], future={0: 1})
    state = _state(machines=(0, 1))
    state.machine_available_times[0] = 4
    algo = RGRALNS(RGRALNSConfig(H_A=4, N_A=2, random_seed=5))

    decisions = algo(view, state)

    assert decisions == [(1, 10, 1, 0)]
    for job_id, op_id, machine_id, start_time in decisions:
        job = view.get_job(job_id)
        op = job.operation_at(state.next_op_index_for_job(job_id))
        assert start_time == state.current_time
        assert job.release_time <= state.current_time
        assert op.op_id == op_id
        assert state.is_machine_idle(machine_id)
        assert machine_id in op.eligible_machines
        assert not state.is_operation_completed(job_id, op_id)
        assert not state.is_operation_ongoing(job_id, op_id)
