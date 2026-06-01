"""Smoke tests for fast metaheuristic baseline algorithms."""

from src.algorithms.baselines_fast import run_ga_fast, run_sa_fast
from src.core.dataclasses import (
    Job,
    Machine,
    Operation,
    OperationAlternative,
    ServiceEntity,
    SLISPInstance,
)
from src.core.simulator import run_simulation
from src.experiments.run_pilot_benchmark import _create_algorithm


def _op(job_id: int, seq: int, p0: int, p1: int) -> Operation:
    return Operation(
        op_id=job_id * 100 + seq,
        job_id=job_id,
        sequence_index=seq,
        alternatives=[
            OperationAlternative(machine_id=0, processing_time=p0),
            OperationAlternative(machine_id=1, processing_time=p1),
        ],
    )


def _small_meta_instance() -> SLISPInstance:
    jobs = [
        Job(0, 0, 0, 3, [_op(0, 0, 4, 6), _op(0, 1, 5, 3)]),
        Job(1, 0, 0, 4, [_op(1, 0, 6, 2), _op(1, 1, 3, 5)]),
        Job(2, 1, 0, 2, [_op(2, 0, 3, 5), _op(2, 1, 4, 2)]),
        Job(3, 1, 0, 5, [_op(3, 0, 5, 3), _op(3, 1, 2, 6)]),
    ]
    entities = [
        ServiceEntity(0, deadline=13, rho=0.6, weight=2.0, total_quantity=7, transport_delay=0),
        ServiceEntity(1, deadline=12, rho=0.6, weight=1.0, total_quantity=7, transport_delay=0),
    ]
    return SLISPInstance(
        jobs=jobs,
        entities=entities,
        machines=[Machine(0), Machine(1)],
        alpha=1.0,
        beta=1.0,
    )


def test_sa_fast_runs_to_complete_schedule():
    algo = run_sa_fast(horizon=50, max_iter=4, seed=7)
    state, obj = run_simulation(_small_meta_instance(), algo)

    assert len(state.completed_jobs) == 4
    assert obj.Z >= 0
    assert algo._convergence_log


def test_ga_fast_runs_to_complete_schedule():
    algo = run_ga_fast(horizon=50, max_iter=3, population_size=6, seed=7)
    state, obj = run_simulation(_small_meta_instance(), algo)

    assert len(state.completed_jobs) == 4
    assert obj.Z >= 0
    assert algo._convergence_log


def test_pilot_factory_supports_new_metaheuristics():
    sa, sa_label = _create_algorithm(
        "sa",
        {"type": "sa_fast", "label": "SA-Fast", "max_iter": 2},
        seed=11,
    )
    ga, ga_label = _create_algorithm(
        "ga",
        {"type": "ga_fast", "label": "GA-Fast", "max_iter": 2, "population_size": 4},
        seed=11,
    )

    assert sa_label == "SA-Fast"
    assert ga_label == "GA-Fast"
    assert callable(sa)
    assert callable(ga)
