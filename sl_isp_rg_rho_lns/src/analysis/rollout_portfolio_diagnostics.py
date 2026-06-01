"""Diagnostics for no-regret rollout portfolio candidate CSVs."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


REQUIRED_COLUMNS = {
    "instance_index",
    "algorithm",
    "candidate",
    "Z",
    "runtime_s",
    "selected",
}


def _selected_as_bool(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series
    return series.astype(str).str.lower().isin({"1", "true", "yes"})


def summarize_rollout_portfolio(
    df: pd.DataFrame,
    slow_runtime_s: float = 30.0,
) -> pd.DataFrame:
    """Summarize rollout candidates across instances and proposed variants."""

    missing = REQUIRED_COLUMNS.difference(df.columns)
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"rollout portfolio is missing required columns: {missing_list}")

    work = df.copy()
    work["selected"] = _selected_as_bool(work["selected"])
    work["Z"] = pd.to_numeric(work["Z"])
    work["runtime_s"] = pd.to_numeric(work["runtime_s"])
    instance_keys = ["algorithm", "instance_index"]
    work["instance_best_Z"] = work.groupby(instance_keys)["Z"].transform("min")
    work["regret_vs_instance_best"] = work["Z"] - work["instance_best_Z"]

    summary = (
        work.groupby("candidate", as_index=False)
        .agg(
            runs=("candidate", "size"),
            selected_count=("selected", "sum"),
            mean_Z=("Z", "mean"),
            mean_runtime_s=("runtime_s", "mean"),
            mean_regret_vs_instance_best=("regret_vs_instance_best", "mean"),
        )
        .sort_values(
            ["selected_count", "mean_regret_vs_instance_best", "mean_runtime_s"],
            ascending=[False, True, True],
        )
        .reset_index(drop=True)
    )
    summary["selection_rate"] = summary["selected_count"] / summary["runs"]
    summary["slow_never_selected"] = (
        (summary["selected_count"] == 0)
        & (summary["mean_runtime_s"] >= float(slow_runtime_s))
    )

    column_order = [
        "candidate",
        "runs",
        "selected_count",
        "selection_rate",
        "mean_Z",
        "mean_runtime_s",
        "mean_regret_vs_instance_best",
        "slow_never_selected",
    ]
    return summary[column_order]


def write_rollout_diagnostics(
    input_csv: str | Path,
    output_csv: str | Path,
    slow_runtime_s: float = 30.0,
) -> Path:
    """Load a rollout portfolio CSV and write candidate diagnostics."""

    input_path = Path(input_csv)
    output_path = Path(output_csv)
    summary = summarize_rollout_portfolio(
        pd.read_csv(input_path),
        slow_runtime_s=slow_runtime_s,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output_path, index=False)
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Summarize rollout portfolio candidate diagnostics.",
    )
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("output_csv", type=Path)
    parser.add_argument("--slow-runtime-s", type=float, default=30.0)
    args = parser.parse_args(argv)

    written = write_rollout_diagnostics(
        args.input_csv,
        args.output_csv,
        slow_runtime_s=args.slow_runtime_s,
    )
    print(f"Wrote rollout diagnostics to {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
