#!/usr/bin/env python3
"""Run the Paper A Stage 2 formal experiment suite.

Orchestrates multiple experiment modules (main comparison, beta sensitivity,
ablation, mechanism analysis, scalability, seed robustness) by driving the
existing ``run_paper_a_online_benchmark`` protocol with per-module overrides.

Each module writes results to a separate sub-directory under ``--output``.
Metadata (git branch, commit hash, timestamp) is saved alongside results.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "sl_isp_rg_rho_lns"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from src.experiments.paper_a_online_protocol import run_paper_a_online_benchmark


# ---------------------------------------------------------------------------
# Suite definitions
# ---------------------------------------------------------------------------

ALL_MAIN_ALGORITHMS = [
    "edd",
    "spt",
    "wspt",
    "atc",
    "swd",
    "sfg",
    "lightweight_rg_dispatch",
    "online_legacy_rg_alns",
    "rg_ralns",
]

BETA_SENSITIVITY_ALGORITHMS = [
    "edd",
    "lightweight_rg_dispatch",
    "online_legacy_rg_alns",
    "rg_ralns",
]

ABLATION_VARIANTS: dict[str, dict[str, object]] = {
    "full_rg_ralns_default": {
        "description": "Full RG-RALNS default configuration",
        "overrides": {},
    },
    "w_o_recoverability_trigger": {
        "description": "RG-RALNS without recoverability trigger (always dispatch)",
        "overrides": {
            "rg_ralns": {
                "bottleneck_trigger_mode": "normal",
                "early_rescue_trigger": False,
            },
        },
        "note": "Full trigger disable requires code change to force trigger bypass.",
    },
    "w_o_service_safe_extraction": {
        "description": "RG-RALNS without service-safe extraction (service_first acceptance)",
        "overrides": {
            "rg_ralns": {
                "acceptance_mode": "service_first",
            },
        },
    },
    "w_o_service_safe_acceptance": {
        "description": "RG-RALNS without service-safe candidate acceptance",
        "overrides": {
            "rg_ralns": {
                "acceptance_mode": "service_first",
            },
        },
        "note": "Currently same as w_o_service_safe_extraction; separate code path needed for distinct ablation.",
    },
    "w_o_local_alns": {
        "description": "Lightweight RG Dispatch only (no local ALNS)",
        "overrides": {},
        "algorithm_subset": ["lightweight_rg_dispatch"],
    },
    "capacity_rescue_enabled_diagnostic": {
        "description": "Diagnostic variant with capacity rescue enabled (NOT default)",
        "overrides": {
            "rg_ralns": {
                "capacity_rescue_enabled": True,
            },
        },
    },
}

SCALABILITY_CONFIGS: dict[str, dict[str, object]] = {
    "small": {
        "n_jobs": 20,
        "n_machines": 5,
        "n_entities": 3,
    },
    "medium": {
        "n_jobs": 50,
        "n_machines": 10,
        "n_entities": 5,
    },
    "large": {
        "n_jobs": 100,
        "n_machines": 20,
        "n_entities": 8,
    },
    "xlarge": {
        "n_jobs": 200,
        "n_machines": 40,
        "n_entities": 12,
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git_branch() -> str:
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, cwd=PROJECT_ROOT,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=PROJECT_ROOT,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def _run_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_metadata(output_dir: Path, suite_name: str, extra: dict | None = None) -> Path:
    import json
    output_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "suite": suite_name,
        "git_branch": _git_branch(),
        "git_commit": _git_commit(),
        "run_timestamp_utc": _run_timestamp(),
        "project_root": str(PROJECT_ROOT),
    }
    if extra:
        meta.update(extra)
    path = output_dir / "run_metadata.json"
    path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return path


def _parse_algorithm_list(algorithms: list[str] | None) -> list[str] | None:
    """Normalise algorithm name aliases to the internal keys."""
    if algorithms is None:
        return None
    alias_map = {
        "EDD": "edd",
        "SPT": "spt",
        "WSPT": "wspt",
        "ATC": "atc",
        "SWD": "swd",
        "SFG": "sfg",
        "Lightweight_RG_Dispatch": "lightweight_rg_dispatch",
        "LightweightRG": "lightweight_rg_dispatch",
        "Online_Legacy_ALNS": "online_legacy_rg_alns",
        "OnlineLegacyALNS": "online_legacy_rg_alns",
        "RG_RALNS": "rg_ralns",
        "RGRALNS": "rg_ralns",
    }
    return [alias_map.get(a, a) for a in algorithms]


# ---------------------------------------------------------------------------
# Suite runners
# ---------------------------------------------------------------------------

def run_suite_pilot(
    config_path: Path,
    output_dir: Path,
    seeds: list[int],
    beta_0: float,
    algorithms: list[str],
) -> dict:
    """Small pilot validation run."""
    module_dir = output_dir / "pilot"
    _write_metadata(module_dir, "pilot", {
        "seeds": seeds,
        "beta_0": beta_0,
        "algorithms": algorithms,
    })

    config_overrides = {
        "algorithms": {"main_online": algorithms, "offline_oracle": []},
        "objective": {"beta_0": beta_0},
    }

    return run_paper_a_online_benchmark(
        config_path=config_path,
        seeds=seeds,
        output_dir=module_dir,
        config_overrides=config_overrides,
    )


def run_suite_main(
    config_path: Path,
    output_dir: Path,
    seeds: list[int],
    algorithms: list[str] | None = None,
) -> dict:
    """Main online comparison table."""
    module_dir = output_dir / "main_comparison"
    algos = algorithms or ALL_MAIN_ALGORITHMS
    _write_metadata(module_dir, "main_comparison", {
        "seeds": seeds,
        "algorithms": algos,
    })

    config_overrides = {
        "algorithms": {"main_online": algos, "offline_oracle": []},
    }

    return run_paper_a_online_benchmark(
        config_path=config_path,
        seeds=seeds,
        output_dir=module_dir,
        config_overrides=config_overrides,
    )


def run_suite_beta_sensitivity(
    config_path: Path,
    output_dir: Path,
    seeds: list[int],
    algorithms: list[str] | None = None,
) -> dict:
    """Beta sensitivity analysis."""
    module_dir = output_dir / "beta_sensitivity"
    algos = algorithms or BETA_SENSITIVITY_ALGORITHMS
    _write_metadata(module_dir, "beta_sensitivity", {
        "seeds": seeds,
        "algorithms": algos,
    })

    config_overrides = {
        "algorithms": {"main_online": algos, "offline_oracle": []},
    }

    return run_paper_a_online_benchmark(
        config_path=config_path,
        seeds=seeds,
        output_dir=module_dir,
        config_overrides=config_overrides,
    )


def run_suite_ablation(
    config_path: Path,
    output_dir: Path,
    seeds: list[int],
) -> dict:
    """Ablation study: run each variant as a separate benchmark call."""
    module_dir = output_dir / "ablation"
    _write_metadata(module_dir, "ablation", {
        "seeds": seeds,
        "variants": list(ABLATION_VARIANTS),
    })

    all_results: dict[str, dict] = {}
    for variant_name, variant_def in ABLATION_VARIANTS.items():
        variant_dir = module_dir / variant_name
        overrides: dict = dict(variant_def.get("overrides", {}))
        algo_subset = variant_def.get("algorithm_subset")
        if algo_subset:
            overrides["algorithms"] = {"main_online": list(algo_subset), "offline_oracle": []}
        else:
            overrides["algorithms"] = {"main_online": ["rg_ralns"], "offline_oracle": []}

        if not overrides:
            overrides = None  # type: ignore[assignment]

        _write_metadata(variant_dir, f"ablation/{variant_name}", {
            "description": variant_def.get("description", ""),
            "note": variant_def.get("note", ""),
            "seeds": seeds,
        })

        result = run_paper_a_online_benchmark(
            config_path=config_path,
            seeds=seeds,
            output_dir=variant_dir,
            config_overrides=overrides,  # type: ignore[arg-type]
        )
        all_results[variant_name] = result
    return all_results


def run_suite_mechanism(
    config_path: Path,
    output_dir: Path,
    seeds: list[int],
) -> dict:
    """Mechanism analysis: run RG-RALNS with debug trace enabled."""
    module_dir = output_dir / "mechanism"
    _write_metadata(module_dir, "mechanism", {
        "seeds": seeds,
    })

    config_overrides = {
        "algorithms": {"main_online": ["rg_ralns"], "offline_oracle": []},
        "rg_ralns": {"debug_trace": True},
    }

    return run_paper_a_online_benchmark(
        config_path=config_path,
        seeds=seeds,
        output_dir=module_dir,
        config_overrides=config_overrides,
        rg_debug_trace=True,
    )


def run_suite_scalability(
    config_path: Path,
    output_dir: Path,
    seeds: list[int],
    algorithms: list[str] | None = None,
    scales: list[str] | None = None,
) -> dict:
    """Scalability analysis across instance sizes."""
    module_dir = output_dir / "scalability"
    algos = algorithms or BETA_SENSITIVITY_ALGORITHMS
    selected_scales = scales or list(SCALABILITY_CONFIGS)
    _write_metadata(module_dir, "scalability", {
        "seeds": seeds,
        "algorithms": algos,
        "scales": selected_scales,
    })

    all_results: dict[str, dict] = {}
    for scale_name in selected_scales:
        scale_cfg = SCALABILITY_CONFIGS.get(scale_name)
        if scale_cfg is None:
            print(f"  [WARN] Unknown scale '{scale_name}', skipping.")
            continue
        scale_dir = module_dir / scale_name
        _write_metadata(scale_dir, f"scalability/{scale_name}", {
            "scale_config": scale_cfg,
            "seeds": seeds,
        })

        config_overrides = {
            "algorithms": {"main_online": algos, "offline_oracle": []},
            "instances": {
                f"scale_{scale_name}": {
                    "num_instances": 1,
                    "num_jobs": scale_cfg["n_jobs"],
                    "num_machines": scale_cfg["n_machines"],
                    "num_entities": scale_cfg["n_entities"],
                    "ops_per_job": [2, 4],
                    "rho_range": [0.65, 0.80],
                    "deadline_tightness": 1.25,
                    "effective_due_spread": 0.30,
                    "weight_pattern": "mild",
                    "quantity_range": [1, 5],
                    "proc_time_range": [2, 20],
                    "transport_delay_range": [0, 8],
                    "eligible_machines_range": [1, 3],
                    "arrival_intensity": "medium",
                    "alpha": 1.0,
                    "beta": 1.0,
                },
            },
        }

        result = run_paper_a_online_benchmark(
            config_path=config_path,
            seeds=seeds,
            output_dir=scale_dir,
            config_overrides=config_overrides,
        )
        all_results[scale_name] = result
    return all_results


def run_suite_robustness(
    config_path: Path,
    output_dir: Path,
    seeds: list[int],
    algorithms: list[str] | None = None,
) -> dict:
    """Seed robustness analysis."""
    module_dir = output_dir / "robustness"
    algos = algorithms or ALL_MAIN_ALGORITHMS
    _write_metadata(module_dir, "robustness", {
        "seeds": seeds,
        "algorithms": algos,
    })

    config_overrides = {
        "algorithms": {"main_online": algos, "offline_oracle": []},
    }

    return run_paper_a_online_benchmark(
        config_path=config_path,
        seeds=seeds,
        output_dir=module_dir,
        config_overrides=config_overrides,
    )


# ---------------------------------------------------------------------------
# Suite registry
# ---------------------------------------------------------------------------

SUITE_RUNNERS = {
    "pilot": run_suite_pilot,
    "main": run_suite_main,
    "beta_sensitivity": run_suite_beta_sensitivity,
    "ablation": run_suite_ablation,
    "mechanism": run_suite_mechanism,
    "scalability": run_suite_scalability,
    "robustness": run_suite_robustness,
    "all": None,  # special: run all suites
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs" / "paper_a_online.yaml",
        help="Path to the Paper A online benchmark config.",
    )
    parser.add_argument(
        "--suite",
        choices=list(SUITE_RUNNERS),
        default="pilot",
        help="Experiment suite to run (default: pilot).",
    )
    parser.add_argument(
        "--seeds", type=int, nargs="+", default=[0],
        help="Seeds to use (default: [0]).",
    )
    parser.add_argument(
        "--objective-beta",
        type=float,
        default=20.0,
        help="Override objective.beta_0 (default: 20.0).",
    )
    parser.add_argument(
        "--algorithms",
        nargs="+",
        default=None,
        help="Algorithm keys for the selected suite. Accepts friendly names "
             "(EDD, SPT, WSPT, ATC, SWD, SFG, Lightweight_RG_Dispatch, "
             "Online_Legacy_ALNS, RG_RALNS).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "results" / "paper_a_experiment_suite",
        help="Root output directory.",
    )
    parser.add_argument(
        "--scales",
        nargs="+",
        choices=list(SCALABILITY_CONFIGS),
        default=None,
        help="Scale labels for the scalability suite.",
    )
    args = parser.parse_args()

    config_path: Path = args.config
    output_dir: Path = args.output
    suite: str = args.suite
    seeds: list[int] = args.seeds
    beta_0: float = args.objective_beta
    algorithms: list[str] | None = _parse_algorithm_list(args.algorithms)

    if not config_path.exists():
        print(f"ERROR: config file not found: {config_path}")
        sys.exit(1)

    print(f"=== Paper A Experiment Suite ===")
    print(f"  Config:       {config_path}")
    print(f"  Suite:        {suite}")
    print(f"  Seeds:        {seeds}")
    print(f"  Beta_0:       {beta_0}")
    print(f"  Algorithms:   {algorithms or '(default for suite)'}")
    print(f"  Output:       {output_dir}")
    print(f"  Git branch:   {_git_branch()}")
    print(f"  Git commit:   {_git_commit()}")
    print(f"  Timestamp:    {_run_timestamp()}")
    print()

    output_dir.mkdir(parents=True, exist_ok=True)

    # Root metadata
    _write_metadata(output_dir, f"suite_{suite}", {
        "config_path": str(config_path),
        "seeds": seeds,
        "beta_0": beta_0,
        "algorithms": algorithms,
    })

    if suite == "all":
        suites_to_run = [k for k in SUITE_RUNNERS if k not in ("all", "pilot")]
    else:
        suites_to_run = [suite]

    overall_start = time.perf_counter()
    for suite_name in suites_to_run:
        runner = SUITE_RUNNERS.get(suite_name)
        if runner is None:
            print(f"  [SKIP] Unknown suite: {suite_name}")
            continue

        print(f"--- Running suite: {suite_name} ---")
        suite_start = time.perf_counter()
        try:
            kwargs = {
                "config_path": config_path,
                "output_dir": output_dir,
                "seeds": seeds,
            }
            if suite_name in ("pilot",):
                kwargs["beta_0"] = beta_0
                kwargs["algorithms"] = algorithms or BETA_SENSITIVITY_ALGORITHMS
            elif suite_name in ("main", "robustness"):
                kwargs["algorithms"] = algorithms
            elif suite_name in ("beta_sensitivity", "scalability"):
                kwargs["algorithms"] = algorithms
            elif suite_name == "scalability":
                kwargs["scales"] = args.scales

            result = runner(**kwargs)
            elapsed = time.perf_counter() - suite_start
            if isinstance(result, dict):
                out_count = result.get("per_instance_rows", "?")
                print(f"  [OK] {suite_name} completed in {elapsed:.1f}s "
                      f"({out_count} per-instance rows)")
            else:
                print(f"  [OK] {suite_name} completed in {elapsed:.1f}s")
        except Exception as exc:
            elapsed = time.perf_counter() - suite_start
            print(f"  [FAIL] {suite_name} after {elapsed:.1f}s: {exc}")

    overall_elapsed = time.perf_counter() - overall_start
    print(f"\n=== Suite complete in {overall_elapsed:.1f}s ===")
    print(f"  Output: {output_dir}")


if __name__ == "__main__":
    main()
