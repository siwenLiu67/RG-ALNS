"""Tests for the Paper A online benchmark runner protocol."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
import yaml

from src.experiments.paper_a_online_protocol import (
    PROTOCOL_STATEMENT,
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
        "rg_ralns": {"H_A": 6, "N_A": 3},
        "legacy_rg_alns": {"horizon": 80, "lns_iterations": 2},
    }
    path.write_text(yaml.safe_dump(config), encoding="utf-8")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


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

    mechanism_rows = _read_csv(output_dir / "mechanism_stats.csv")
    assert {"trigger_count", "trigger_ratio", "algorithm_call_count", "number_of_events", "number_of_decision_events"}.issubset(
        mechanism_rows[0]
    )
    assert all(float(row["trigger_ratio"]) <= 1.0 for row in mechanism_rows)

    config_used = yaml.safe_load((output_dir / "config_used.yaml").read_text(encoding="utf-8"))
    assert config_used["rg_ralns"]["H_A"] == 4
    assert config_used["rg_ralns"]["N_A"] == 2
    assert config_used["rg_ralns"]["bottleneck_trigger_mode"] == "normal"


def test_protocol_statement_is_available_for_paper_text():
    assert "same online event-driven simulation protocol" in PROTOCOL_STATEMENT
    assert "only operations that are immediately executable" in PROTOCOL_STATEMENT
