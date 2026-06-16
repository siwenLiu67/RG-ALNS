"""Tests for the Paper A Stage 2-pre experiment pipeline helpers."""

from __future__ import annotations

import csv
import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_script(script_name: str):
    script_path = PROJECT_ROOT / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(script_name[:-3], script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fieldnames.append(key)
                seen.add(key)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_experiment_suite_normalizes_requested_algorithm_names():
    suite = _load_script("run_paper_a_experiment_suite.py")

    assert suite.normalize_algorithm_key("EDD") == "edd"
    assert suite.normalize_algorithm_key("Lightweight_RG_Dispatch") == "lightweight_rg_dispatch"
    assert suite.normalize_algorithm_key("Online_Legacy_ALNS") == "online_legacy_rg_alns"
    assert suite.normalize_algorithm_key("RG_RALNS") == "rg_ralns"


def test_summarizer_generates_paper_tables_and_statistics(tmp_path: Path):
    summarizer = _load_script("summarize_paper_a_results.py")
    input_dir = tmp_path / "benchmark"
    output_dir = tmp_path / "tables"

    per_instance_rows = [
        {
            "instance": "tiny",
            "instance_index": 0,
            "seed": 0,
            "algorithm": "rg_ralns",
            "algorithm_label": "RG-RALNS",
            "table_group": "main_online",
            "status": "OK",
            "Z_N": 0.10,
            "TT": 10,
            "WSF": 0,
            "TT_hat": 0.10,
            "WSF_hat": 0,
            "ZSR": 1.0,
            "runtime": 0.05,
        },
        {
            "instance": "tiny",
            "instance_index": 0,
            "seed": 0,
            "algorithm": "online_legacy_rg_alns",
            "algorithm_label": "Online-Legacy-ALNS",
            "table_group": "main_online",
            "status": "OK",
            "Z_N": 0.20,
            "TT": 8,
            "WSF": 1,
            "TT_hat": 0.08,
            "WSF_hat": 0.01,
            "ZSR": 0.5,
            "runtime": 1.5,
        },
        {
            "instance": "tiny",
            "instance_index": 0,
            "seed": 1,
            "algorithm": "rg_ralns",
            "algorithm_label": "RG-RALNS",
            "table_group": "main_online",
            "status": "OK",
            "Z_N": 0.30,
            "TT": 20,
            "WSF": 1,
            "TT_hat": 0.20,
            "WSF_hat": 0.01,
            "ZSR": 0.5,
            "runtime": 0.06,
        },
        {
            "instance": "tiny",
            "instance_index": 0,
            "seed": 1,
            "algorithm": "online_legacy_rg_alns",
            "algorithm_label": "Online-Legacy-ALNS",
            "table_group": "main_online",
            "status": "OK",
            "Z_N": 0.40,
            "TT": 18,
            "WSF": 2,
            "TT_hat": 0.18,
            "WSF_hat": 0.02,
            "ZSR": 0.5,
            "runtime": 1.6,
        },
    ]
    _write_csv(input_dir / "per_instance_results.csv", per_instance_rows)
    _write_csv(input_dir / "mechanism_stats.csv", [
        {
            "algorithm": "rg_ralns",
            "algorithm_label": "RG-RALNS",
            "table_group": "main_online",
            "trigger_count": 2,
            "trigger_ratio": 0.4,
            "avg_A_size": 5,
            "max_A_size": 8,
            "dispatch_fallback_count": 1,
            "rescue_fallback_success_count": 1,
            "ordinary_fallback_count": 0,
        }
    ])
    _write_csv(input_dir / "beta_sensitivity_summary.csv", [
        {
            "beta_0": 20,
            "algorithm": "rg_ralns",
            "algorithm_label": "RG-RALNS",
            "table_group": "main_online",
            "mean_Z_N": 0.20,
            "mean_TT": 15,
            "mean_WSF": 0.5,
            "mean_ZSR": 0.75,
            "mean_runtime": 0.055,
        },
        {
            "beta_0": 20,
            "algorithm": "online_legacy_rg_alns",
            "algorithm_label": "Online-Legacy-ALNS",
            "table_group": "main_online",
            "mean_Z_N": 0.30,
            "mean_TT": 13,
            "mean_WSF": 1.5,
            "mean_ZSR": 0.5,
            "mean_runtime": 1.55,
        },
    ])

    outputs = summarizer.generate_tables(input_dir, output_dir)

    expected = {
        "table_main_comparison.csv",
        "table_beta_sensitivity.csv",
        "table_ablation.csv",
        "table_mechanism_stats.csv",
        "table_scalability.csv",
        "table_seed_robustness.csv",
        "table_statistical_tests.csv",
        "missing_inputs.csv",
    }
    assert {path.name for path in outputs.values()} == expected
    for filename in expected:
        assert (output_dir / filename).exists()

    main = _read_csv(output_dir / "table_main_comparison.csv")
    rg_row = next(row for row in main if row["algorithm"] == "rg_ralns")
    assert float(rg_row["mean_Z_N"]) == 0.20
    assert "ci95_low_Z_N" in rg_row
    assert "avg_rank_Z_N" in rg_row

    robustness = _read_csv(output_dir / "table_seed_robustness.csv")
    seed_one_rg = next(
        row for row in robustness
        if row["algorithm"] == "rg_ralns" and row["seed"] == "1"
    )
    assert seed_one_rg["is_service_outlier"] == "True"

    stats = _read_csv(output_dir / "table_statistical_tests.csv")
    assert any(
        row["algorithm"] == "rg_ralns"
        and row["baseline_algorithm"] == "online_legacy_rg_alns"
        and row["metric"] == "Z_N"
        for row in stats
    )
