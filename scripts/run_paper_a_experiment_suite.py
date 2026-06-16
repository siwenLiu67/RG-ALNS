#!/usr/bin/env python3
"""Run Paper A experiment suites without changing the online protocol."""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "sl_isp_rg_rho_lns"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from src.experiments.paper_a_online_protocol import (  # noqa: E402
    load_paper_a_config,
    run_paper_a_online_benchmark,
)


ALGORITHM_ALIASES = {
    "edd": "edd",
    "spt": "spt",
    "wspt": "wspt",
    "atc": "atc",
    "swd": "swd",
    "sfg": "sfg",
    "lightweightrgdispatch": "lightweight_rg_dispatch",
    "lightweight_rg_dispatch": "lightweight_rg_dispatch",
    "lightweight-rg-dispatch": "lightweight_rg_dispatch",
    "lightweight rg dispatch": "lightweight_rg_dispatch",
    "onlinelegacyalns": "online_legacy_rg_alns",
    "online_legacy_alns": "online_legacy_rg_alns",
    "online-legacy-alns": "online_legacy_rg_alns",
    "online legacy alns": "online_legacy_rg_alns",
    "online_legacy_rg_alns": "online_legacy_rg_alns",
    "online-legacy-rg-alns": "online_legacy_rg_alns",
    "rgralns": "rg_ralns",
    "rg_ralns": "rg_ralns",
    "rg-ralns": "rg_ralns",
    "rg ralns": "rg_ralns",
}

SUITE_DESCRIPTIONS = {
    "pilot": "Small Stage 2-pre pipeline check.",
    "main": "Main online comparison using the selected algorithm set.",
    "beta_sensitivity": "Beta sensitivity run for normalized SLA penalty intensity.",
    "ablation": "Ablation planning run; unavailable variants are documented, not faked.",
    "mechanism": "Mechanism analysis run with RG-RALNS diagnostics enabled.",
    "scalability": "Scalability smoke run using the selected scale preset.",
    "robustness": "Robustness run across seeds and service outlier diagnostics.",
}

SCALE_PRESETS = {
    "small": {"num_jobs": 20, "num_machines": 5, "num_entities": 3},
    "medium": {"num_jobs": 50, "num_machines": 8, "num_entities": 5},
    "large": {"num_jobs": 100, "num_machines": 12, "num_entities": 8},
    "xlarge": {"num_jobs": 200, "num_machines": 16, "num_entities": 12},
}

ABLATION_PLAN = [
    {
        "variant": "Full RG-RALNS default",
        "implementable_now": True,
        "recommended_for_final_paper": True,
        "required_code_changes": "",
        "notes": "Current default with capacity_rescue_enabled=false.",
    },
    {
        "variant": "w/o recoverability trigger",
        "implementable_now": False,
        "recommended_for_final_paper": True,
        "required_code_changes": "Expose trigger disabling while preserving online view.",
        "notes": "Useful to isolate recoverability-guided triggering contribution.",
    },
    {
        "variant": "w/o service-safe extraction",
        "implementable_now": False,
        "recommended_for_final_paper": True,
        "required_code_changes": "Expose extraction policy switch.",
        "notes": "Useful because Stage 0 directly fixed extraction/fallback failures.",
    },
    {
        "variant": "w/o rescue-chain precursor priority",
        "implementable_now": False,
        "recommended_for_final_paper": "maybe",
        "required_code_changes": "Expose precursor priority switch.",
        "notes": "Stage 0.5 found this did not fix seed 2 alone, but it supports diagnosis.",
    },
    {
        "variant": "w/o service-safe acceptance",
        "implementable_now": True,
        "recommended_for_final_paper": True,
        "required_code_changes": "Use rg_ralns.acceptance_mode=service_first/service_safe_z comparison.",
        "notes": "Existing acceptance_mode parameter can support a focused comparison.",
    },
    {
        "variant": "w/o local ALNS",
        "implementable_now": True,
        "recommended_for_final_paper": True,
        "required_code_changes": "Use Lightweight RG Dispatch baseline.",
        "notes": "Already present as the lightweight ablation.",
    },
    {
        "variant": "capacity_rescue_enabled=true",
        "implementable_now": True,
        "recommended_for_final_paper": False,
        "required_code_changes": "Set rg_ralns.capacity_rescue_enabled=true.",
        "notes": "Stage 1.5 negative diagnostic variant; not a default mechanism.",
    },
]


def normalize_algorithm_key(name: str) -> str:
    """Normalize a user-facing algorithm name to a Paper A config key."""

    normalized = name.strip().lower().replace("__", "_")
    lookup_key = normalized.replace("_", "").replace("-", "").replace(" ", "")
    if normalized in ALGORITHM_ALIASES:
        return ALGORITHM_ALIASES[normalized]
    if lookup_key in ALGORITHM_ALIASES:
        return ALGORITHM_ALIASES[lookup_key]
    raise ValueError(f"Unknown Paper A algorithm name: {name}")


def _git_value(args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
    except Exception:
        return ""
    return completed.stdout.strip()


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


def _selected_algorithm_keys(args: argparse.Namespace, config: dict[str, Any]) -> list[str]:
    if args.algorithms:
        return [normalize_algorithm_key(name) for name in args.algorithms]
    if args.suite == "pilot":
        return [
            "edd",
            "lightweight_rg_dispatch",
            "online_legacy_rg_alns",
            "rg_ralns",
        ]
    return list(config.get("algorithms", {}).get("main_online", []))


def _instance_overrides_for_scale(
    config: dict[str, Any],
    scale: str | None,
) -> dict[str, Any] | None:
    if not scale:
        return None
    if scale not in SCALE_PRESETS:
        raise ValueError(f"Unknown scale preset: {scale}")
    instances = {}
    for instance_key, instance_cfg in config.get("instances", {}).items():
        updated = dict(instance_cfg)
        updated.update(SCALE_PRESETS[scale])
        updated["group_name"] = updated.get("group_name", f"{instance_key}_{scale}")
        instances[f"{instance_key}_{scale}"] = updated
    return instances


def _write_suite_metadata(
    *,
    output_dir: Path,
    args: argparse.Namespace,
    algorithm_keys: list[str],
    config_overrides: dict[str, Any],
) -> Path:
    metadata = {
        "suite": args.suite,
        "suite_description": SUITE_DESCRIPTIONS[args.suite],
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "branch": _git_value(["branch", "--show-current"]),
        "commit": _git_value(["rev-parse", "HEAD"]),
        "config": str(args.config),
        "seeds": args.seeds,
        "objective_beta": args.objective_beta,
        "beta_sensitivity": args.beta_sensitivity,
        "algorithms": algorithm_keys,
        "scale": args.scale,
        "rg_debug_trace": args.rg_debug_trace,
        "config_overrides": config_overrides,
    }
    path = output_dir / "suite_metadata.yaml"
    output_dir.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(metadata, fh, sort_keys=False)
    return path


def _write_ablation_plan(output_dir: Path) -> Path:
    path = output_dir / "ablation_plan.csv"
    _write_csv(path, ABLATION_PLAN)
    return path


def build_config_overrides(
    *,
    args: argparse.Namespace,
    config: dict[str, Any],
    algorithm_keys: list[str],
) -> dict[str, Any]:
    """Build shallow overrides accepted by run_paper_a_online_benchmark."""

    overrides: dict[str, Any] = {
        "algorithms": {
            "main_online": algorithm_keys,
            "offline_oracle": [],
        }
    }
    if args.objective_beta is not None:
        overrides["objective"] = {"beta_0": float(args.objective_beta)}
    if args.suite == "mechanism" or args.rg_debug_trace:
        rg_cfg = dict(overrides.get("rg_ralns", {}))
        rg_cfg["debug_trace"] = True
        overrides["rg_ralns"] = rg_cfg
    instances = _instance_overrides_for_scale(config, args.scale)
    if instances is not None:
        overrides["instances"] = instances
    return overrides


def run_suite(args: argparse.Namespace) -> dict[str, Any]:
    config = load_paper_a_config(args.config)
    algorithm_keys = _selected_algorithm_keys(args, config)
    config_overrides = build_config_overrides(
        args=args,
        config=config,
        algorithm_keys=algorithm_keys,
    )
    beta_sensitivity = args.beta_sensitivity
    if args.suite == "beta_sensitivity" and beta_sensitivity is None:
        beta_sensitivity = list(config.get("objective", {}).get(
            "beta_sensitivity",
            [1, 5, 10, 20, 50, 100],
        ))

    output_dir = args.output
    metadata_path = _write_suite_metadata(
        output_dir=output_dir,
        args=args,
        algorithm_keys=algorithm_keys,
        config_overrides=config_overrides,
    )
    extra_outputs = {"suite_metadata_yaml": str(metadata_path)}
    if args.suite == "ablation":
        extra_outputs["ablation_plan_csv"] = str(_write_ablation_plan(output_dir))

    if args.dry_run_plan:
        return {"outputs": extra_outputs, "dry_run_plan": True}

    result = run_paper_a_online_benchmark(
        config_path=args.config,
        seeds=args.seeds,
        output_dir=output_dir,
        config_overrides=config_overrides,
        beta_sensitivity=beta_sensitivity,
        rg_debug_trace=args.rg_debug_trace or args.suite == "mechanism",
    )
    result["outputs"].update(extra_outputs)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs" / "paper_a_online.yaml",
    )
    parser.add_argument(
        "--suite",
        choices=sorted(SUITE_DESCRIPTIONS),
        default="pilot",
    )
    parser.add_argument("--seeds", type=int, nargs="+", default=[0])
    parser.add_argument("--objective-beta", type=float)
    parser.add_argument("--beta-sensitivity", type=float, nargs="+")
    parser.add_argument("--algorithms", nargs="+")
    parser.add_argument("--scale", choices=sorted(SCALE_PRESETS))
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "results" / "paper_a_stage2_pre_pilot",
    )
    parser.add_argument("--rg-debug-trace", action="store_true")
    parser.add_argument(
        "--dry-run-plan",
        action="store_true",
        help="Write suite metadata/plan files without running the benchmark.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_suite(args)
    for name, path in result["outputs"].items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
