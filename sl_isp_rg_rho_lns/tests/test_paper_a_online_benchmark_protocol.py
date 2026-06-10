"""Tests for the Paper A online benchmark runner protocol."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
import yaml

from src.core.dataclasses import (
    Job,
    Machine,
    Operation,
    OperationAlternative,
    ServiceEntity,
    SLISPInstance,
)
from src.core.objective import ObjectiveResult
from src.experiments.paper_a_online_protocol import (
    PROTOCOL_STATEMENT,
    compute_objective_calibration,
    evaluate_normalized_objective,
    load_paper_a_config,
    run_paper_a_online_benchmark,
)


def _write_config(path: Path, *, online_visibility: bool = True) -> None:
    config = {
        "experiment_protocol": "paper_a_online",
        "online_visibility": online_visibility,
        "current_time_commit_only": True,
        "hide_future_job_details": True,
        "instances": {
            "tiny_dynamic": {
                "num_instances": 1,
                "num_jobs": 8,
                "num_machines": 3,
                "num_entities": 2,
                "ops_per_job": [2, 2],
                "rho_range": [0.6, 0.7],
                "deadline_tightness": 1.4,
                "weight_pattern": "mild",
                "quantity_range": [1, 3],
                "proc_time_range": [1, 5],
                "transport_delay_range": [0, 2],
                "eligible_machines_range": [1, 2],
                "arrival_intensity": "medium",
                "alpha": 1.0,
                "beta": 1.0,
            }
        },
        "algorithms": {
            "main_online": [
                "edd",
                "spt",
                "lightweight_rg_dispatch",
                "online_legacy_rg_alns",
                "rg_ralns",
            ],
            "offline_oracle": [
                "offline_legacy_rg_alns",
            ],
        },
        "objective": {
            "type": "normalized",
            "alpha_0": 1.0,
            "beta_0": 20.0,
            "beta_sensitivity": [1, 5, 20],
        },
        "rg_ralns": {"H_A": 6, "N_A": 3},
        "legacy_rg_alns": {"horizon": 80, "lns_iterations": 2},
    }
    path.write_text(yaml.safe_dump(config), encoding="utf-8")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _single_op(job_id: int) -> Operation:
    return Operation(
        op_id=job_id,
        job_id=job_id,
        sequence_index=0,
        alternatives=[OperationAlternative(machine_id=0, processing_time=1)],
    )


def test_objective_calibration_uses_instance_level_scales():
    entity_0 = ServiceEntity(
        entity_id=0,
        deadline=10,
        rho=0.5,
        weight=2.0,
        total_quantity=10,
        transport_delay=2,
    )
    entity_1 = ServiceEntity(
        entity_id=1,
        deadline=6,
        rho=1.0,
        weight=1.5,
        total_quantity=3,
        transport_delay=1,
    )
    instance = SLISPInstance(
        jobs=[
            Job(0, 0, release_time=0, quantity=1, operations=[_single_op(0)]),
            Job(1, 0, release_time=5, quantity=1, operations=[_single_op(1)]),
            Job(2, 1, release_time=10, quantity=1, operations=[_single_op(2)]),
        ],
        entities=[entity_0, entity_1],
        machines=[Machine(0)],
        alpha=1.0,
        beta=1.0,
    )

    calibration = compute_objective_calibration(instance, alpha_0=1.0, beta_0=20.0)
    normalized = evaluate_normalized_objective(
        ObjectiveResult(
            total_tardiness=24,
            weighted_service_shortfall=2.9,
            Z=26.9,
            zero_shortfall_entity_rate=0.5,
            per_entity_shortfall={0: 1.0, 1: 0.0},
            per_job_tardiness={0: 10, 1: 14, 2: 0},
            per_entity_on_time_quantity={0: 4, 1: 3},
        ),
        calibration,
    )

    assert calibration.Theta_I == pytest.approx(12.0)
    assert calibration.Omega_I == pytest.approx(14.5)
    assert calibration.alpha_I == pytest.approx(1.0 / 12.0)
    assert calibration.beta_I == pytest.approx(20.0 / 14.5)
    assert normalized["TT_hat"] == pytest.approx(2.0)
    assert normalized["WSF_hat"] == pytest.approx(0.2)
    assert normalized["normalized_Z"] == pytest.approx(6.0)


def test_load_config_requires_paper_a_online_flags(tmp_path: Path):
    config_path = tmp_path / "paper_a_online.yaml"
    _write_config(config_path, online_visibility=False)

    with pytest.raises(ValueError, match="online_visibility"):
        load_paper_a_config(config_path)


def test_runner_writes_main_online_and_offline_outputs(tmp_path: Path):
    config_path = tmp_path / "paper_a_online.yaml"
    output_dir = tmp_path / "results"
    _write_config(config_path)

    result = run_paper_a_online_benchmark(
        config_path=config_path,
        seeds=[0],
        output_dir=output_dir,
        config_overrides={
            "rg_ralns": {
                "H_A": 4,
                "N_A": 2,
                "acceptance_mode": "service_safe_z",
                "bottleneck_trigger_mode": "normal",
            }
        },
    )

    expected_files = {
        "results_summary_csv",
        "per_instance_results_csv",
        "mechanism_stats_csv",
        "trigger_reason_counts_csv",
        "objective_calibration_csv",
        "beta_sensitivity_summary_csv",
        "config_used_yaml",
    }
    assert set(result["outputs"]) == expected_files
    for output_path in result["outputs"].values():
        assert Path(output_path).exists()

    per_instance = _read_csv(output_dir / "per_instance_results.csv")
    assert per_instance
    main_rows = [row for row in per_instance if row["table_group"] == "main_online"]
    oracle_rows = [row for row in per_instance if row["table_group"] == "offline_oracle"]

    assert main_rows
    assert oracle_rows
    assert all(row["online_visibility"] == "True" for row in main_rows)
    assert all(row["online_visibility"] == "False" for row in oracle_rows)
    assert "offline_legacy_rg_alns" not in {row["algorithm"] for row in main_rows}
    assert all(row["objective_scope"] == "global_final" for row in per_instance)
    assert "Online-Legacy-ALNS" in {row["algorithm_label"] for row in main_rows}
    assert "Offline-Legacy-ALNS" in {row["algorithm_label"] for row in oracle_rows}
    assert {
        "Z_original",
        "Z_N",
        "normalized_Z",
        "TT",
        "WSF",
        "TT_hat",
        "WSF_hat",
        "zero_shortfall_entity_rate",
        "Theta_I",
        "Omega_I",
        "alpha_I",
        "beta_I",
    }.issubset(per_instance[0])

    summary_rows = _read_csv(output_dir / "results_summary.csv")
    assert {"mean_Z_N", "mean_normalized_Z", "mean_TT_hat", "mean_WSF_hat"}.issubset(summary_rows[0])

    mechanism_rows = _read_csv(output_dir / "mechanism_stats.csv")
    assert {"trigger_count", "trigger_ratio", "algorithm_call_count", "number_of_events", "number_of_decision_events"}.issubset(
        mechanism_rows[0]
    )
    assert all(float(row["trigger_ratio"]) <= 1.0 for row in mechanism_rows)

    config_used = yaml.safe_load((output_dir / "config_used.yaml").read_text(encoding="utf-8"))
    assert config_used["rg_ralns"]["H_A"] == 4
    assert config_used["rg_ralns"]["N_A"] == 2
    assert config_used["rg_ralns"]["bottleneck_trigger_mode"] == "normal"
    assert config_used["objective"]["beta_0"] == 20.0

    calibration_rows = _read_csv(output_dir / "objective_calibration.csv")
    assert calibration_rows
    assert {"instance_id", "Theta_I", "Omega_I", "alpha_0", "beta_0", "alpha_I", "beta_I"}.issubset(
        calibration_rows[0]
    )

    sensitivity_rows = _read_csv(output_dir / "beta_sensitivity_summary.csv")
    assert sensitivity_rows
    assert {float(row["beta_0"]) for row in sensitivity_rows} == {1.0, 5.0, 20.0}
    assert {
        "beta_0",
        "algorithm",
        "mean_Z_N",
        "mean_TT",
        "mean_WSF",
        "mean_TT_hat",
        "mean_WSF_hat",
        "mean_ZSR",
        "mean_runtime",
        "rank_by_Z_N",
    }.issubset(sensitivity_rows[0])


def test_protocol_statement_is_available_for_paper_text():
    assert "same online event-driven simulation protocol" in PROTOCOL_STATEMENT
    assert "only operations that are immediately executable" in PROTOCOL_STATEMENT
