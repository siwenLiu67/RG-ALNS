#!/usr/bin/env python3
"""Run the Paper A online event-driven benchmark protocol."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "sl_isp_rg_rho_lns"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from src.experiments.paper_a_online_protocol import run_paper_a_online_benchmark


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs" / "paper_a_online.yaml",
    )
    parser.add_argument("--seeds", type=int, nargs="+", default=[0])
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "results" / "paper_a_online",
    )
    parser.add_argument("--rg-H-A", type=int, dest="rg_H_A")
    parser.add_argument("--rg-N-A", type=int, dest="rg_N_A")
    parser.add_argument(
        "--rg-acceptance-mode",
        choices=["service_first", "service_safe_z"],
    )
    parser.add_argument(
        "--rg-bottleneck-trigger-mode",
        choices=["normal", "strict"],
    )
    parser.add_argument(
        "--beta-sensitivity",
        type=float,
        nargs="+",
        help="Override objective.beta_sensitivity values for normalized objective analysis.",
    )
    parser.add_argument(
        "--objective-beta",
        type=float,
        help="Override objective.beta_0 for the main normalized objective setting.",
    )
    parser.add_argument(
        "--rg-debug-trace",
        action="store_true",
        help="Write RG-RALNS event trace rows for diagnostic runs.",
    )
    args = parser.parse_args()

    rg_overrides = {
        key: value
        for key, value in {
            "H_A": args.rg_H_A,
            "N_A": args.rg_N_A,
            "acceptance_mode": args.rg_acceptance_mode,
            "bottleneck_trigger_mode": args.rg_bottleneck_trigger_mode,
        }.items()
        if value is not None
    }
    config_overrides = {}
    if rg_overrides:
        config_overrides["rg_ralns"] = rg_overrides
    if args.objective_beta is not None:
        config_overrides["objective"] = {"beta_0": args.objective_beta}
    if not config_overrides:
        config_overrides = None

    result = run_paper_a_online_benchmark(
        config_path=args.config,
        seeds=args.seeds,
        output_dir=args.output,
        config_overrides=config_overrides,
        beta_sensitivity=args.beta_sensitivity,
        rg_debug_trace=args.rg_debug_trace,
    )
    for name, path in result["outputs"].items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
