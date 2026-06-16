#!/usr/bin/env python3
"""Generate paper-ready CSV tables from Paper A benchmark outputs."""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


METRICS = ["Z_N", "TT", "WSF", "TT_hat", "WSF_hat", "ZSR", "runtime"]
MECHANISM_FIELDS = [
    "trigger_count",
    "trigger_ratio",
    "avg_A_size",
    "max_A_size",
    "alns_runtime_total",
    "dispatch_fallback_count",
    "rescue_fallback_success_count",
    "ordinary_fallback_count",
    "local_extraction_success_count",
    "affected_set_rescue_success_count",
    "rescue_machine_contention_events",
]
BASELINE_COMPARISONS = [
    "online_legacy_rg_alns",
    "lightweight_rg_dispatch",
    "edd",
]


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fieldnames.append(key)
                seen.add(key)
    if not fieldnames:
        fieldnames = ["empty"]
        rows = [{"empty": ""}]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _values(rows: Iterable[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = _as_float(row.get(key))
        if value is not None and math.isfinite(value):
            values.append(value)
    return values


def _stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "n": 0,
            "mean": "",
            "std": "",
            "se": "",
            "ci95_low": "",
            "ci95_high": "",
        }
    mean_value = statistics.fmean(values)
    std_value = statistics.stdev(values) if len(values) > 1 else 0.0
    se_value = std_value / math.sqrt(len(values)) if values else 0.0
    margin = 1.96 * se_value
    return {
        "n": len(values),
        "mean": mean_value,
        "std": std_value,
        "se": se_value,
        "ci95_low": mean_value - margin,
        "ci95_high": mean_value + margin,
    }


def _group_rows(
    rows: Iterable[dict[str, str]],
    keys: tuple[str, ...],
) -> dict[tuple[str, ...], list[dict[str, str]]]:
    grouped: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(row.get(key, "") for key in keys)].append(row)
    return grouped


def _ok_main_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        row for row in rows
        if row.get("table_group", "main_online") == "main_online"
        and row.get("status", "OK") == "OK"
    ]


def _paired_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        row.get("instance", ""),
        row.get("instance_index", ""),
        row.get("seed", ""),
    )


def _rank_info(rows: list[dict[str, str]]) -> tuple[dict[str, int], dict[str, float]]:
    best_counts: dict[str, int] = defaultdict(int)
    ranks: dict[str, list[int]] = defaultdict(list)
    by_instance: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if _as_float(row.get("Z_N")) is not None:
            by_instance[_paired_key(row)].append(row)
    for group_rows in by_instance.values():
        ranked = sorted(
            group_rows,
            key=lambda row: (_as_float(row.get("Z_N")) or math.inf, row.get("algorithm", "")),
        )
        for rank, row in enumerate(ranked, start=1):
            ranks[row["algorithm"]].append(rank)
            if rank == 1:
                best_counts[row["algorithm"]] += 1
    avg_ranks = {
        algorithm: statistics.fmean(values)
        for algorithm, values in ranks.items()
    }
    return dict(best_counts), avg_ranks


def _main_comparison_rows(per_instance_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows = _ok_main_rows(per_instance_rows)
    best_counts, avg_ranks = _rank_info(rows)
    grouped = _group_rows(rows, ("algorithm", "algorithm_label", "table_group"))
    output: list[dict[str, Any]] = []
    for (algorithm, label, table_group), group_rows in sorted(grouped.items()):
        row: dict[str, Any] = {
            "algorithm": algorithm,
            "algorithm_label": label,
            "table_group": table_group,
            "runs": len(group_rows),
            "best_count_Z_N": best_counts.get(algorithm, 0),
            "avg_rank_Z_N": avg_ranks.get(algorithm, ""),
        }
        for metric in METRICS:
            stats = _stats(_values(group_rows, metric))
            row[f"mean_{metric}"] = stats["mean"]
            row[f"std_{metric}"] = stats["std"]
            row[f"se_{metric}"] = stats["se"]
            row[f"ci95_low_{metric}"] = stats["ci95_low"]
            row[f"ci95_high_{metric}"] = stats["ci95_high"]
        output.append(row)
    ranked = sorted(
        [row for row in output if row.get("mean_Z_N") != ""],
        key=lambda row: (float(row["mean_Z_N"]), row["algorithm"]),
    )
    rank_by_algorithm = {
        row["algorithm"]: rank
        for rank, row in enumerate(ranked, start=1)
    }
    for row in output:
        row["rank_by_mean_Z_N"] = rank_by_algorithm.get(row["algorithm"], "")
    return output


def _relative_improvement(value: Any, baseline_value: Any, *, maximize: bool = False) -> float | str:
    value_f = _as_float(value)
    baseline_f = _as_float(baseline_value)
    if value_f is None or baseline_f is None or abs(baseline_f) <= 1e-12:
        return ""
    if maximize:
        return (value_f - baseline_f) / abs(baseline_f) * 100.0
    return (baseline_f - value_f) / abs(baseline_f) * 100.0


def _beta_sensitivity_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    grouped_by_beta = _group_rows(rows, ("beta_0",))
    output: list[dict[str, Any]] = []
    for (beta_0,), beta_rows in sorted(grouped_by_beta.items(), key=lambda item: float(item[0][0])):
        values = {row["algorithm"]: row for row in beta_rows if row.get("table_group", "main_online") == "main_online"}
        ranked = sorted(
            [row for row in beta_rows if _as_float(row.get("mean_Z_N")) is not None],
            key=lambda row: (_as_float(row.get("mean_Z_N")) or math.inf, row.get("algorithm", "")),
        )
        rank_by_algorithm = {
            row["algorithm"]: rank
            for rank, row in enumerate(ranked, start=1)
        }
        for row in beta_rows:
            copied = dict(row)
            copied["rank_by_Z_N"] = row.get("rank_by_Z_N") or rank_by_algorithm.get(row.get("algorithm", ""), "")
            for baseline_key, column in (
                ("online_legacy_rg_alns", "relative_improvement_vs_Online_Legacy_ALNS"),
                ("lightweight_rg_dispatch", "relative_improvement_vs_Lightweight_RG"),
                ("edd", "relative_improvement_vs_EDD"),
            ):
                copied[column] = _relative_improvement(
                    row.get("mean_Z_N"),
                    values.get(baseline_key, {}).get("mean_Z_N"),
                )
            output.append(copied)
    return output


def _mechanism_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped = _group_rows(rows, ("algorithm", "algorithm_label", "table_group"))
    output: list[dict[str, Any]] = []
    for (algorithm, label, table_group), group_rows in sorted(grouped.items()):
        row: dict[str, Any] = {
            "algorithm": algorithm,
            "algorithm_label": label,
            "table_group": table_group,
            "runs": len(group_rows),
        }
        for field in MECHANISM_FIELDS:
            stats = _stats(_values(group_rows, field))
            row[f"mean_{field}"] = stats["mean"]
            row[f"std_{field}"] = stats["std"]
        output.append(row)
    return output


def _seed_robustness_rows(
    per_instance_rows: list[dict[str, str]],
    *,
    wsf_threshold: float,
    zsr_threshold: float,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in _ok_main_rows(per_instance_rows):
        wsf = _as_float(row.get("WSF"))
        zsr = _as_float(row.get("ZSR"))
        is_outlier = (
            (wsf is not None and wsf > wsf_threshold)
            or (zsr is not None and zsr < zsr_threshold)
        )
        output.append({
            "instance": row.get("instance", ""),
            "instance_index": row.get("instance_index", ""),
            "seed": row.get("seed", ""),
            "algorithm": row.get("algorithm", ""),
            "algorithm_label": row.get("algorithm_label", ""),
            "Z_N": row.get("Z_N", ""),
            "TT": row.get("TT", ""),
            "WSF": row.get("WSF", ""),
            "ZSR": row.get("ZSR", ""),
            "runtime": row.get("runtime", ""),
            "is_service_outlier": is_outlier,
        })
    return output


def _scalability_rows(per_instance_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows = _ok_main_rows(per_instance_rows)
    grouped = _group_rows(rows, ("instance", "algorithm", "algorithm_label"))
    output: list[dict[str, Any]] = []
    for (scale_label, algorithm, label), group_rows in sorted(grouped.items()):
        row: dict[str, Any] = {
            "scale_label": scale_label,
            "algorithm": algorithm,
            "algorithm_label": label,
            "runs": len(group_rows),
        }
        for metric in ("Z_N", "TT", "WSF", "ZSR", "runtime"):
            row[f"mean_{metric}"] = _stats(_values(group_rows, metric))["mean"]
        output.append(row)
    return output


def _try_scipy_tests(algorithm_values: list[float], baseline_values: list[float]) -> tuple[Any, Any]:
    try:
        from scipy import stats  # type: ignore
    except Exception:
        return "", ""
    try:
        ttest = stats.ttest_rel(algorithm_values, baseline_values).pvalue
    except Exception:
        ttest = ""
    try:
        wilcoxon = stats.wilcoxon(algorithm_values, baseline_values).pvalue
    except Exception:
        wilcoxon = ""
    return ttest, wilcoxon


def _statistical_test_rows(per_instance_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows = _ok_main_rows(per_instance_rows)
    by_algorithm: dict[str, dict[tuple[str, str, str], dict[str, str]]] = defaultdict(dict)
    labels: dict[str, str] = {}
    for row in rows:
        algorithm = row.get("algorithm", "")
        labels[algorithm] = row.get("algorithm_label", algorithm)
        by_algorithm[algorithm][_paired_key(row)] = row

    rg_rows = by_algorithm.get("rg_ralns", {})
    output: list[dict[str, Any]] = []
    for baseline in BASELINE_COMPARISONS:
        baseline_rows = by_algorithm.get(baseline, {})
        common_keys = sorted(set(rg_rows) & set(baseline_rows))
        if not common_keys:
            continue
        for metric in METRICS:
            algorithm_values: list[float] = []
            baseline_values: list[float] = []
            for key in common_keys:
                alg_value = _as_float(rg_rows[key].get(metric))
                base_value = _as_float(baseline_rows[key].get(metric))
                if alg_value is None or base_value is None:
                    continue
                algorithm_values.append(alg_value)
                baseline_values.append(base_value)
            if not algorithm_values:
                continue
            mean_algorithm = statistics.fmean(algorithm_values)
            mean_baseline = statistics.fmean(baseline_values)
            diffs = [
                alg - base
                for alg, base in zip(algorithm_values, baseline_values, strict=True)
            ]
            p_ttest, p_wilcoxon = _try_scipy_tests(algorithm_values, baseline_values)
            output.append({
                "metric": metric,
                "algorithm": "rg_ralns",
                "algorithm_label": labels.get("rg_ralns", "RG-RALNS"),
                "baseline_algorithm": baseline,
                "baseline_algorithm_label": labels.get(baseline, baseline),
                "mean_algorithm": mean_algorithm,
                "mean_baseline": mean_baseline,
                "mean_difference": statistics.fmean(diffs),
                "relative_improvement_percent": _relative_improvement(
                    mean_algorithm,
                    mean_baseline,
                    maximize=(metric == "ZSR"),
                ),
                "p_value_paired_ttest": p_ttest,
                "p_value_wilcoxon": p_wilcoxon,
                "n": len(algorithm_values),
            })
    return output


def _missing_row(table: str, expected_path: Path, message: str) -> dict[str, Any]:
    return {
        "table": table,
        "status": "missing required input",
        "expected_path": str(expected_path),
        "message": message,
    }


def generate_tables(
    input_dir: str | Path,
    output_dir: str | Path,
    *,
    service_outlier_wsf_threshold: float = 0.0,
    service_outlier_zsr_threshold: float = 1.0,
) -> dict[str, Path]:
    """Read one benchmark output folder and generate paper table CSVs."""

    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "main_comparison": output_dir / "table_main_comparison.csv",
        "beta_sensitivity": output_dir / "table_beta_sensitivity.csv",
        "ablation": output_dir / "table_ablation.csv",
        "mechanism_stats": output_dir / "table_mechanism_stats.csv",
        "scalability": output_dir / "table_scalability.csv",
        "seed_robustness": output_dir / "table_seed_robustness.csv",
        "statistical_tests": output_dir / "table_statistical_tests.csv",
        "missing_inputs": output_dir / "missing_inputs.csv",
    }
    missing: list[dict[str, Any]] = []

    per_instance_path = input_dir / "per_instance_results.csv"
    per_instance_rows = _read_csv(per_instance_path)
    if per_instance_rows:
        _write_csv(outputs["main_comparison"], _main_comparison_rows(per_instance_rows))
        _write_csv(outputs["seed_robustness"], _seed_robustness_rows(
            per_instance_rows,
            wsf_threshold=service_outlier_wsf_threshold,
            zsr_threshold=service_outlier_zsr_threshold,
        ))
        _write_csv(outputs["scalability"], _scalability_rows(per_instance_rows))
        _write_csv(outputs["statistical_tests"], _statistical_test_rows(per_instance_rows))
    else:
        for key in ("main_comparison", "seed_robustness", "scalability", "statistical_tests"):
            row = _missing_row(key, per_instance_path, "per_instance_results.csv is required")
            _write_csv(outputs[key], [row])
            missing.append(row)

    beta_path = input_dir / "beta_sensitivity_summary.csv"
    beta_rows = _read_csv(beta_path)
    if beta_rows:
        _write_csv(outputs["beta_sensitivity"], _beta_sensitivity_rows(beta_rows))
    else:
        row = _missing_row("beta_sensitivity", beta_path, "beta_sensitivity_summary.csv is required")
        _write_csv(outputs["beta_sensitivity"], [row])
        missing.append(row)

    mechanism_path = input_dir / "mechanism_stats.csv"
    mechanism_rows = _read_csv(mechanism_path)
    if mechanism_rows:
        _write_csv(outputs["mechanism_stats"], _mechanism_rows(mechanism_rows))
    else:
        row = _missing_row("mechanism_stats", mechanism_path, "mechanism_stats.csv is required")
        _write_csv(outputs["mechanism_stats"], [row])
        missing.append(row)

    ablation_path = input_dir / "ablation_results.csv"
    ablation_rows = _read_csv(ablation_path)
    if ablation_rows:
        _write_csv(outputs["ablation"], ablation_rows)
    else:
        row = _missing_row(
            "ablation",
            ablation_path,
            "Ablation variants were not run in this input folder.",
        )
        _write_csv(outputs["ablation"], [row])
        missing.append(row)

    _write_csv(outputs["missing_inputs"], missing)
    return outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--service-outlier-wsf-threshold", type=float, default=0.0)
    parser.add_argument("--service-outlier-zsr-threshold", type=float, default=1.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    outputs = generate_tables(
        args.input,
        args.output,
        service_outlier_wsf_threshold=args.service_outlier_wsf_threshold,
        service_outlier_zsr_threshold=args.service_outlier_zsr_threshold,
    )
    for name, path in outputs.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
