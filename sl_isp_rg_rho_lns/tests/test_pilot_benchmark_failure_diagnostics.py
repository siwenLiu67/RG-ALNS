"""Tests for benchmark failure diagnostics."""

import csv

from src.core.dataclasses import (
    Job,
    Machine,
    Operation,
    OperationAlternative,
    ServiceEntity,
    SLISPInstance,
)
from src.experiments.run_pilot_benchmark import _append_csv, _run_single_simulation


def _tiny_instance() -> SLISPInstance:
    entity = ServiceEntity(
        entity_id=0,
        deadline=20,
        rho=1.0,
        weight=1.0,
        total_quantity=10,
        transport_delay=0,
    )
    machine = Machine(machine_id=0)
    job = Job(
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
    )
    return SLISPInstance(
        jobs=[job],
        entities=[entity],
        machines=[machine],
        alpha=1.0,
        beta=1.0,
    )


def test_single_simulation_failure_row_includes_exception_diagnostics():
    row = _run_single_simulation(
        _tiny_instance(),
        "unknown_rule",
        {"type": "dispatching", "label": "Broken Rule"},
        run_seed=42,
    )

    assert row["status"] == "FAILED"
    assert row["error_type"] == "ValueError"
    assert "Unknown dispatching rule: unknown_rule" in row["error_message"]
    assert "ValueError: Unknown dispatching rule: unknown_rule" in row["error_traceback"]


def test_append_csv_preserves_existing_header_order(tmp_path):
    path = tmp_path / "convergence.csv"
    _append_csv(
        path,
        [
            {
                "iteration": 0,
                "current_Z": 10.0,
                "best_so_far_Z": 10.0,
                "runtime_elapsed": 0.0,
                "algorithm": "ils_fast",
                "pressure_level": "medium",
            }
        ],
    )

    _append_csv(
        path,
        [
            {
                "iteration": 1,
                "current_Z": 9.0,
                "best_so_far_Z": 9.0,
                "runtime_elapsed": 0.1,
                "pressure_level": "medium",
                "algorithm": "nr_rg_rho_lns",
            }
        ],
    )

    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))

    assert rows[1]["algorithm"] == "nr_rg_rho_lns"
    assert rows[1]["pressure_level"] == "medium"
