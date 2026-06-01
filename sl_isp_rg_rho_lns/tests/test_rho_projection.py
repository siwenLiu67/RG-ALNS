"""Regression tests for rolling-horizon projection semantics."""

import random

import pytest

from src.algorithms.rg_rho_lns_fast import (
    FastSchedule,
    RGRHOLNSFast,
    _apply_exact_local_repair,
    _combine_context_and_learned_weights,
    _compute_rg_scores,
    _event_search_budget,
    _extract_immediate_decisions,
    _fast_eval_Z,
    _multi_start_initial_solution,
    _operator_learning_reward,
    _quota_marginal_service_quantity,
    _repair_by_sequence_crossover,
    _rollout_edd_rule,
    _should_run_exact_local_repair,
    _tardiness_opportunity_gain,
    _update_operator_weight,
    _useful_service_quantity,
    run_plain_rho_fast,
)
from src.core.dataclasses import (
    Job,
    Machine,
    Operation,
    OperationAlternative,
    ServiceEntity,
    SLISPInstance,
)
from src.core.schedule_state import ScheduleState
from src.core.simulator import run_simulation
from src.generation.instance_generator import InstanceConfig, generate_instance
from src.experiments.run_pilot_benchmark import _generate_instance


def make_release_conflict_instance() -> SLISPInstance:
    """One-machine instance where future urgent work must not block current work."""
    jobs = [
        Job(
            job_id=0,
            entity_id=0,
            release_time=0,
            quantity=100,
            operations=[
                Operation(
                    op_id=0,
                    job_id=0,
                    sequence_index=0,
                    alternatives=[OperationAlternative(machine_id=0, processing_time=200)],
                )
            ],
        ),
        Job(
            job_id=1,
            entity_id=1,
            release_time=100,
            quantity=1,
            operations=[
                Operation(
                    op_id=0,
                    job_id=1,
                    sequence_index=0,
                    alternatives=[OperationAlternative(machine_id=0, processing_time=10)],
                )
            ],
        ),
    ]
    entities = [
        ServiceEntity(
            entity_id=0,
            deadline=250,
            rho=1.0,
            weight=1.0,
            total_quantity=100,
            transport_delay=0,
        ),
        ServiceEntity(
            entity_id=1,
            deadline=150,
            rho=1.0,
            weight=1.0,
            total_quantity=1,
            transport_delay=0,
        ),
    ]
    return SLISPInstance(
        jobs=jobs,
        entities=entities,
        machines=[Machine(machine_id=0)],
        alpha=1.0,
        beta=1.0,
    )


def test_plain_rho_dispatches_current_ready_work_before_future_release():
    inst = make_release_conflict_instance()
    state = ScheduleState(current_time=0)
    state.machine_available_times[0] = 0

    decisions = run_plain_rho_fast(horizon=300, seed=1)(inst, state)

    assert decisions == [(0, 0, 0, 0)]


def test_plain_rho_improves_release_conflict_over_old_idle_projection():
    inst = make_release_conflict_instance()

    state, obj = run_simulation(inst, run_plain_rho_fast(horizon=300, seed=1))

    assert state.completed_jobs[0] == 200
    assert obj.Z == 61.0


def test_fast_eval_does_not_treat_unscheduled_jobs_as_time_zero():
    base = make_release_conflict_instance()
    inst = SLISPInstance(
        jobs=base.jobs,
        entities=[
            base.entities[0],
            ServiceEntity(
                entity_id=1,
                deadline=50,
                rho=1.0,
                weight=1.0,
                total_quantity=1,
                transport_delay=0,
            ),
        ],
        machines=base.machines,
        alpha=1.0,
        beta=1.0,
    )
    state = ScheduleState(current_time=0)
    state.machine_available_times[0] = 0
    sched = FastSchedule()
    sched.machine_slots[0] = []

    z_value = _fast_eval_Z(sched, inst, state)

    assert z_value >= 60


def test_fast_eval_uses_final_operation_not_append_order():
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
                ),
                Operation(
                    op_id=1,
                    job_id=0,
                    sequence_index=1,
                    alternatives=[OperationAlternative(machine_id=0, processing_time=10)],
                ),
            ],
        )
    ]
    inst = SLISPInstance(
        jobs=jobs,
        entities=[
            ServiceEntity(
                entity_id=0,
                deadline=30,
                rho=1.0,
                weight=1.0,
                total_quantity=1,
                transport_delay=0,
            )
        ],
        machines=[Machine(machine_id=0)],
        alpha=1.0,
        beta=1.0,
    )
    state = ScheduleState(current_time=0)
    state.machine_available_times[0] = 0
    sched = FastSchedule()
    sched.machine_slots[0] = []

    sched.add_op(0, 1, 0, 10, 20)
    sched.add_op(0, 0, 0, 100, 101)

    assert _fast_eval_Z(sched, inst, state) == 0.0


def test_exact_local_repair_improves_bad_service_cover_schedule():
    pytest.importorskip("ortools.sat.python.cp_model")
    jobs = [
        Job(
            job_id=0,
            entity_id=1,
            release_time=0,
            quantity=1,
            operations=[
                Operation(
                    op_id=0,
                    job_id=0,
                    sequence_index=0,
                    alternatives=[OperationAlternative(machine_id=0, processing_time=8)],
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
                    op_id=0,
                    job_id=1,
                    sequence_index=0,
                    alternatives=[OperationAlternative(machine_id=0, processing_time=8)],
                )
            ],
        ),
        Job(
            job_id=2,
            entity_id=0,
            release_time=0,
            quantity=1,
            operations=[
                Operation(
                    op_id=0,
                    job_id=2,
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
                deadline=11,
                rho=1.0,
                weight=10.0,
                total_quantity=3,
                transport_delay=0,
            ),
            ServiceEntity(
                entity_id=1,
                deadline=100,
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
    state = ScheduleState(current_time=0)
    state.machine_available_times[0] = 0
    sched = FastSchedule()
    sched.machine_slots[0] = []
    sched.add_op(0, 0, 0, 0, 8)
    sched.add_op(1, 0, 0, 8, 16)
    sched.add_op(2, 0, 0, 16, 18)

    old_z = _fast_eval_Z(sched, inst, state)
    repaired, new_z, info = _apply_exact_local_repair(
        inst,
        state,
        sched,
        old_z,
        candidates=[0, 1, 2],
        scores={1: 10.0, 2: 10.0, 0: 0.0},
        max_jobs=3,
        time_limit_s=2.0,
    )

    assert info["accepted"] is True
    assert new_z < old_z
    assert _fast_eval_Z(repaired, inst, state) == new_z


def test_exact_repair_mandatory_selection_uses_machine_pool(monkeypatch):
    import src.algorithms.rg_rho_lns_fast as rho_module

    inst = make_release_conflict_instance()
    state = ScheduleState(current_time=0)
    state.machine_available_times[0] = 0
    sched = FastSchedule()
    sched.add_op(0, 0, 0, 0, 200)
    sched.add_op(1, 0, 0, 200, 210)
    seen_pools: list[set[int]] = []

    def fake_mandatory_rescue_jobs(
        _entity_id, pool_B, _state, _instance, method="dp"
    ):
        seen_pools.append(set(pool_B))
        return []

    monkeypatch.setattr(
        rho_module, "mandatory_rescue_jobs", fake_mandatory_rescue_jobs
    )

    rho_module._select_exact_repair_jobs(
        inst,
        state,
        sched,
        candidates=[0, 1],
        scores={},
        max_jobs=1,
    )

    assert seen_pools
    assert all(pool == {0} for pool in seen_pools)


def test_exact_repair_selection_includes_same_machine_blocker():
    import src.algorithms.rg_rho_lns_fast as rho_module

    jobs = [
        Job(
            job_id=0,
            entity_id=1,
            release_time=0,
            quantity=1,
            operations=[
                Operation(
                    op_id=0,
                    job_id=0,
                    sequence_index=0,
                    alternatives=[OperationAlternative(machine_id=0, processing_time=8)],
                )
            ],
        ),
        Job(
            job_id=1,
            entity_id=0,
            release_time=0,
            quantity=1,
            operations=[
                Operation(
                    op_id=10,
                    job_id=1,
                    sequence_index=0,
                    alternatives=[OperationAlternative(machine_id=0, processing_time=3)],
                )
            ],
        ),
        Job(
            job_id=2,
            entity_id=1,
            release_time=0,
            quantity=1,
            operations=[
                Operation(
                    op_id=20,
                    job_id=2,
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
                deadline=5,
                rho=1.0,
                weight=10.0,
                total_quantity=1,
                transport_delay=0,
            ),
            ServiceEntity(
                entity_id=1,
                deadline=100,
                rho=1.0,
                weight=1.0,
                total_quantity=2,
                transport_delay=0,
            ),
        ],
        machines=[Machine(machine_id=0)],
        alpha=1.0,
        beta=1.0,
    )
    state = ScheduleState(current_time=0)
    state.machine_available_times[0] = 0
    sched = FastSchedule()
    sched.machine_slots[0] = []
    sched.add_op(0, 0, 0, 0, 8)
    sched.add_op(1, 10, 0, 8, 11)
    sched.add_op(2, 20, 0, 11, 13)

    active = rho_module._select_exact_repair_jobs(
        inst,
        state,
        sched,
        candidates=[0, 1, 2],
        scores={1: 20.0, 0: 0.0, 2: 0.0},
        max_jobs=2,
    )

    assert active[0] == 1
    assert 0 in active


def test_useful_service_quantity_caps_already_secured_entity():
    inst = make_release_conflict_instance()
    state = ScheduleState(current_time=0)
    state.completed_jobs[0] = 200

    assert _useful_service_quantity(inst, state, inst.get_job(0)) == 0.0
    assert _useful_service_quantity(inst, ScheduleState(current_time=0), inst.get_job(0)) == 100.0


def test_sequence_crossover_neighborhood_improves_projected_order():
    cfg = InstanceConfig(
        group_name="seq_xover",
        num_instances=1,
        num_jobs=10,
        num_machines=4,
        num_entities=3,
        ops_per_job=(2, 3),
        rho_range=(0.70, 0.80),
        deadline_tightness=1.0,
        weight_pattern="mild",
        quantity_range=(1, 10),
        proc_time_range=(1, 9),
        transport_delay_range=(0, 0),
        eligible_machines_range=(2, 4),
    )
    base = generate_instance(cfg, seed=20260526)
    effective_due_values = [12, 20, 28]
    inst = SLISPInstance(
        jobs=base.jobs,
        entities=[
            ServiceEntity(
                entity_id=e.entity_id,
                deadline=effective_due_values[e.entity_id] + e.transport_delay,
                rho=e.rho,
                weight=e.weight,
                total_quantity=e.total_quantity,
                transport_delay=e.transport_delay,
            )
            for e in base.entities
        ],
        machines=base.machines,
        alpha=base.alpha,
        beta=base.beta,
        metadata={**base.metadata, "effective_due_values": effective_due_values},
    )
    state = ScheduleState(current_time=0)
    for machine in inst.machines:
        state.machine_available_times[machine.machine_id] = 0
    candidates = [job.job_id for job in inst.jobs]
    scores = _compute_rg_scores(
        inst,
        state,
        {machine.machine_id for machine in inst.machines},
        0.40,
        0.15,
        0.10,
        0.05,
        0.10,
        0.50,
        0.20,
    )
    rng = random.Random(20260526)
    sched, initial_z, _diag = _multi_start_initial_solution(
        inst,
        state,
        candidates,
        scores,
        rng,
        top_k=2,
        polish_moves=30,
    )

    improved = _repair_by_sequence_crossover(
        inst,
        sched,
        state,
        candidates,
        scores,
        rng,
        trials=8,
    )

    assert _fast_eval_Z(improved, inst, state) < initial_z


def test_quota_marginal_service_ignores_redundant_on_time_quantity():
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
            release_time=0,
            quantity=1,
            operations=[
                Operation(
                    op_id=10,
                    job_id=1,
                    sequence_index=0,
                    alternatives=[OperationAlternative(machine_id=0, processing_time=1)],
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
                rho=0.5,
                weight=1.0,
                total_quantity=10,
                transport_delay=0,
            )
        ],
        machines=[Machine(machine_id=0)],
        alpha=1.0,
        beta=1.0,
    )
    state = ScheduleState(current_time=0)
    state.machine_available_times[0] = 0
    pool = {0}

    assert _quota_marginal_service_quantity(inst, state, pool, inst.get_job(1)) == 0.0
    assert _quota_marginal_service_quantity(inst, state, pool, inst.get_job(0)) == 4.0


def test_tardiness_opportunity_gain_values_late_pull_forward():
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
                    alternatives=[OperationAlternative(machine_id=0, processing_time=5)],
                ),
                Operation(
                    op_id=1,
                    job_id=0,
                    sequence_index=1,
                    alternatives=[OperationAlternative(machine_id=0, processing_time=7)],
                ),
            ],
        )
    ]
    inst = SLISPInstance(
        jobs=jobs,
        entities=[
            ServiceEntity(
                entity_id=0,
                deadline=10,
                rho=1.0,
                weight=1.0,
                total_quantity=1,
                transport_delay=0,
            )
        ],
        machines=[Machine(machine_id=0)],
        alpha=1.0,
        beta=1.0,
    )
    state = ScheduleState(current_time=0)
    state.machine_available_times[0] = 0
    job = inst.get_job(0)

    gain = _tardiness_opportunity_gain(
        inst,
        state,
        job,
        job.operation_at(0),
        processing_time=5,
        delay_duration=3,
    )

    assert gain == 3.0


def test_standard_projected_extraction_follows_projected_order_even_with_mandatory_rescue():
    jobs = [
        Job(
            job_id=0,
            entity_id=0,
            release_time=0,
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
            entity_id=1,
            release_time=0,
            quantity=1,
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
    inst = SLISPInstance(
        jobs=jobs,
        entities=[
            ServiceEntity(
                entity_id=0,
                deadline=5,
                rho=1.0,
                weight=10.0,
                total_quantity=10,
                transport_delay=0,
            ),
            ServiceEntity(
                entity_id=1,
                deadline=100,
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
    state = ScheduleState(current_time=0)
    state.machine_available_times[0] = 0
    sched = FastSchedule()
    sched.machine_slots[0] = []
    sched.add_op(1, 100, 0, 0, 1)
    sched.add_op(0, 0, 0, 1, 6)

    decisions = _extract_immediate_decisions(sched, inst, state, dispatch_mode="standard_projected")

    assert decisions == [(1, 100, 0, 0)]


def test_service_aware_extraction_can_override_projection_for_mandatory_rescue():
    jobs = [
        Job(
            job_id=0,
            entity_id=0,
            release_time=0,
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
            entity_id=1,
            release_time=0,
            quantity=1,
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
    inst = SLISPInstance(
        jobs=jobs,
        entities=[
            ServiceEntity(
                entity_id=0,
                deadline=5,
                rho=1.0,
                weight=10.0,
                total_quantity=10,
                transport_delay=0,
            ),
            ServiceEntity(
                entity_id=1,
                deadline=100,
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
    state = ScheduleState(current_time=0)
    state.machine_available_times[0] = 0
    sched = FastSchedule()
    sched.machine_slots[0] = []
    sched.add_op(1, 100, 0, 0, 1)
    sched.add_op(0, 0, 0, 1, 6)

    decisions = _extract_immediate_decisions(sched, inst, state, dispatch_mode="service_aware")

    assert decisions == [(0, 0, 0, 0)]


def test_operator_learning_weights_feed_back_into_sampling_probabilities():
    names = ["a", "b"]
    learned = {"a": 1.0, "b": 1.0}
    context = [0.5, 0.5]

    before = _combine_context_and_learned_weights(names, context, learned)
    reward = _operator_learning_reward(100.0, 80.0, accepted=True, wsf_tolerance_accept=False)
    _update_operator_weight(
        learned,
        "a",
        reward=reward,
        reaction_factor=0.5,
        min_weight=0.05,
        max_weight=8.0,
    )
    after = _combine_context_and_learned_weights(names, context, learned)

    assert before == [0.5, 0.5]
    assert learned["a"] > learned["b"]
    assert after[0] > before[0]
    assert after[1] < before[1]


def test_nr_factory_passes_exact_local_repair_budget():
    from src.experiments.run_pilot_benchmark import _create_algorithm

    algo, label = _create_algorithm(
        "nr_rg_rho_lns",
        {
            "type": "nr_rg_rho_lns",
            "label": "NR-RG-RHO-LNS",
            "horizon": 120,
            "lns_iterations": 5,
            "exact_local_job_limit": 6,
            "exact_local_time_limit_s": 0.2,
        },
        seed=7,
    )

    assert label == "NR-RG-RHO-LNS"
    assert algo.exact_local_job_limit == 6
    assert algo.exact_local_time_limit_s == 0.2
    assert algo.use_lns is True
    assert algo.use_multi_start_init is True


def test_rg_alns_kwargs_maps_shared_parameters():
    from src.experiments.run_pilot_benchmark import _rg_alns_kwargs

    kwargs = _rg_alns_kwargs(
        {
            "horizon": 90,
            "lns_iterations": 7,
            "exact_local_job_limit": 4,
            "exact_local_time_limit_s": 0.15,
            "use_sequence_crossover": False,
            "sequence_crossover_trials": 9,
            "dispatch_mode": "service_aware",
        },
        seed=123,
        default_lns_iterations=20,
    )

    assert kwargs == {
        "horizon": 90,
        "lns_iterations": 7,
        "exact_local_job_limit": 4,
        "exact_local_time_limit_s": 0.15,
        "use_sequence_crossover": False,
        "sequence_crossover_trials": 9,
        "dispatch_mode": "service_aware",
        "seed": 123,
    }


def test_rg_alns_factory_uses_final_paper_name_and_standard_projected_dispatch():
    from src.experiments.run_pilot_benchmark import _create_algorithm

    algo, label = _create_algorithm(
        "rg_alns",
        {"type": "rg_alns"},
        seed=42,
    )

    assert label == "RG-ALNS"
    assert algo.dispatch_mode == "standard_projected"
    assert algo.use_lns is True
    assert algo.use_operator_adaptation is True


def test_low_risk_event_search_budget_reduces_lns_and_local_search():
    budget = _event_search_budget(
        base_lns_iterations=20,
        base_local_search_iters=40,
        rg_intensity=0.0,
        projected_wsf=0.0,
        mandatory_count=0,
    )

    assert budget["lns_iterations"] == 5
    assert budget["local_search_iters"] == 10
    assert budget["risk_level"] == "low"


def test_high_risk_event_search_budget_keeps_full_budget():
    budget = _event_search_budget(
        base_lns_iterations=20,
        base_local_search_iters=40,
        rg_intensity=0.6,
        projected_wsf=1.0,
        mandatory_count=2,
    )

    assert budget["lns_iterations"] == 20
    assert budget["local_search_iters"] == 40
    assert budget["risk_level"] == "high"


def test_exact_local_repair_runs_only_when_service_risk_is_present():
    assert _should_run_exact_local_repair(
        use_exact_local_repair=True,
        projected_wsf=0.0,
        mandatory_count=0,
        rg_intensity=0.0,
        no_improve=0,
    ) is False

    assert _should_run_exact_local_repair(
        use_exact_local_repair=True,
        projected_wsf=1.0,
        mandatory_count=0,
        rg_intensity=0.0,
        no_improve=0,
    ) is True

    assert _should_run_exact_local_repair(
        use_exact_local_repair=True,
        projected_wsf=0.0,
        mandatory_count=1,
        rg_intensity=0.0,
        no_improve=0,
    ) is False


def test_nr_factory_defaults_to_alns_main_path():
    from src.experiments.run_pilot_benchmark import _create_algorithm

    algo, _label = _create_algorithm(
        "nr_rg_rho_lns",
        {"type": "nr_rg_rho_lns", "label": "NR-RG-RHO-LNS"},
        seed=42,
    )

    assert algo.use_lns is True
    assert algo.use_multi_start_init is True


def test_simulator_rejects_non_next_operation_decision():
    inst = make_release_conflict_instance()

    def invalid_algorithm(_inst, _state):
        return [(0, 99, 0, 0)]

    with pytest.raises(ValueError):
        run_simulation(inst, invalid_algorithm)


def test_plain_rho_generated_dynamic_instance_returns_only_valid_next_operations():
    cfg = {
        "num_jobs": 40,
        "num_machines": 5,
        "num_entities": 3,
        "ops_per_job": [2, 4],
        "rho_range": [0.75, 0.85],
        "deadline_tightness": 1.0,
        "weight_pattern": "mild",
        "proc_time_range": [10, 50],
        "transport_delay_range": [10, 40],
        "eligible_machines_range": [2, 3],
        "arrival_intensity": "medium",
        "alpha": 1.0,
        "beta": 1.0,
    }
    inst = _generate_instance(cfg, seed=42, idx=0)

    state, _obj = run_simulation(inst, run_plain_rho_fast(horizon=300, seed=42))

    assert len(state.completed_jobs) == inst.num_jobs
