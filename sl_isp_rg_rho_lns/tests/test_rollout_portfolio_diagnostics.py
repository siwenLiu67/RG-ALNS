"""Tests for rollout portfolio diagnostic summaries."""

import pandas as pd
import pytest

from src.analysis.rollout_portfolio_diagnostics import (
    summarize_rollout_portfolio,
    write_rollout_diagnostics,
)


def _portfolio_rows() -> list[dict]:
    return [
        {
            "instance_index": 0,
            "algorithm": "NR",
            "candidate": "EDD",
            "Z": 10.0,
            "runtime_s": 0.1,
            "selected": True,
        },
        {
            "instance_index": 0,
            "algorithm": "NR",
            "candidate": "Sequence",
            "Z": 100.0,
            "runtime_s": 8.0,
            "selected": False,
        },
        {
            "instance_index": 1,
            "algorithm": "NR",
            "candidate": "EDD",
            "Z": 12.0,
            "runtime_s": 0.1,
            "selected": True,
        },
        {
            "instance_index": 1,
            "algorithm": "NR",
            "candidate": "Sequence",
            "Z": 90.0,
            "runtime_s": 9.0,
            "selected": False,
        },
    ]


def test_candidate_summary_marks_slow_never_selected_candidates():
    summary = summarize_rollout_portfolio(
        pd.DataFrame(_portfolio_rows()),
        slow_runtime_s=1.0,
    )

    sequence = summary.loc[summary["candidate"] == "Sequence"].iloc[0]

    assert sequence["runs"] == 2
    assert sequence["selected_count"] == 0
    assert sequence["selection_rate"] == 0.0
    assert sequence["mean_regret_vs_instance_best"] == pytest.approx(84.0)
    assert bool(sequence["slow_never_selected"]) is True


def test_candidate_summary_orders_by_selected_count_then_regret():
    summary = summarize_rollout_portfolio(
        pd.DataFrame(_portfolio_rows()),
        slow_runtime_s=1.0,
    )

    assert summary["candidate"].tolist() == ["EDD", "Sequence"]


def test_load_and_write_summary_round_trip(tmp_path):
    source = tmp_path / "portfolio.csv"
    output = tmp_path / "summary.csv"
    pd.DataFrame(_portfolio_rows()).to_csv(source, index=False)

    written = write_rollout_diagnostics(source, output, slow_runtime_s=1.0)

    assert written == output
    persisted = pd.read_csv(output)
    assert persisted["candidate"].tolist() == ["EDD", "Sequence"]


def test_summary_rejects_missing_required_columns():
    with pytest.raises(ValueError, match="missing required columns"):
        summarize_rollout_portfolio(pd.DataFrame({"candidate": ["EDD"]}))
