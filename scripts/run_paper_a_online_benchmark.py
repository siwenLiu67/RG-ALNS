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
    args = parser.parse_args()

    result = run_paper_a_online_benchmark(
        config_path=args.config,
        seeds=args.seeds,
        output_dir=args.output,
    )
    for name, path in result["outputs"].items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
