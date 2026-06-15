#!/usr/bin/env python3
"""Summarize Paper A benchmark results into paper-ready tables.

Reads per-instance and mechanism CSV files from one or more benchmark output
directories and produces paper-ready summary tables with descriptive statistics,
statistical tests (if scipy is available), and relative improvement columns.

Output tables:
  table_main_comparison.csv
  table_beta_sensitivity.csv
  table_ablation.csv
  table_mechanism_stats.csv
  table_scalability.csv
  table_seed_robustness.csv
  table_statistical_tests.csv
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    from scipy.stats import ttest_rel, wilcoxon
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False


# ---------------------------------------------------------------------------
# Descriptive statistics
# ---------------------------------------------------------------------------

def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else float("nan")


def _std(values: list[float], ddof: int = 1) -> float:
    n = len(values)
    if n < 2:
        return float("nan")
    m = _mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (n - ddof))


def _stderr(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return float("nan")
    s = _std(values)
    return s / math.sqrt(n)


def _ci95(values: list[float]) -> tuple[float, float]:
    """95% confidence interval using t-distribution (1.96 approx for large n)."""
    n = len(values)
    if n < 2:
        return (float("nan"), float("nan"))
    m = _mean(values)
    se = _stderr(values)
    # Use 1.96 for normal approximation; for small n use t-critical
    if n < 30:
        try:
            from scipy.stats import t as t_dist
            t_crit = t_dist.ppf(0.975, n - 1)
        except ImportError:
            t_crit = 1.96
    else:
        t_crit = 1.96
    half_width = t_crit * se
    return (m - half_width, m + half_width)


def _relative_improvement(alg_val: float, baseline_val: float) -> float | str:
    """Relative improvement of algorithm over baseline: (baseline - alg) / baseline * 100."""
    if abs(baseline_val) < 1e-12:
        return ""
    return (baseline_val - alg_val) / baseline_val * 100.0


# ---------------------------------------------------------------------------
# Statistical tests
# ---------------------------------------------------------------------------

def _paired_ttest(x: list[float], y: list[float]) -> float | None:
    if not _HAS_SCIPY or len(x) < 3 or len(x) != len(y):
        return None
    try:
        _stat, p = ttest_rel(x, y)
        return float(p)
    except Exception:
        return None


def _wilcoxon_p(x: list[float], y: list[float]) -> float | None:
    if not _HAS_SCIPY or len(x) < 3 or len(x) != len(y):
        return None
    try:
        _stat, p = wilcoxon(x, y, zero_method="zsplit")
        return float(p)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def _read_csv(path: str | Path) -> list[dict[str, str]]:
    with open(path, "r", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        print(f"  [WARN] No rows to write for {path}")
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    # Collect all fieldnames across all rows for consistency
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
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _find_csv_files(input_dir: Path) -> dict[str, Path]:
    """Find all per_instance_results.csv files in the input directory tree."""
    result: dict[str, Path] = {}
    for root, _dirs, files in os.walk(input_dir):
        for fname in files:
            if fname == "per_instance_results.csv":
                # Use relative path as key
                rel = str(Path(root).relative_to(input_dir))
                key = rel if rel != "." else "__root__"
                result[key] = Path(root) / fname
    return result


def _load_per_instance_data(input_dir: Path) -> list[dict[str, Any]]:
    """Load and merge all per-instance rows from an input directory."""
    all_rows: list[dict[str, Any]] = []
    csv_files = _find_csv_files(input_dir)
    if not csv_files:
        print(f"  [WARN] No per_instance_results.csv found under {input_dir}")
        return all_rows
    for source_key, path in sorted(csv_files.items()):
        try:
            rows = _read_csv(path)
            for row in rows:
                row["_source"] = source_key
            all_rows.extend(rows)
        except Exception as exc:
            print(f"  [WARN] Failed to read {path}: {exc}")
    return all_rows


# ---------------------------------------------------------------------------
# Table generators
# ---------------------------------------------------------------------------

def _algorithm_label(alg_key: str) -> str:
    labels = {
        "edd": "EDD",
        "spt": "SPT",
        "wspt": "WSPT",
        "atc": "ATC",
        "swd": "SWD",
        "sfg": "SFG",
        "lightweight_rg_dispatch": "Lightweight RG Dispatch",
        "online_legacy_rg_alns": "Online-Legacy-ALNS",
        "rg_ralns": "RG-RALNS",
        "offline_legacy_rg_alns": "Offline-Legacy-ALNS",
        "online_ils": "Online-ILS",
        "online_vns": "Online-VNS",
        "online_ts": "Online-TS",
        "online_sa": "Online-SA",
        "online_ga": "Online-GA",
    }
    return labels.get(alg_key, alg_key)


def _float_val(row: dict[str, Any], key: str) -> float | None:
    val = row.get(key, "")
    if val == "" or val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _group_by_algorithm(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        algo = row.get("algorithm", "unknown")
        groups[algo].append(row)
    return dict(groups)


def generate_table_main_comparison(
    per_instance_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Generate the main comparison table with descriptive stats."""
    groups = _group_by_algorithm(per_instance_rows)
    summary: list[dict[str, Any]] = []

    for algo_key in sorted(groups.keys()):
        algo_rows = [r for r in groups[algo_key] if r.get("status") == "OK"]
        if not algo_rows:
            continue

        z_n_vals = [_float_val(r, "Z_N") for r in algo_rows]
        z_n_vals = [v for v in z_n_vals if v is not None]
        tt_vals = [_float_val(r, "TT") for r in algo_rows]
        tt_vals = [v for v in tt_vals if v is not None]
        wsf_vals = [_float_val(r, "WSF") for r in algo_rows]
        wsf_vals = [v for v in wsf_vals if v is not None]
        tt_hat_vals = [_float_val(r, "TT_hat") for r in algo_rows]
        tt_hat_vals = [v for v in tt_hat_vals if v is not None]
        wsf_hat_vals = [_float_val(r, "WSF_hat") for r in algo_rows]
        wsf_hat_vals = [v for v in wsf_hat_vals if v is not None]
        zsr_vals = [_float_val(r, "ZSR") for r in algo_rows]
        zsr_vals = [v for v in zsr_vals if v is not None]
        runtime_vals = [_float_val(r, "runtime") for r in algo_rows]
        runtime_vals = [v for v in runtime_vals if v is not None]

        z_n_ci = _ci95(z_n_vals)
        row = {
            "algorithm": algo_key,
            "algorithm_label": _algorithm_label(algo_key),
            "n": len(algo_rows),
            "mean_Z_N": _mean(z_n_vals),
            "std_Z_N": _std(z_n_vals),
            "se_Z_N": _stderr(z_n_vals),
            "ci95_lower_Z_N": z_n_ci[0],
            "ci95_upper_Z_N": z_n_ci[1],
            "mean_TT": _mean(tt_vals),
            "std_TT": _std(tt_vals),
            "mean_WSF": _mean(wsf_vals),
            "std_WSF": _std(wsf_vals),
            "mean_TT_hat": _mean(tt_hat_vals),
            "mean_WSF_hat": _mean(wsf_hat_vals),
            "mean_ZSR": _mean(zsr_vals),
            "std_ZSR": _std(zsr_vals),
            "mean_runtime": _mean(runtime_vals),
            "std_runtime": _std(runtime_vals),
            # Per-instance WSF/ZSR for service outlier detection
            "instances_WSF_gt_0": sum(1 for v in wsf_vals if v > 0),
            "instances_ZSR_lt_1": sum(1 for v in zsr_vals if v < 1),
        }
        summary.append(row)

    # Rank by Z_N
    ranked = sorted(summary, key=lambda r: r["mean_Z_N"])
    for rank, r in enumerate(ranked, start=1):
        r["rank_by_Z_N"] = rank

    # Add RG-RALNS relative gaps
    _add_rg_gaps(summary)

    return summary


def _add_rg_gaps(rows: list[dict[str, Any]]) -> None:
    """Add relative improvement columns for RG-RALNS vs key baselines."""
    # Pre-initialize all gap columns on all rows
    gap_columns = [
        "RG_vs_OnlineLegacyALNS_improvement_pct",
        "RG_vs_LightweightRG_improvement_pct",
        "RG_vs_EDD_improvement_pct",
        "vs_EDD_improvement_pct",
    ]
    for row in rows:
        for col in gap_columns:
            row.setdefault(col, "")

    rg_row = next((r for r in rows if r["algorithm"] == "rg_ralns"), None)
    if rg_row is not None:
        rg_z = rg_row["mean_Z_N"]
        for baseline_key, col_name in [
            ("online_legacy_rg_alns", "RG_vs_OnlineLegacyALNS_improvement_pct"),
            ("lightweight_rg_dispatch", "RG_vs_LightweightRG_improvement_pct"),
            ("edd", "RG_vs_EDD_improvement_pct"),
        ]:
            baseline_row = next((r for r in rows if r["algorithm"] == baseline_key), None)
            if baseline_row:
                rg_row[col_name] = _relative_improvement(rg_z, baseline_row["mean_Z_N"])
            else:
                rg_row[col_name] = ""

    # Also add improvements for each row relative to EDD
    edd_row = next((r for r in rows if r["algorithm"] == "edd"), None)
    if edd_row:
        edd_z = edd_row["mean_Z_N"]
        for r in rows:
            if r["algorithm"] != "edd":
                r["vs_EDD_improvement_pct"] = _relative_improvement(r["mean_Z_N"], edd_z)
            else:
                r["vs_EDD_improvement_pct"] = 0.0


def generate_table_beta_sensitivity(
    per_instance_rows: list[dict[str, Any]],
    beta_values: list[float] | None = None,
    alpha_0: float = 1.0,
) -> list[dict[str, Any]]:
    """Generate beta sensitivity table from per-instance rows.

    Re-computes Z_N for each beta_0 using the stored TT_hat and WSF_hat values.
    """
    if beta_values is None:
        beta_values = [1, 5, 10, 20, 50, 100]

    groups = _group_by_algorithm(per_instance_rows)
    table_rows: list[dict[str, Any]] = []

    for beta_0 in beta_values:
        for algo_key in sorted(groups.keys()):
            algo_rows = [r for r in groups[algo_key] if r.get("status") == "OK"]
            if not algo_rows:
                continue

            tt_hat_vals = [_float_val(r, "TT_hat") for r in algo_rows]
            tt_hat_vals = [v for v in tt_hat_vals if v is not None]
            wsf_hat_vals = [_float_val(r, "WSF_hat") for r in algo_rows]
            wsf_hat_vals = [v for v in wsf_hat_vals if v is not None]

            # Recompute Z_N at this beta_0
            z_n_vals = []
            for tt_h, wsf_h in zip(tt_hat_vals, wsf_hat_vals):
                z_n_vals.append(alpha_0 * tt_h + beta_0 * wsf_h)

            tt_vals = [_float_val(r, "TT") for r in algo_rows]
            tt_vals = [v for v in tt_vals if v is not None]
            wsf_vals = [_float_val(r, "WSF") for r in algo_rows]
            wsf_vals = [v for v in wsf_vals if v is not None]
            zsr_vals = [_float_val(r, "ZSR") for r in algo_rows]
            zsr_vals = [v for v in zsr_vals if v is not None]
            runtime_vals = [_float_val(r, "runtime") for r in algo_rows]
            runtime_vals = [v for v in runtime_vals if v is not None]

            row = {
                "beta_0": beta_0,
                "algorithm": algo_key,
                "algorithm_label": _algorithm_label(algo_key),
                "n": len(algo_rows),
                "mean_Z_N": _mean(z_n_vals),
                "std_Z_N": _std(z_n_vals),
                "mean_TT": _mean(tt_vals),
                "mean_WSF": _mean(wsf_vals),
                "mean_WSF_hat": _mean(wsf_hat_vals),
                "mean_TT_hat": _mean(tt_hat_vals),
                "mean_ZSR": _mean(zsr_vals),
                "mean_runtime": _mean(runtime_vals),
            }
            table_rows.append(row)

    # Rank by Z_N within each beta_0
    beta_groups: dict[float, list[dict[str, Any]]] = defaultdict(list)
    for row in table_rows:
        beta_groups[row["beta_0"]].append(row)

    for beta_0, group in beta_groups.items():
        ranked = sorted(group, key=lambda r: r["mean_Z_N"])
        for rank, r in enumerate(ranked, start=1):
            r["rank_by_Z_N"] = rank

    # Add relative improvements
    for beta_0, group in beta_groups.items():
        online_legacy = next((r for r in group if r["algorithm"] == "online_legacy_rg_alns"), None)
        lightweight = next((r for r in group if r["algorithm"] == "lightweight_rg_dispatch"), None)
        rg = next((r for r in group if r["algorithm"] == "rg_ralns"), None)
        for r in group:
            if online_legacy:
                r["vs_OnlineLegacyALNS_improvement_pct"] = _relative_improvement(
                    r["mean_Z_N"], online_legacy["mean_Z_N"]
                )
            if lightweight:
                r["vs_LightweightRG_improvement_pct"] = _relative_improvement(
                    r["mean_Z_N"], lightweight["mean_Z_N"]
                )
            if rg and r["algorithm"] != "rg_ralns":
                r["vs_RGRALNS_gap_pct"] = _relative_improvement(rg["mean_Z_N"], r["mean_Z_N"])

    return table_rows


def generate_table_ablation(
    per_instance_rows: list[dict[str, Any]],
    variant_labels: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Generate ablation study table.

    Variants are identified by their _source directory key.
    """
    if variant_labels is None:
        variant_labels = {}

    # Group by _source (variant)
    source_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in per_instance_rows:
        source = row.get("_source", "__root__")
        source_groups[source].append(row)

    table_rows: list[dict[str, Any]] = []
    for source_key in sorted(source_groups.keys()):
        algo_rows = [r for r in source_groups[source_key] if r.get("status") == "OK"]
        if not algo_rows:
            continue

        # Get the algorithm(s) in this variant
        algos_in_source = set(r.get("algorithm", "") for r in algo_rows)
        variant_label = variant_labels.get(source_key, source_key)

        for algo_key in sorted(algos_in_source):
            sub_rows = [r for r in algo_rows if r.get("algorithm") == algo_key]
            z_n_vals = [_float_val(r, "Z_N") for r in sub_rows]
            z_n_vals = [v for v in z_n_vals if v is not None]
            tt_vals = [_float_val(r, "TT") for r in sub_rows]
            tt_vals = [v for v in tt_vals if v is not None]
            wsf_vals = [_float_val(r, "WSF") for r in sub_rows]
            wsf_vals = [v for v in wsf_vals if v is not None]
            zsr_vals = [_float_val(r, "ZSR") for r in sub_rows]
            zsr_vals = [v for v in zsr_vals if v is not None]
            runtime_vals = [_float_val(r, "runtime") for r in sub_rows]
            runtime_vals = [v for v in runtime_vals if v is not None]

            row = {
                "variant": source_key,
                "variant_label": variant_label,
                "algorithm": algo_key,
                "algorithm_label": _algorithm_label(algo_key),
                "n": len(sub_rows),
                "mean_Z_N": _mean(z_n_vals),
                "std_Z_N": _std(z_n_vals),
                "mean_TT": _mean(tt_vals),
                "mean_WSF": _mean(wsf_vals),
                "mean_ZSR": _mean(zsr_vals),
                "mean_runtime": _mean(runtime_vals),
            }
            table_rows.append(row)

    # Add relative difference vs Full RG-RALNS
    full_rg = next(
        (r for r in table_rows
         if "full" in r["variant"].lower() and r["algorithm"] == "rg_ralns"),
        None,
    )
    if full_rg:
        full_z = full_rg["mean_Z_N"]
        for r in table_rows:
            r["vs_Full_RG_RALNS_Z_N_diff"] = r["mean_Z_N"] - full_z
            r["vs_Full_RG_RALNS_improvement_pct"] = _relative_improvement(r["mean_Z_N"], full_z)

    return table_rows


def generate_table_mechanism_stats(
    input_dir: Path,
) -> list[dict[str, Any]]:
    """Generate mechanism analysis table from mechanism_stats.csv files."""
    all_rows: list[dict[str, Any]] = []
    for root, _dirs, files in os.walk(input_dir):
        for fname in files:
            if fname == "mechanism_stats.csv":
                path = Path(root) / fname
                try:
                    rows = _read_csv(path)
                    for r in rows:
                        r["_source"] = str(Path(root).relative_to(input_dir))
                    all_rows.extend(rows)
                except Exception as exc:
                    print(f"  [WARN] Failed to read {path}: {exc}")

    if not all_rows:
        print("  [WARN] No mechanism_stats.csv found")
        return []

    # Filter to RG-RALNS only
    rg_rows = [r for r in all_rows if r.get("algorithm") == "rg_ralns"]
    if not rg_rows:
        rg_rows = all_rows

    table_rows: list[dict[str, Any]] = []
    for row in rg_rows:
        mechanism_fields = [
            "trigger_count", "trigger_ratio", "avg_A_size", "max_A_size",
            "alns_runtime_total", "dispatch_fallback_count",
            "local_extraction_success_count", "affected_set_rescue_success_count",
            "rescue_fallback_count", "ordinary_fallback_count",
            "rescue_fallback_success_count", "algorithm_call_count",
            "number_of_events", "number_of_decision_events",
            "mandatory_precursor_in_A_count", "cover_precursor_in_A_count",
            "mandatory_precursor_selected_count", "cover_precursor_selected_count",
        ]
        entry: dict[str, Any] = {
            "algorithm": row.get("algorithm", ""),
            "instance": row.get("instance", ""),
            "seed": row.get("seed", ""),
            "_source": row.get("_source", ""),
        }
        for field in mechanism_fields:
            try:
                entry[field] = float(row.get(field, 0))
            except (ValueError, TypeError):
                entry[field] = row.get(field, "")
        table_rows.append(entry)

    # Add aggregate summary row
    if table_rows:
        agg: dict[str, Any] = {
            "algorithm": "RG-RALNS (aggregate)",
            "instance": "ALL",
            "seed": "ALL",
            "_source": "aggregate",
        }
        for field in mechanism_fields:
            vals = []
            for r in table_rows:
                v = r.get(field, "")
                if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v)):
                    vals.append(v)
            if vals:
                agg[field] = _mean(vals)
            else:
                agg[field] = ""
        table_rows.append(agg)

    return table_rows


def generate_table_scalability(
    per_instance_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Generate scalability table grouped by scale label."""
    # Scalability data comes from _source paths like "scalability/small"
    source_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in per_instance_rows:
        source = row.get("_source", "__root__")
        # Extract scale name from path
        parts = source.replace("\\", "/").split("/")
        scale_name = parts[-1] if len(parts) > 1 else source
        source_groups[scale_name].append(row)

    table_rows: list[dict[str, Any]] = []
    for scale_name in sorted(source_groups.keys()):
        algo_groups = _group_by_algorithm(source_groups[scale_name])
        for algo_key in sorted(algo_groups.keys()):
            algo_rows = [r for r in algo_groups[algo_key] if r.get("status") == "OK"]
            if not algo_rows:
                continue
            z_vals = [_float_val(r, "Z_N") for r in algo_rows]
            z_vals = [v for v in z_vals if v is not None]
            runtime_vals = [_float_val(r, "runtime") for r in algo_rows]
            runtime_vals = [v for v in runtime_vals if v is not None]

            row = {
                "scale": scale_name,
                "algorithm": algo_key,
                "algorithm_label": _algorithm_label(algo_key),
                "n": len(algo_rows),
                "mean_Z_N": _mean(z_vals),
                "std_Z_N": _std(z_vals),
                "mean_runtime": _mean(runtime_vals),
                "std_runtime": _std(runtime_vals),
            }
            table_rows.append(row)

    return table_rows


def generate_table_seed_robustness(
    per_instance_rows: list[dict[str, Any]],
    service_outlier_threshold_wsf: float = 0.0,
    service_outlier_threshold_zsr: float = 1.0,
) -> list[dict[str, Any]]:
    """Generate seed robustness table with per-seed diagnostics."""
    # Group by (algorithm, seed)
    seed_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in per_instance_rows:
        key = (row.get("algorithm", ""), row.get("seed", ""))
        seed_groups[key].append(row)

    table_rows: list[dict[str, Any]] = []
    for (algo_key, seed) in sorted(seed_groups.keys()):
        algo_rows = [r for r in seed_groups[(algo_key, seed)] if r.get("status") == "OK"]
        if not algo_rows:
            continue

        z_vals = [_float_val(r, "Z_N") for r in algo_rows]
        z_vals = [v for v in z_vals if v is not None]
        tt_vals = [_float_val(r, "TT") for r in algo_rows]
        tt_vals = [v for v in tt_vals if v is not None]
        wsf_vals = [_float_val(r, "WSF") for r in algo_rows]
        wsf_vals = [v for v in wsf_vals if v is not None]
        zsr_vals = [_float_val(r, "ZSR") for r in algo_rows]
        zsr_vals = [v for v in zsr_vals if v is not None]
        runtime_vals = [_float_val(r, "runtime") for r in algo_rows]
        runtime_vals = [v for v in runtime_vals if v is not None]

        # Service outlier detection
        is_outlier = False
        if wsf_vals:
            is_outlier = is_outlier or any(v > service_outlier_threshold_wsf for v in wsf_vals)
        if zsr_vals:
            is_outlier = is_outlier or any(v < service_outlier_threshold_zsr for v in zsr_vals)

        row = {
            "seed": int(seed) if seed.isdigit() or (seed.startswith("-") and seed[1:].isdigit()) else seed,
            "algorithm": algo_key,
            "algorithm_label": _algorithm_label(algo_key),
            "n_instances": len(algo_rows),
            "mean_Z_N": _mean(z_vals),
            "std_Z_N": _std(z_vals),
            "mean_TT": _mean(tt_vals),
            "mean_WSF": _mean(wsf_vals),
            "mean_ZSR": _mean(zsr_vals),
            "mean_runtime": _mean(runtime_vals),
            "is_service_outlier": is_outlier,
            "outlier_threshold_WSF": service_outlier_threshold_wsf,
            "outlier_threshold_ZSR": service_outlier_threshold_zsr,
        }
        table_rows.append(row)

    return table_rows


def generate_table_statistical_tests(
    per_instance_rows: list[dict[str, Any]],
    comparisons: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Generate statistical tests table for key algorithm pairs.

    Requires per-instance pairing (same instance_key + seed).
    """
    if comparisons is None:
        comparisons = [
            {"algorithm": "rg_ralns", "baseline": "online_legacy_rg_alns",
             "label": "RG-RALNS vs Online-Legacy-ALNS"},
            {"algorithm": "rg_ralns", "baseline": "lightweight_rg_dispatch",
             "label": "RG-RALNS vs Lightweight RG Dispatch"},
            {"algorithm": "rg_ralns", "baseline": "edd",
             "label": "RG-RALNS vs EDD"},
            {"algorithm": "lightweight_rg_dispatch", "baseline": "edd",
             "label": "Lightweight RG Dispatch vs EDD"},
            {"algorithm": "online_legacy_rg_alns", "baseline": "edd",
             "label": "Online-Legacy-ALNS vs EDD"},
        ]

    # Build paired index: (instance_key, seed) -> {algorithm: row}
    paired_index: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in per_instance_rows:
        if row.get("status") != "OK":
            continue
        instance_key = row.get("instance", "")
        seed = row.get("seed", "")
        algo = row.get("algorithm", "")
        paired_index[(instance_key, seed)][algo] = row

    table_rows: list[dict[str, Any]] = []
    metrics = ["Z_N", "TT", "WSF", "ZSR"]

    for comp in comparisons:
        algo_key = comp["algorithm"]
        baseline_key = comp["baseline"]
        comp_label = comp["label"]

        for metric in metrics:
            algo_vals: list[float] = []
            baseline_vals: list[float] = []

            for (inst, seed), algo_map in paired_index.items():
                algo_row = algo_map.get(algo_key)
                baseline_row = algo_map.get(baseline_key)
                if algo_row and baseline_row:
                    a_val = _float_val(algo_row, metric)
                    b_val = _float_val(baseline_row, metric)
                    if a_val is not None and b_val is not None:
                        algo_vals.append(a_val)
                        baseline_vals.append(b_val)

            n = len(algo_vals)
            if n < 1:
                continue

            mean_alg = _mean(algo_vals)
            mean_base = _mean(baseline_vals)
            mean_diff = mean_alg - mean_base
            rel_imp = _relative_improvement(mean_alg, mean_base)
            if isinstance(rel_imp, str) and rel_imp == "":
                rel_imp = float("nan")

            row = {
                "comparison": comp_label,
                "algorithm": algo_key,
                "baseline_algorithm": baseline_key,
                "metric": metric,
                "n_paired": n,
                "mean_algorithm": mean_alg,
                "mean_baseline": mean_base,
                "mean_difference": mean_diff,
                "relative_improvement_percent": rel_imp if not (isinstance(rel_imp, float) and math.isnan(rel_imp)) else "",
                "p_value_paired_ttest": _paired_ttest(algo_vals, baseline_vals),
                "p_value_wilcoxon": _wilcoxon_p(algo_vals, baseline_vals),
            }
            table_rows.append(row)

    return table_rows


def _load_mechanism_rows(input_dir: Path) -> list[dict[str, Any]]:
    """Load mechanism_stats.csv if available."""
    for root, _dirs, files in os.walk(input_dir):
        for fname in files:
            if fname == "mechanism_stats.csv":
                path = Path(root) / fname
                try:
                    return _read_csv(path)
                except Exception:
                    return []
    return []


def _load_trigger_rows(input_dir: Path) -> list[dict[str, Any]]:
    """Load trigger_reason_counts.csv if available."""
    for root, _dirs, files in os.walk(input_dir):
        for fname in files:
            if fname == "trigger_reason_counts.csv":
                path = Path(root) / fname
                try:
                    return _read_csv(path)
                except Exception:
                    return []
    return []


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def summarize_results(
    input_dir: Path,
    output_dir: Path,
    *,
    beta_values: list[float] | None = None,
    service_outlier_wsf: float = 0.0,
    service_outlier_zsr: float = 1.0,
) -> dict[str, Path]:
    """Run all table generators and write CSV files.

    Returns a mapping of table name to output path.
    """
    if beta_values is None:
        beta_values = [1, 5, 10, 20, 50, 100]

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}

    print(f"Loading per-instance data from: {input_dir}")
    per_instance_rows = _load_per_instance_data(input_dir)
    if not per_instance_rows:
        print("  [ERROR] No per-instance data found. Cannot generate tables.")
        # Report missing input
        print(f"  Missing required input: per_instance_results.csv")
        print(f"  Expected path: {input_dir}/**/per_instance_results.csv")
        print(f"  Tables that cannot be generated: ALL")
        return outputs

    print(f"  Loaded {len(per_instance_rows)} per-instance rows")

    # Table 1: Main comparison
    print("Generating table_main_comparison.csv ...")
    table_main = generate_table_main_comparison(per_instance_rows)
    path_main = output_dir / "table_main_comparison.csv"
    _write_csv(path_main, table_main)
    outputs["main_comparison"] = path_main
    print(f"  Wrote {len(table_main)} rows to {path_main}")

    # Table 2: Beta sensitivity
    print("Generating table_beta_sensitivity.csv ...")
    table_beta = generate_table_beta_sensitivity(per_instance_rows, beta_values)
    path_beta = output_dir / "table_beta_sensitivity.csv"
    _write_csv(path_beta, table_beta)
    outputs["beta_sensitivity"] = path_beta
    print(f"  Wrote {len(table_beta)} rows to {path_beta}")

    # Table 3: Ablation
    print("Generating table_ablation.csv ...")
    sources = set(r.get("_source", "") for r in per_instance_rows)
    has_ablation = any("ablation" in s.lower() or "w_o_" in s.lower() or "variant" in s.lower()
                       for s in sources)
    if has_ablation or len(sources) > 1:
        table_ablation = generate_table_ablation(per_instance_rows)
        path_ablation = output_dir / "table_ablation.csv"
        _write_csv(path_ablation, table_ablation)
        outputs["ablation"] = path_ablation
        print(f"  Wrote {len(table_ablation)} rows to {path_ablation}")
    else:
        print("  [SKIP] No ablation variant data detected; single-source run.")

    # Table 4: Mechanism stats
    print("Generating table_mechanism_stats.csv ...")
    table_mech = generate_table_mechanism_stats(input_dir)
    if table_mech:
        path_mech = output_dir / "table_mechanism_stats.csv"
        _write_csv(path_mech, table_mech)
        outputs["mechanism_stats"] = path_mech
        print(f"  Wrote {len(table_mech)} rows to {path_mech}")
    else:
        print("  [WARN] Missing required input: mechanism_stats.csv")
        print("  Table that cannot be generated: table_mechanism_stats.csv")

    # Table 5: Scalability
    print("Generating table_scalability.csv ...")
    has_scalability = any("scalability" in s.lower() or "scale_" in s.lower() for s in sources)
    if has_scalability:
        table_scale = generate_table_scalability(per_instance_rows)
        path_scale = output_dir / "table_scalability.csv"
        _write_csv(path_scale, table_scale)
        outputs["scalability"] = path_scale
        print(f"  Wrote {len(table_scale)} rows to {path_scale}")
    else:
        print("  [SKIP] No scalability data detected.")

    # Table 6: Seed robustness
    print("Generating table_seed_robustness.csv ...")
    table_robust = generate_table_seed_robustness(
        per_instance_rows,
        service_outlier_threshold_wsf=service_outlier_wsf,
        service_outlier_threshold_zsr=service_outlier_zsr,
    )
    if table_robust:
        path_robust = output_dir / "table_seed_robustness.csv"
        _write_csv(path_robust, table_robust)
        outputs["seed_robustness"] = path_robust
        print(f"  Wrote {len(table_robust)} rows to {path_robust}")

    # Table 7: Statistical tests
    print("Generating table_statistical_tests.csv ...")
    table_stats = generate_table_statistical_tests(per_instance_rows)
    if table_stats:
        path_stats = output_dir / "table_statistical_tests.csv"
        _write_csv(path_stats, table_stats)
        outputs["statistical_tests"] = path_stats
        print(f"  Wrote {len(table_stats)} rows to {path_stats}")
    else:
        print("  [WARN] Could not generate statistical tests (insufficient paired data).")

    return outputs


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Directory containing benchmark results (with per_instance_results.csv).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output directory for paper-ready table CSVs.",
    )
    parser.add_argument(
        "--beta-values",
        type=float,
        nargs="+",
        default=[1, 5, 10, 20, 50, 100],
        help="Beta values for sensitivity analysis (default: 1 5 10 20 50 100).",
    )
    parser.add_argument(
        "--service-outlier-wsf",
        type=float,
        default=0.0,
        help="WSF threshold for service outlier detection (default: 0).",
    )
    parser.add_argument(
        "--service-outlier-zsr",
        type=float,
        default=1.0,
        help="ZSR threshold for service outlier detection (default: 1).",
    )
    args = parser.parse_args()

    input_dir: Path = args.input
    output_dir: Path = args.output

    if not input_dir.exists():
        print(f"ERROR: input directory not found: {input_dir}")
        sys.exit(1)

    print(f"=== Paper A Results Summarizer ===")
    print(f"  Input:       {input_dir}")
    print(f"  Output:      {output_dir}")
    print(f"  SciPy:       {'available' if _HAS_SCIPY else 'NOT available (statistical tests skipped)'}")
    print()

    outputs = summarize_results(
        input_dir,
        output_dir,
        beta_values=args.beta_values,
        service_outlier_wsf=args.service_outlier_wsf,
        service_outlier_zsr=args.service_outlier_zsr,
    )

    print(f"\n=== Summary generated: {len(outputs)} table(s) ===")
    for table_name, path in outputs.items():
        print(f"  {table_name}: {path}")


if __name__ == "__main__":
    main()
