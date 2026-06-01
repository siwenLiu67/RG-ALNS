#!/usr/bin/env python3
"""Generate LaTeX result rows for 0522.tex from real experiment CSV files.

The script does not infer missing results. If an expected CSV or column is
absent, the corresponding LaTeX row file is not generated and the manuscript
keeps its built-in pending placeholders.
"""

from __future__ import annotations

import argparse
import csv
import math
import shutil
from collections import defaultdict
from pathlib import Path
from statistics import mean, median, stdev

try:
    from scipy.stats import wilcoxon  # type: ignore

    HAS_SCIPY = True
except Exception:  # pragma: no cover - optional dependency
    HAS_SCIPY = False


PROPOSED = "RG-ALNS"
PROPOSED_ALIASES = {
    PROPOSED,
    "NR-RG-RHO-LNS",
    "SRG-RHO-LNS",
}

ALGORITHM_DISPLAY_ORDER = [
    ("EDD", "EDD"),
    ("SPT", "SPT"),
    ("WSPT", "WSPT"),
    ("ATC", "ATC"),
    ("Service-Weighted", "Service-weighted"),
    ("Shortfall-Greedy", "Shortfall-greedy"),
    ("Plain-RHO-Fast", "Plain RHO"),
    ("RHO-LNS-Fast", "RHO-LNS"),
    ("Adaptive-RG-v1.2", "Adaptive RG"),
    ("ILS-Fast", "ILS"),
    ("VNS-Fast", "VNS"),
    ("TS-Fast", "TS"),
    (PROPOSED, PROPOSED),
]

DISPLAY_BY_RAW = dict(ALGORITHM_DISPLAY_ORDER)
RAW_BY_DISPLAY = {display: raw for raw, display in ALGORITHM_DISPLAY_ORDER}
RAW_ORDER = [raw for raw, _ in ALGORITHM_DISPLAY_ORDER]

PRESSURE_DISPLAY = {
    "medium": "Medium",
    "high": "High",
    "very_high": "Very high",
}

FIGURE_MAP = {
    "fig1_overall_Z.pdf": ["fig1_overall_Z.pdf"],
    "fig2_tt_wsf_decomposition.pdf": ["fig2_tt_wsf_decomposition.pdf"],
    "fig3_pressure_Z.pdf": ["fig3_pressure_Z.pdf"],
    "fig4_pressure_WSF.pdf": ["fig4_pressure_WSF.pdf"],
    "fig5_ablation.pdf": ["fig5_ablation.pdf"],
    "fig6_candidate_selection_frequency.pdf": [
        "fig6_candidate_selection_frequency.pdf"
    ],
    "fig7_convergence_best_so_far_Z.pdf": [
        "fig7_convergence_best_so_far_Z.pdf",
        "fig7_convergence.pdf",
    ],
    "fig8_runtime_log_scale.pdf": [
        "fig8_runtime_log_scale.pdf",
        "fig8_runtime.pdf",
    ],
    "fig9_scalability_heatmap.pdf": [
        "fig9_scalability_heatmap.pdf",
        "fig9_scalability.pdf",
    ],
    "fig10_operator_contribution.pdf": ["fig10_operator_contribution.pdf"],
    "fig11_representative_gantt.pdf": ["fig11_representative_gantt.pdf"],
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        if row.get("algorithm_label") in PROPOSED_ALIASES:
            row["algorithm_label"] = PROPOSED
        if row.get("variant") == "Full NR-RG-RHO-LNS":
            row["variant"] = "Full RG-ALNS"
    return rows


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def ok_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if row.get("status") == "OK"]


def numeric(row: dict[str, str], key: str) -> float:
    value = row.get(key, "")
    if value in {"", "None", "nan", "NaN"}:
        raise ValueError(f"missing numeric value for {key}")
    return float(value)


def has_columns(rows: list[dict[str, str]], columns: list[str]) -> bool:
    if not rows:
        return False
    available = set(rows[0].keys())
    return all(col in available for col in columns)


def fmt(value: float, digits: int = 2) -> str:
    if math.isnan(value) or math.isinf(value):
        return "--"
    return f"{value:.{digits}f}"


def fmt_mean(values: list[float], digits: int = 2) -> str:
    return fmt(mean(values), digits) if values else "--"


def latex_escape(value: object) -> str:
    text = str(value)
    replacements = {
        "&": r"\&",
        "%": r"\%",
        "#": r"\#",
        "_": r"\_",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def write_rows(path: Path, rows: list[str]) -> None:
    write_text(path, "\n".join(rows) + ("\n" if rows else ""))


def grouped(rows: list[dict[str, str]], key_fn, metric_names: list[str]):
    out: dict[object, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in rows:
        key = key_fn(row)
        for metric in metric_names:
            try:
                out[key][metric].append(numeric(row, metric))
            except ValueError:
                pass
    return out


def generate_table3(rows: list[dict[str, str]], tables_dir: Path) -> str:
    required = ["algorithm_label", "Z", "TT", "WSF", "ZSR", "runtime_total_s"]
    if not has_columns(rows, required):
        return "Table 3 not generated: final_raw.csv is missing required columns."

    by_algo = grouped(
        rows,
        lambda row: row["algorithm_label"],
        ["Z", "TT", "WSF", "ZSR", "runtime_total_s"],
    )
    lines: list[str] = []
    for raw, display in ALGORITHM_DISPLAY_ORDER:
        metrics = by_algo.get(raw)
        if not metrics or not metrics["Z"]:
            continue
        lines.append(
            " & ".join(
                [
                    latex_escape(display),
                    fmt_mean(metrics["Z"], 2),
                    fmt_mean(metrics["TT"], 2),
                    fmt_mean(metrics["WSF"], 2),
                    fmt_mean(metrics["ZSR"], 3),
                    fmt_mean(metrics["runtime_total_s"], 3),
                ]
            )
            + r" \\"
        )
    if not lines:
        return "Table 3 not generated: no recognized algorithm labels."
    write_rows(tables_dir / "table3_overall_comparison_rows.tex", lines)
    return "Table 3 generated from final_raw.csv."


def generate_table4(rows: list[dict[str, str]], tables_dir: Path) -> str:
    required = ["pressure_level", "algorithm_label", "Z", "TT", "WSF", "ZSR"]
    if not has_columns(rows, required):
        return "Table 4 not generated: final_raw.csv is missing required columns."

    by_key = grouped(
        rows,
        lambda row: (row["pressure_level"], row["algorithm_label"]),
        ["Z", "TT", "WSF", "ZSR"],
    )
    lines: list[str] = []
    for pressure in ["medium", "high", "very_high"]:
        for raw, display in ALGORITHM_DISPLAY_ORDER:
            metrics = by_key.get((pressure, raw))
            if not metrics or not metrics["Z"]:
                continue
            lines.append(
                " & ".join(
                    [
                        PRESSURE_DISPLAY.get(pressure, pressure),
                        latex_escape(display),
                        fmt_mean(metrics["Z"], 2),
                        fmt_mean(metrics["TT"], 2),
                        fmt_mean(metrics["WSF"], 2),
                        fmt_mean(metrics["ZSR"], 3),
                    ]
                )
                + r" \\"
            )
    if not lines:
        return "Table 4 not generated: no pressure-level aggregates found."
    write_rows(tables_dir / "table4_pressure_comparison_rows.tex", lines)
    return "Table 4 generated from final_raw.csv."


def pair_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        row.get("pressure_level", ""),
        row.get("instance_index", ""),
        row.get("seed_index", ""),
    )


def paired_stats(rows: list[dict[str, str]], baseline_raw: str) -> dict[str, object]:
    proposed_by_key: dict[tuple[str, str, str], float] = {}
    baseline_by_key: dict[tuple[str, str, str], float] = {}
    for row in rows:
        label = row.get("algorithm_label")
        try:
            z = numeric(row, "Z")
        except ValueError:
            continue
        if label == PROPOSED:
            proposed_by_key[pair_key(row)] = z
        elif label == baseline_raw:
            baseline_by_key[pair_key(row)] = z
    common = sorted(set(proposed_by_key) & set(baseline_by_key))
    proposed = [proposed_by_key[key] for key in common]
    baseline = [baseline_by_key[key] for key in common]
    deltas = [proposed[i] - baseline[i] for i in range(len(common))]
    if len(deltas) < 2:
        return {"n": len(deltas)}
    sd = stdev(deltas) if len(deltas) > 1 else 0.0
    p_value = None
    if HAS_SCIPY and len(deltas) >= 3:
        try:
            p_value = float(wilcoxon(proposed, baseline, zero_method="zsplit").pvalue)
        except Exception:
            p_value = None
    return {
        "n": len(deltas),
        "mean_delta": mean(deltas),
        "median_delta": median(deltas),
        "win_rate": sum(1 for delta in deltas if delta < 0) / len(deltas),
        "effect": mean(deltas) / sd if sd > 0 else 0.0,
        "p_value": p_value,
    }


def generate_table5(rows: list[dict[str, str]], tables_dir: Path) -> str:
    required = ["pressure_level", "instance_index", "seed_index", "algorithm_label", "Z"]
    if not has_columns(rows, required):
        return "Table 5 not generated: final_raw.csv is missing paired-test columns."

    lines: list[str] = []
    for raw, display in ALGORITHM_DISPLAY_ORDER:
        if raw == PROPOSED:
            continue
        stats = paired_stats(rows, raw)
        if stats.get("n", 0) < 2:
            continue
        p_value = stats.get("p_value")
        p_text = fmt(p_value, 4) if isinstance(p_value, float) else "N/A"
        lines.append(
            " & ".join(
                [
                    latex_escape(display),
                    fmt(float(stats["mean_delta"]), 2),
                    fmt(float(stats["win_rate"]), 3),
                    p_text,
                    fmt(float(stats["effect"]), 3),
                ]
            )
            + r" \\"
        )
    if not lines:
        return "Table 5 not generated: paired baselines are unavailable."
    write_rows(tables_dir / "table5_paired_tests_rows.tex", lines)
    return "Table 5 generated from matched final_raw.csv rows."


def generate_table5b(rows: list[dict[str, str]], tables_dir: Path) -> str:
    required = ["pressure_level", "instance_index", "seed_index", "algorithm_label", "Z"]
    if not has_columns(rows, required):
        return "Table 5b not generated: final_raw.csv is missing paired-test columns."

    lines: list[str] = []
    for pressure in ["medium", "high", "very_high"]:
        subset = [row for row in rows if row.get("pressure_level") == pressure]
        for raw, display in ALGORITHM_DISPLAY_ORDER:
            if raw == PROPOSED:
                continue
            stats = paired_stats(subset, raw)
            if stats.get("n", 0) < 2:
                continue
            p_value = stats.get("p_value")
            p_text = fmt(p_value, 4) if isinstance(p_value, float) else "N/A"
            lines.append(
                " & ".join(
                    [
                        PRESSURE_DISPLAY.get(pressure, pressure),
                        latex_escape(display),
                        fmt(float(stats["mean_delta"]), 2),
                        fmt(float(stats["win_rate"]), 3),
                        p_text,
                    ]
                )
                + r" \\"
            )
    if not lines:
        return "Table 5b not generated: pressure-specific pairs are unavailable."
    write_rows(tables_dir / "table5b_pressure_specific_tests_rows.tex", lines)
    return "Table 5b generated from matched final_raw.csv rows."


def generate_table6(input_dir: Path, tables_dir: Path) -> str:
    source = input_dir / "ablation_raw.csv"
    if not source.exists():
        return "Table 6 not generated: ablation_raw.csv is not available."
    rows = ok_rows(read_csv(source))
    required = ["variant", "Z", "TT", "WSF", "ZSR"]
    if not has_columns(rows, required):
        return "Table 6 not generated: ablation_raw.csv is missing required columns."

    order = [
        "EDF-only",
        "Best-of-5",
        "Multi-start",
        "+polishing",
        "+top-k LNS",
        "Full RG-ALNS",
    ]
    by_variant = grouped(rows, lambda row: row["variant"], ["Z", "TT", "WSF", "ZSR"])
    lines: list[str] = []
    for variant in order:
        metrics = by_variant.get(variant)
        if not metrics or not metrics["Z"]:
            continue
        lines.append(
            " & ".join(
                [
                    latex_escape(variant),
                    fmt_mean(metrics["Z"], 2),
                    fmt_mean(metrics["TT"], 2),
                    fmt_mean(metrics["WSF"], 2),
                    fmt_mean(metrics["ZSR"], 3),
                ]
            )
            + r" \\"
        )
    if not lines:
        return "Table 6 not generated: no recognized ablation variants."
    write_rows(tables_dir / "table6_ablation_rows.tex", lines)
    return "Table 6 generated from ablation_raw.csv."


def first_column(rows: list[dict[str, str]], candidates: list[str]) -> str | None:
    if not rows:
        return None
    columns = set(rows[0].keys())
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def generate_table7(rows: list[dict[str, str]], tables_dir: Path) -> str:
    jobs_col = first_column(rows, ["num_jobs", "jobs", "job_count"])
    machines_col = first_column(rows, ["num_machines", "machines", "machine_count"])
    if not jobs_col or not machines_col:
        return (
            "Table 7 not generated: final_raw.csv needs job and machine columns "
            "or a separate instance mapping."
        )
    required = [
        "pressure_level",
        "instance_index",
        "seed_index",
        "algorithm_label",
        "Z",
        jobs_col,
        machines_col,
    ]
    if not has_columns(rows, required):
        return "Table 7 not generated: scalability columns are incomplete."

    by_instance: dict[tuple[str, str, str], dict[str, dict[str, str]]] = defaultdict(dict)
    for row in rows:
        by_instance[pair_key(row)][row["algorithm_label"]] = row

    grouped_values: dict[tuple[str, str, str], dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for instance_rows in by_instance.values():
        values = {
            raw: numeric(row, "Z")
            for raw, row in instance_rows.items()
            if row.get("Z") not in {"", "None", None}
        }
        if not values:
            continue
        best = min(values.values())
        rho = values.get("RHO-LNS-Fast")
        for raw, z_value in values.items():
            row = instance_rows[raw]
            key = (row[jobs_col], row[machines_col], raw)
            grouped_values[key]["gap"].append((z_value - best) / max(best, 1e-9) * 100)
            if rho is not None:
                grouped_values[key]["improvement"].append((rho - z_value) / max(rho, 1e-9) * 100)

    lines: list[str] = []
    for jobs in ["40", "80", "120", "160"]:
        for machines in ["5", "10", "15"]:
            for raw, display in ALGORITHM_DISPLAY_ORDER:
                metrics = grouped_values.get((jobs, machines, raw))
                if not metrics or not metrics["gap"]:
                    continue
                improvement = (
                    fmt_mean(metrics["improvement"], 2)
                    if metrics["improvement"]
                    else "--"
                )
                lines.append(
                    " & ".join(
                        [
                            jobs,
                            machines,
                            latex_escape(display),
                            fmt_mean(metrics["gap"], 2),
                            improvement,
                        ]
                    )
                    + r" \\"
                )
    if not lines:
        return "Table 7 not generated: no scalability aggregates found."
    write_rows(tables_dir / "table7_scalability_rows.tex", lines)
    return "Table 7 generated with relative gap and RHO-LNS improvement."


def generate_table8(input_dir: Path, tables_dir: Path) -> str:
    source = input_dir / "diagnostics_operator_success.csv"
    if not source.exists():
        return "Table 8 not generated: diagnostics_operator_success.csv is not available."
    rows = read_csv(source)
    required = ["operator_name", "usage_count", "improvement_count", "total_improvement"]
    if not has_columns(rows, required):
        return "Table 8 not generated: operator diagnostic columns are incomplete."
    totals: dict[str, dict[str, float]] = defaultdict(
        lambda: {"usage": 0.0, "success": 0.0, "improvement": 0.0}
    )
    for row in rows:
        name = row["operator_name"]
        totals[name]["usage"] += numeric(row, "usage_count")
        totals[name]["success"] += numeric(row, "improvement_count")
        totals[name]["improvement"] += numeric(row, "total_improvement")
    total_usage = sum(item["usage"] for item in totals.values())
    lines = []
    for name in sorted(totals):
        item = totals[name]
        usage_ratio = item["usage"] / total_usage if total_usage > 0 else 0.0
        success_rate = item["success"] / item["usage"] if item["usage"] > 0 else 0.0
        mean_improvement = item["improvement"] / item["success"] if item["success"] > 0 else 0.0
        lines.append(
            " & ".join(
                [
                    latex_escape(name),
                    fmt(usage_ratio, 3),
                    fmt(success_rate, 3),
                    fmt(mean_improvement, 2),
                ]
            )
            + r" \\"
        )
    if not lines:
        return "Table 8 not generated: no operator diagnostics found."
    write_rows(tables_dir / "table8_operator_contribution_rows.tex", lines)
    return "Table 8 generated from operator diagnostics."


def generate_table9(rows: list[dict[str, str]], tables_dir: Path) -> str:
    required = ["algorithm_label", "runtime_total_s"]
    if not has_columns(rows, required):
        return "Table 9 not generated: final_raw.csv is missing runtime columns."

    eval_col = first_column(rows, ["schedule_evaluations", "evaluations", "events_count"])
    construct_col = first_column(rows, ["construction_time_s", "construction_runtime_s"])
    search_col = first_column(rows, ["search_time_s", "search_runtime_s"])
    by_algo = grouped(rows, lambda row: row["algorithm_label"], ["runtime_total_s"])
    lines: list[str] = []
    for raw, display in ALGORITHM_DISPLAY_ORDER:
        metrics = by_algo.get(raw)
        if not metrics or not metrics["runtime_total_s"]:
            continue
        subset = [row for row in rows if row.get("algorithm_label") == raw]
        evaluations = fmt_mean([numeric(row, eval_col) for row in subset], 1) if eval_col else r"\todoresult{not logged}"
        construction = fmt_mean([numeric(row, construct_col) for row in subset], 3) if construct_col else r"\todoresult{not logged}"
        search = fmt_mean([numeric(row, search_col) for row in subset], 3) if search_col else r"\todoresult{not logged}"
        lines.append(
            " & ".join(
                [
                    latex_escape(display),
                    fmt_mean(metrics["runtime_total_s"], 3),
                    fmt(max(metrics["runtime_total_s"]), 3),
                    evaluations,
                    construction,
                    search,
                ]
            )
            + r" \\"
        )
    if not lines:
        return "Table 9 not generated: no runtime aggregates found."
    write_rows(tables_dir / "table9_runtime_budget_rows.tex", lines)
    return "Table 9 generated from runtime columns; missing budget fields remain marked."


def copy_figures(input_dir: Path, paper_dir: Path) -> list[str]:
    source_dir = input_dir / "figures"
    target_dir = paper_dir / "figures"
    status: list[str] = []
    if not source_dir.exists():
        return ["Figures not copied: input figures directory is not available."]
    target_dir.mkdir(parents=True, exist_ok=True)
    for target_name, candidates in FIGURE_MAP.items():
        copied = False
        for candidate in candidates:
            source = source_dir / candidate
            if source.exists():
                shutil.copy2(source, target_dir / target_name)
                status.append(f"Copied {source.name} -> figures/{target_name}.")
                copied = True
                break
        if not copied:
            status.append(f"Missing figure source for figures/{target_name}.")
    return status


def build_status_report(status: list[str], input_dir: Path, paper_dir: Path) -> str:
    try:
        input_display = input_dir.relative_to(paper_dir.parent).as_posix()
    except ValueError:
        input_display = input_dir.name
    try:
        paper_display = paper_dir.relative_to(paper_dir.parent).as_posix()
    except ValueError:
        paper_display = paper_dir.name
    lines = [
        "# Generated Results Status",
        "",
        f"Input directory: `{input_display}`",
        f"Paper directory: `{paper_display}`",
        "",
        "This file is generated by `paper/tools/autofill_results.py`.",
        "No numerical conclusion should be written until all required result files are available.",
        "",
        "## Generation Status",
        "",
    ]
    lines.extend(f"- {item}" for item in status)
    lines.extend(
        [
            "",
            "## Sign Convention",
            "",
            "- In paired-test tables, `Delta Z` is computed as `Z_proposed - Z_baseline`.",
            "- Negative `Delta Z` means the proposed method has lower objective value on the matched pair.",
            "- Win rate is the fraction of matched pairs with `Z_proposed < Z_baseline`.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    default_paper_dir = Path(__file__).resolve().parents[1]
    default_input_dir = (
        default_paper_dir.parent
        / "sl_isp_rg_rho_lns"
        / "outputs"
        / "final_v13_validation"
    )
    parser.add_argument("--input-dir", type=Path, default=default_input_dir)
    parser.add_argument("--paper-dir", type=Path, default=default_paper_dir)
    parser.add_argument("--copy-figures", action="store_true")
    args = parser.parse_args()

    input_dir = args.input_dir.resolve()
    paper_dir = args.paper_dir.resolve()
    tables_dir = paper_dir / "generated_tables"
    status: list[str] = []

    raw_path = input_dir / "final_raw.csv"
    if raw_path.exists():
        rows = ok_rows(read_csv(raw_path))
        status.append(f"Read {len(rows)} OK rows from final_raw.csv.")
        status.append(generate_table3(rows, tables_dir))
        status.append(generate_table4(rows, tables_dir))
        status.append(generate_table5(rows, tables_dir))
        status.append(generate_table5b(rows, tables_dir))
        status.append(generate_table7(rows, tables_dir))
        status.append(generate_table9(rows, tables_dir))
    else:
        status.append("final_raw.csv is not available; result tables remain pending.")

    status.append(generate_table6(input_dir, tables_dir))
    status.append(generate_table8(input_dir, tables_dir))

    if args.copy_figures:
        status.extend(copy_figures(input_dir, paper_dir))
    else:
        status.append("Figure copying skipped. Use --copy-figures after figures are generated.")

    write_text(
        paper_dir / "generated_results_status.md",
        build_status_report(status, input_dir, paper_dir),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
