"""Pilot benchmark runner.

Generates or loads small sets of medium and high service-pressure SL-ISP
instances, runs the six algorithms, and records per-run metrics for analysis.

Usage:
    python3 -m src.experiments.run_pilot_benchmark
"""

import csv
import logging
import os
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import yaml

from src.core.dataclasses import SLISPInstance
from src.core.objective import compute_objective
from src.core.schedule_state import ScheduleState
from src.core.simulator import run_simulation
from src.generation.instance_generator import (
    InstanceConfig,
    generate_instance,
)
from src.generation.scenario_builder import build_dynamic_scenario

# Algorithm imports
from src.algorithms.dispatching_rules import (
    edd_rule,
    swd_rule,
    sfg_rule,
)
from src.algorithms.rg_rho_lns_fast import (
    run_plain_rho_fast,
    run_rho_lns_fast,
    run_rg_rho_fast,
    run_rg_rho_lns_fast,
    run_rg_rho_lns_fast_v11,
    run_adaptive_rg_rho_lns_fast,
    run_rg_alns,
    run_rg_alns_small_oracle,
    run_nr_rg_rho_lns,
    run_nr_rg_rho_lns_small_oracle,
)
from src.algorithms.rg_ralns import (
    run_lightweight_rg_dispatch,
    run_rg_ralns,
)
from src.algorithms.baselines_fast import (
    spt_rule,
    wspt_rule,
    atc_rule,
    run_ils_fast,
    run_vns_fast,
    run_ts_fast,
    run_sa_fast,
    run_ga_fast,
)

# For post-hoc mandatory job computation on non-RG algorithms
from src.recoverability.mandatory_jobs import mandatory_rescue_jobs
from src.recoverability.shortfall_bounds import (
    unavoidable_shortfall_lower_bound,
)

logging.basicConfig(
    level=logging.WARNING,  # suppress INFO logs from RG-RHO-LNS
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pilot_benchmark")
logger.setLevel(logging.INFO)


# ── Algorithm factory ──────────────────────────────────────────────────────────

def _rg_alns_kwargs(
    algo_cfg: dict,
    seed: int,
    default_lns_iterations: int = 20,
) -> dict:
    """Map shared RG-ALNS config fields to constructor kwargs."""

    return {
        "horizon": algo_cfg.get("horizon", 300),
        "lns_iterations": algo_cfg.get("lns_iterations", default_lns_iterations),
        "exact_local_job_limit": algo_cfg.get("exact_local_job_limit", 8),
        "exact_local_time_limit_s": algo_cfg.get("exact_local_time_limit_s", 0.2),
        "use_sequence_crossover": algo_cfg.get("use_sequence_crossover", True),
        "sequence_crossover_trials": algo_cfg.get("sequence_crossover_trials", 4),
        "dispatch_mode": algo_cfg.get("dispatch_mode", "standard_projected"),
        "seed": seed,
    }


def _nr_rg_rho_lns_kwargs(
    algo_cfg: dict,
    seed: int,
    default_lns_iterations: int = 20,
) -> dict:
    """Backward-compatible alias for legacy NR-RG-RHO-LNS config entries."""
    return _rg_alns_kwargs(algo_cfg, seed, default_lns_iterations)


def _rg_ralns_kwargs(algo_cfg: dict, seed: int) -> dict:
    """Map Paper A RG-RALNS config fields to constructor kwargs."""

    return {
        "H_A": algo_cfg.get("H_A", algo_cfg.get("h_a", 12)),
        "N_A": algo_cfg.get("N_A", algo_cfg.get("n_a", 30)),
        "alpha": algo_cfg.get("alpha", None),
        "beta": algo_cfg.get("beta", None),
        "regret_k": algo_cfg.get("regret_k", 2),
        "eps": algo_cfg.get("eps", 1e-9),
        "random_seed": algo_cfg.get("random_seed", seed),
        "destroy_fraction": algo_cfg.get("destroy_fraction", 0.35),
    }


def _uses_online_visibility(algo_cfg: dict) -> bool:
    """RG-RALNS algorithms must run through OnlineProblemView by default."""

    algo_type = algo_cfg.get("type")
    default_online = algo_type in {"rg_ralns", "lightweight_rg_dispatch"}
    return bool(algo_cfg.get("online_visibility", default_online))


def _create_algorithm(algo_key: str, algo_cfg: dict, seed: int = 42):
    """Build a fresh algorithm instance/callable from its config entry.

    Returns (callable, label).
    The callable must match SchedulingAlgorithm signature:
        (instance, state) -> list[(job_id, op_id, machine_id, start_time)]
    """
    algo_type = algo_cfg["type"]
    label: str = algo_cfg.get("label", "RG-ALNS" if algo_type == "rg_alns" else algo_key)

    if algo_type == "dispatching":
        if algo_key == "edd":
            return edd_rule, label
        elif algo_key == "swd":
            return swd_rule, label
        elif algo_key == "sfg":
            return sfg_rule, label
        elif algo_key == "spt":
            return spt_rule, label
        elif algo_key == "wspt":
            return wspt_rule, label
        elif algo_key == "atc":
            return atc_rule, label
        else:
            raise ValueError(f"Unknown dispatching rule: {algo_key}")

    # ── Solver-free algorithm types ───────────────────────────────────────────
    elif algo_type == "rho_fast":
        return (run_plain_rho_fast(
            horizon=algo_cfg.get("horizon", 300),
            seed=seed,
        ), label)

    elif algo_type == "rho_lns_fast":
        return (run_rho_lns_fast(
            horizon=algo_cfg.get("horizon", 300),
            lns_iterations=algo_cfg.get("lns_iterations", 20),
            seed=seed,
        ), label)

    elif algo_type == "rg_rho_fast":
        return (run_rg_rho_fast(
            horizon=algo_cfg.get("horizon", 300),
            seed=seed,
        ), label)

    elif algo_type == "rg_rho_lns_fast":
        return (run_rg_rho_lns_fast(
            horizon=algo_cfg.get("horizon", 300),
            lns_iterations=algo_cfg.get("lns_iterations", 20),
            seed=seed,
        ), label)

    elif algo_type == "rg_rho_lns_fast_v11":
        return (run_rg_rho_lns_fast_v11(
            horizon=algo_cfg.get("horizon", 300),
            lns_iterations=algo_cfg.get("lns_iterations", 40),
            seed=seed,
        ), label)

    elif algo_type == "adaptive_rg_rho_lns_fast":
        return (run_adaptive_rg_rho_lns_fast(
            horizon=algo_cfg.get("horizon", 300),
            lns_iterations=algo_cfg.get("lns_iterations", 40),
            seed=seed,
        ), label)

    elif algo_type == "rg_alns":
        algo = run_rg_alns(
            **_rg_alns_kwargs(algo_cfg, seed),
        )
        return (algo, label)

    elif algo_type == "rg_alns_small_oracle":
        algo = run_rg_alns_small_oracle(
            **_rg_alns_kwargs(algo_cfg, seed),
        )
        return (algo, label)

    elif algo_type == "nr_rg_rho_lns":
        algo = run_nr_rg_rho_lns(
            **_rg_alns_kwargs(algo_cfg, seed),
        )
        return (algo, label)

    elif algo_type == "nr_rg_rho_lns_small_oracle":
        algo = run_nr_rg_rho_lns_small_oracle(
            **_rg_alns_kwargs(algo_cfg, seed),
        )
        return (algo, label)

    elif algo_type == "rg_ralns":
        algo = run_rg_ralns(
            **_rg_ralns_kwargs(algo_cfg, seed),
        )
        return (algo, label)

    elif algo_type == "lightweight_rg_dispatch":
        algo = run_lightweight_rg_dispatch(
            **_rg_ralns_kwargs(algo_cfg, seed),
        )
        return (algo, label)

    # ── Metaheuristic baselines ────────────────────────────────────────────
    elif algo_type == "ils_fast":
        return (run_ils_fast(
            horizon=algo_cfg.get("horizon", 300),
            max_iter=algo_cfg.get("max_iter", 100),
            seed=seed,
        ), label)

    elif algo_type == "vns_fast":
        return (run_vns_fast(
            horizon=algo_cfg.get("horizon", 300),
            max_iter=algo_cfg.get("max_iter", 100),
            seed=seed,
        ), label)

    elif algo_type == "ts_fast":
        return (run_ts_fast(
            horizon=algo_cfg.get("horizon", 300),
            max_iter=algo_cfg.get("max_iter", 100),
            tabu_tenure=algo_cfg.get("tabu_tenure", 7),
            seed=seed,
        ), label)

    elif algo_type == "sa_fast":
        return (run_sa_fast(
            horizon=algo_cfg.get("horizon", 300),
            max_iter=algo_cfg.get("max_iter", 100),
            initial_temperature_ratio=algo_cfg.get("initial_temperature_ratio", 0.10),
            cooling_rate=algo_cfg.get("cooling_rate", 0.95),
            seed=seed,
        ), label)

    elif algo_type == "ga_fast":
        return (run_ga_fast(
            horizon=algo_cfg.get("horizon", 300),
            max_iter=algo_cfg.get("max_iter", 60),
            population_size=algo_cfg.get("population_size", 16),
            crossover_rate=algo_cfg.get("crossover_rate", 0.85),
            mutation_rate=algo_cfg.get("mutation_rate", 0.20),
            elite_size=algo_cfg.get("elite_size", 2),
            seed=seed,
        ), label)

    else:
        raise ValueError(f"Unknown algorithm type: {algo_type}")


# ── Event-count wrapper ────────────────────────────────────────────────────────

class _EventCounter:
    """Wraps a scheduling algorithm to count invocations (decision events)."""

    def __init__(self, inner, label: str = ""):
        self._inner = inner
        self.label = label
        self.count = 0

    def __call__(self, instance, state):
        self.count += 1
        return self._inner(instance, state)


# ── Parallel worker ────────────────────────────────────────────────────────────

_ALGO_TYPES_ITERATIVE = {
    "rho_lns_fast", "rg_rho_lns_fast_v11", "adaptive_rg_rho_lns_fast",
    "ils_fast", "vns_fast", "ts_fast", "sa_fast", "ga_fast",
    "rg_alns", "rg_alns_small_oracle",
    "nr_rg_rho_lns", "nr_rg_rho_lns_small_oracle",
    "rg_ralns", "lightweight_rg_dispatch",
}


def _append_rg_ralns_stats(row: dict, algo_callable) -> None:
    """Add RG-RALNS event/local-search diagnostics when available."""

    inner = getattr(algo_callable, "_inner", algo_callable)
    if not hasattr(inner, "trigger_count"):
        return
    row.update({
        "trigger_count": inner.trigger_count,
        "trigger_reason_counts": dict(inner.trigger_reason_counts),
        "avg_A_size": round(inner.avg_A_size, 4),
        "max_A_size": inner.max_A_size,
        "alns_runtime_total": round(inner.alns_runtime_total, 6),
        "dispatch_fallback_count": inner.dispatch_fallback_count,
    })


def _run_single_simulation(instance, algo_key: str, algo_cfg: dict, run_seed: int
                           ) -> dict:
    """Run one simulation in a worker process. Returns a result row dict."""
    from src.core.simulator import run_simulation
    algo_label = algo_cfg.get("label", algo_key)
    t_start = time.perf_counter()
    try:
        algo_callable, algo_label = _create_algorithm(algo_key, algo_cfg, seed=run_seed)
        final_state, obj_result = run_simulation(
            instance,
            algo_callable,
            online_visibility=_uses_online_visibility(algo_cfg),
        )
        runtime_s = time.perf_counter() - t_start
        row = {
            "algorithm": algo_key, "algorithm_label": algo_label,
            "status": "OK",
            "Z": obj_result.Z, "TT": obj_result.total_tardiness,
            "WSF": obj_result.weighted_service_shortfall,
            "ZSR": obj_result.zero_shortfall_entity_rate,
            "runtime_total_s": round(runtime_s, 4),
        }
        _append_rg_ralns_stats(row, algo_callable)
        # Collect convergence logs if available
        inner = getattr(algo_callable, '_inner', algo_callable)
        if hasattr(inner, '_convergence_log'):
            row["_convergence_log"] = list(inner._convergence_log)
        if hasattr(inner, '_diag_init_candidates'):
            row["_init_candidates"] = list(inner._diag_init_candidates)
        if hasattr(inner, '_rollout_portfolio_diag'):
            row["_rollout_portfolio_diag"] = list(inner._rollout_portfolio_diag)
    except Exception as exc:
        runtime_s = time.perf_counter() - t_start
        row = _failed_result_row(algo_key, algo_label, exc, runtime_s)
    return row


def _failed_result_row(
    algo_key: str,
    algo_label: str,
    exc: BaseException,
    runtime_s: float,
) -> dict:
    """Build a failed benchmark row with enough diagnostics to debug later."""
    return {
        "algorithm": algo_key,
        "algorithm_label": algo_label,
        "status": "FAILED",
        "Z": None,
        "TT": None,
        "WSF": None,
        "ZSR": None,
        "runtime_total_s": round(runtime_s, 4),
        "error_type": exc.__class__.__name__,
        "error_message": str(exc),
        "error_traceback": "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ),
    }


# ── Instance generation ────────────────────────────────────────────────────────

def _build_instance_config(pressure_cfg: dict, seed: int, idx: int) -> InstanceConfig:
    """Build an InstanceConfig from a pressure-level config dict."""
    num_jobs = pressure_cfg["num_jobs"]
    return InstanceConfig(
        group_name="pilot",
        num_instances=1,
        num_jobs=num_jobs,
        num_machines=pressure_cfg["num_machines"],
        num_entities=pressure_cfg["num_entities"],
        ops_per_job=tuple(pressure_cfg["ops_per_job"]),
        rho_range=tuple(pressure_cfg["rho_range"]),
        deadline_tightness=pressure_cfg["deadline_tightness"],
        weight_pattern=pressure_cfg["weight_pattern"],
        proc_time_range=tuple(pressure_cfg.get("proc_time_range", [1, 100])),
        transport_delay_range=tuple(
            pressure_cfg.get("transport_delay_range", [20, 60])
        ),
        eligible_machines_range=tuple(
            pressure_cfg.get("eligible_machines_range", [2, 5])
        ),
        alpha=pressure_cfg.get("alpha", 1.0),
        beta=pressure_cfg.get("beta", 1.0),
        effective_due_spread=pressure_cfg.get("effective_due_spread", 0.0),
        effective_due_multipliers=(
            tuple(pressure_cfg["effective_due_multipliers"])
            if pressure_cfg.get("effective_due_multipliers") is not None
            else None
        ),
        release_time_mode=pressure_cfg.get("release_time_mode", "static"),
        arrival_intensity=pressure_cfg.get("arrival_intensity", "static"),
    )


def _merge_combination_config(pressure_cfg: dict, combo: dict) -> dict:
    """Merge a size combination into a pressure-level instance config."""
    combo_cfg = dict(pressure_cfg)
    combo_cfg.pop("combinations", None)
    for key in (
        "num_jobs",
        "num_machines",
        "num_entities",
        "ops_per_job",
        "rho_range",
        "deadline_tightness",
        "weight_pattern",
        "proc_time_range",
        "transport_delay_range",
        "eligible_machines_range",
        "alpha",
        "beta",
        "effective_due_spread",
        "effective_due_multipliers",
        "arrival_intensity",
        "release_time_mode",
    ):
        if key in combo:
            combo_cfg[key] = combo[key]
    combo_cfg["num_instances"] = combo.get("num_instances", 1)
    return combo_cfg


def _generate_instance(pressure_cfg: dict, seed: int, idx: int) -> SLISPInstance:
    """Generate one instance for a given pressure level."""
    inst_cfg = _build_instance_config(pressure_cfg, seed, idx)
    # Use seed derived from config seed + index
    instance_seed = seed + idx * 10007
    base = generate_instance(inst_cfg, instance_seed, instance_index=0)

    arrival_intensity = pressure_cfg.get("arrival_intensity", "static")
    if arrival_intensity != "static":
        return build_dynamic_scenario(
            base,
            arrival_intensity=arrival_intensity,
            seed=instance_seed + 1,
        )
    return base


# ── Post-hoc mandatory metrics for non-RG algorithms ───────────────────────────

def _initial_state(instance: SLISPInstance) -> ScheduleState:
    """Create a fresh ScheduleState at t=0."""
    state = ScheduleState()
    for m in instance.machines:
        state.machine_available_times[m.machine_id] = 0
    return state


def _compute_mandatory_metrics(
    instance: SLISPInstance,
    initial_state: ScheduleState,
    final_state: ScheduleState,
) -> tuple[int, int]:
    """Identify mandatory jobs at t=0 and check on-time delivery at final state."""
    pool_B = {m.machine_id for m in instance.machines}
    all_mandatory: set[int] = set()
    for entity in instance.entities:
        mand = mandatory_rescue_jobs(
            entity.entity_id, pool_B, initial_state, instance, method="dp"
        )
        all_mandatory.update(mand)

    identified = len(all_mandatory)
    on_time = 0
    for jid in all_mandatory:
        if final_state.is_job_completed(jid):
            job = instance.get_job(jid)
            entity = instance.get_entity(job.entity_id)
            delivery = final_state.completed_jobs[jid] + entity.transport_delay
            if delivery <= entity.deadline:
                on_time += 1

    return identified, on_time


def _compute_shortfall_bound_sum(
    instance: SLISPInstance, state: ScheduleState
) -> int:
    """Sum of unavoidable shortfall lower bounds across entities at t=0."""
    pool_B = {m.machine_id for m in instance.machines}
    total = 0
    for entity in instance.entities:
        u = unavoidable_shortfall_lower_bound(
            entity.entity_id, pool_B, state, instance, method="dp"
        )
        total += u
    return total


# ── Main runner ────────────────────────────────────────────────────────────────

def _collect_fast_diagnostics(algo_callable, pressure_key: str, inst_idx: int,
                              seed_idx: int, algo_key: str, algo_label: str
                              ) -> tuple[list[dict], list[dict]]:
    """Collect operator and mechanism diagnostics from solver-free algorithms."""
    op_rows: list[dict] = []
    mech_rows: list[dict] = []

    inner = getattr(algo_callable, '_inner', algo_callable)
    if not hasattr(inner, '_diag_destroy_usage'):
        return op_rows, mech_rows

    base = {
        "pressure_level": pressure_key,
        "instance_index": inst_idx,
        "seed_index": seed_idx,
        "algorithm": algo_key,
        "algorithm_label": algo_label,
    }

    # ── Operator success diagnostics ──
    for d_name in inner._diag_destroy_usage:
        usage = inner._diag_destroy_usage.get(d_name, 0)
        improvements = inner._diag_destroy_improvements.get(d_name, 0)
        mags = inner._diag_destroy_improvement_magnitudes.get(d_name, [])
        op_rows.append({
            **base,
            "operator_type": "destroy",
            "operator_name": f"destroy_{d_name}",
            "usage_count": usage,
            "improvement_count": improvements,
            "success_rate": improvements / max(1, usage),
            "mean_improvement": sum(mags) / max(1, len(mags)),
            "total_improvement": sum(mags),
            "final_weight": getattr(inner, "_destroy_operator_weights", {}).get(d_name, 1.0),
        })

    for r_name in inner._diag_repair_usage:
        usage = inner._diag_repair_usage.get(r_name, 0)
        improvements = inner._diag_repair_improvements.get(r_name, 0)
        mags = inner._diag_repair_improvement_magnitudes.get(r_name, [])
        op_rows.append({
            **base,
            "operator_type": "repair",
            "operator_name": f"repair_{r_name}",
            "usage_count": usage,
            "improvement_count": improvements,
            "success_rate": improvements / max(1, usage),
            "mean_improvement": sum(mags) / max(1, len(mags)),
            "total_improvement": sum(mags),
            "final_weight": getattr(inner, "_repair_operator_weights", {}).get(r_name, 1.0),
        })

    # Local search
    op_rows.append({
        **base,
        "operator_type": "local_search",
        "operator_name": "local_search",
        "usage_count": inner._diag_total_ls_attempts,
        "improvement_count": inner._diag_total_ls_improvements,
        "success_rate": inner._diag_total_ls_improvements / max(1, inner._diag_total_ls_attempts),
        "mean_improvement": sum(inner._diag_total_ls_magnitudes) / max(1, len(inner._diag_total_ls_magnitudes)),
        "total_improvement": sum(inner._diag_total_ls_magnitudes),
    })

    # LNS summary
    op_rows.append({
        **base,
        "operator_type": "lns_overall",
        "operator_name": "lns_overall",
        "usage_count": inner._diag_lns_iterations_total,
        "improvement_count": inner._diag_lns_improvements_total,
        "success_rate": inner._diag_lns_improvements_total / max(1, inner._diag_lns_iterations_total),
        "mean_improvement": 0,
        "total_improvement": 0,
    })

    # ── RG mechanism diagnostics ──
    for sample in inner._diag_rg_score_samples:
        mech_rows.append({**base, "diag_type": "rg_score_distribution", **sample})

    if hasattr(inner, "_diag_operator_weight_log"):
        mech_rows.append({
            **base,
            "diag_type": "operator_learning_summary",
            "updates": len(inner._diag_operator_weight_log),
            "destroy_weights": dict(getattr(inner, "_destroy_operator_weights", {})),
            "repair_weights": dict(getattr(inner, "_repair_operator_weights", {})),
        })

    for i, mand_count in enumerate(inner._diag_mandatory_counts):
        mech_rows.append({
            **base, "diag_type": "mandatory_count",
            "event_index": i, "mandatory_count": mand_count,
        })

    return op_rows, mech_rows


def run_pilot(config_path: str | Path) -> dict:
    """Execute the pilot benchmark and return a summary dict."""
    config_path = Path(config_path)
    with open(config_path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)

    pilot_cfg = cfg["pilot"]
    instance_cfgs: dict[str, dict] = cfg["instances"]
    algo_cfgs: dict[str, dict] = cfg["algorithms"]
    output_cfg = cfg["output"]
    experiment_mode: str = pilot_cfg.get("experiment_mode", "normal")
    base_seed: int = pilot_cfg.get("seed", 42)
    num_seeds: int = pilot_cfg.get("num_seeds", 1)

    project_root = config_path.parents[1]
    raw_csv_path = project_root / output_cfg["raw_csv"]
    os.makedirs(raw_csv_path.parent, exist_ok=True)

    raw_rows: list[dict] = []
    op_diag_rows: list[dict] = []
    mech_diag_rows: list[dict] = []

    # Count total runs for combinations-based configs
    total_runs = 0
    for pressure_cfg in instance_cfgs.values():
        combos = pressure_cfg.get("combinations", None)
        if combos:
            n_inst = sum(combo.get("num_instances", 1) for combo in combos)
        else:
            n_inst = pressure_cfg.get("num_instances", 1)
        total_runs += n_inst * len(algo_cfgs) * num_seeds
    logger.info("Expanded validation: %d runs total (%d seeds per instance)",
                total_runs, num_seeds)

    # All algorithms run in parallel for large instances
    serial_algos = {}
    parallel_algos = {}
    for k, v in algo_cfgs.items():
        parallel_algos[k] = v  # everything parallel

    serial_work: list[tuple] = []
    parallel_work: list[tuple] = []
    inst_idx = 0

    for pressure_key, pressure_cfg in instance_cfgs.items():
        pressure_label: str = pressure_cfg.get("label", pressure_key)
        combinations = pressure_cfg.get("combinations", None)

        if combinations:
            instance_subset: list[tuple[dict, str]] = []
            for combo in combinations:
                combo_cfg = _merge_combination_config(pressure_cfg, combo)
                nj = combo_cfg.get("num_jobs", 12)
                nm = combo_cfg.get("num_machines", 4)
                ne = combo_cfg.get("num_entities", pressure_cfg.get("num_entities", 1))
                instance_subset.append((combo_cfg, f"{pressure_label}-J{nj}-M{nm}-E{ne}"))
        else:
            num_inst = pressure_cfg.get("num_instances", 1)
            instance_subset = [(pressure_cfg, f"{pressure_label}-{i}") for i in range(num_inst)]

        for inst_cfg, _desc in instance_subset:
            instance = _generate_instance(inst_cfg, base_seed, inst_idx)
            for seed_idx in range(num_seeds):
                run_seed = base_seed + inst_idx * 10007 + seed_idx * 31337
                for algo_key, algo_cfg in serial_algos.items():
                    serial_work.append((instance, algo_key, algo_cfg, run_seed,
                                        pressure_key, pressure_label, inst_idx, seed_idx))
                for algo_key, algo_cfg in parallel_algos.items():
                    parallel_work.append((instance, algo_key, algo_cfg, run_seed,
                                          pressure_key, pressure_label, inst_idx, seed_idx))
            inst_idx += 1

    total_runs = len(serial_work) + len(parallel_work)
    logger.info("Total runs: %d (serial: %d, parallel: %d, %d seeds)",
                total_runs, len(serial_work), len(parallel_work), num_seeds)

    # ── Phase 1: Serial (dispatching rules + fast heuristics) ──────
    run_idx = 0
    for instance, algo_key, algo_cfg, run_seed, p_key, p_label, i_idx, s_idx in serial_work:
        run_idx += 1
        algo_label = algo_cfg.get("label", algo_key)
        logger.info("[%d/%d] SERIAL %s | %s | inst %d | seed %d",
                    run_idx, total_runs, p_label, algo_label, i_idx, s_idx)

        t_start = time.perf_counter()
        try:
            algo_callable, algo_label = _create_algorithm(algo_key, algo_cfg, seed=run_seed)
            final_state, obj_result = run_simulation(
                instance,
                algo_callable,
                online_visibility=_uses_online_visibility(algo_cfg),
            )
            runtime_s = time.perf_counter() - t_start
            row = {
                "pressure_level": p_key, "pressure_label": p_label,
                "instance_index": i_idx, "seed_index": s_idx,
                "algorithm": algo_key, "algorithm_label": algo_label,
                "status": "OK",
                "Z": obj_result.Z, "TT": obj_result.total_tardiness,
                "WSF": obj_result.weighted_service_shortfall,
                "ZSR": obj_result.zero_shortfall_entity_rate,
                "runtime_total_s": round(runtime_s, 4),
                "events_count": 0,
                "mandatory_jobs_identified_total": 0,
                "mandatory_jobs_on_time_total": 0,
                "shortfall_lower_bound_final_sum": 0,
            }
            _append_rg_ralns_stats(row, algo_callable)
            raw_rows.append(row)
        except Exception as exc:
            row = _failed_result_row(
                algo_key,
                algo_cfg.get("label", algo_key),
                exc,
                time.perf_counter() - t_start,
            )
            row.update({
                "pressure_level": p_key, "pressure_label": p_label,
                "instance_index": i_idx, "seed_index": s_idx,
                "events_count": 0,
                "mandatory_jobs_identified_total": 0,
                "mandatory_jobs_on_time_total": 0,
                "shortfall_lower_bound_final_sum": 0,
            })
            raw_rows.append(row)

    # ── Phase 2: Parallel (iterative algorithms) ──────────────────
    if parallel_work:
        n_workers = min(os.cpu_count() or 4, len(parallel_work))
        logger.info("Starting parallel phase with %d workers for %d tasks", n_workers, len(parallel_work))
        with ProcessPoolExecutor(max_workers=n_workers) as executor:
            futures = {}
            for instance, algo_key, algo_cfg, run_seed, p_key, p_label, i_idx, s_idx in parallel_work:
                fut = executor.submit(_run_single_simulation, instance, algo_key, algo_cfg, run_seed)
                futures[fut] = (p_key, p_label, i_idx, s_idx, algo_key, algo_cfg.get("label", algo_key))

            for fut in as_completed(futures):
                p_key, p_label, i_idx, s_idx, algo_key, algo_label = futures[fut]
                run_idx += 1
                try:
                    row = fut.result()
                except Exception as exc:
                    row = _failed_result_row(algo_key, algo_label, exc, runtime_s=0.0)
                # Extract diagnostics before discarding
                conv_data = row.pop("_convergence_log", None)
                cand_data = row.pop("_init_candidates", None)
                portfolio_data = row.pop("_rollout_portfolio_diag", None)

                row.update({
                    "pressure_level": p_key, "pressure_label": p_label,
                    "instance_index": i_idx, "seed_index": s_idx,
                    "events_count": 0,
                    "mandatory_jobs_identified_total": 0,
                    "mandatory_jobs_on_time_total": 0,
                    "shortfall_lower_bound_final_sum": 0,
                })
                raw_rows.append(row)

                # Save convergence logs
                if conv_data:
                    conv_base = {"pressure_level": p_key, "instance_index": i_idx,
                                 "seed_index": s_idx, "algorithm": algo_key,
                                 "algorithm_label": algo_label}
                    for entry in conv_data:
                        entry.update(conv_base)
                    conv_csv_path = project_root / output_cfg.get(
                        "convergence_raw", "outputs/final_v13_validation/convergence_raw.csv")
                    _append_csv(conv_csv_path, conv_data)

                # Save candidate diagnostics
                if cand_data:
                    cand_base = {"pressure_level": p_key, "instance_index": i_idx,
                                 "seed_index": s_idx, "algorithm": algo_key}
                    for entry in cand_data:
                        entry.update(cand_base)
                    cand_csv_path = project_root / output_cfg.get(
                        "initial_candidate_performance",
                        "outputs/final_v13_validation/initial_candidate_performance.csv")
                    _append_csv(cand_csv_path, cand_data)

                if portfolio_data:
                    portfolio_base = {"pressure_level": p_key, "instance_index": i_idx,
                                      "seed_index": s_idx, "algorithm": algo_key}
                    for entry in portfolio_data:
                        entry.update(portfolio_base)
                    portfolio_csv_path = project_root / output_cfg.get(
                        "rollout_portfolio_raw",
                        "outputs/final_v13_validation/rollout_portfolio_raw.csv")
                    _append_csv(portfolio_csv_path, portfolio_data)

    # Write raw results
    _write_csv(raw_csv_path, raw_rows)
    logger.info("Raw results written to %s (%d rows)", raw_csv_path, len(raw_rows))

    return {
        "raw_rows": len(raw_rows),
        "raw_csv": str(raw_csv_path),
    }


def _write_csv(path: Path, rows: list[dict]) -> None:
    """Write a list of dicts as CSV."""
    if not rows:
        return
    # Collect all unique field names across all rows
    fieldnames = []
    seen = set()
    for row in rows:
        for k in row:
            if k not in seen:
                fieldnames.append(k)
                seen.add(k)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def _append_csv(path: Path, rows: list[dict]) -> None:
    """Append rows to a CSV file, creating it if needed."""
    if not rows:
        return
    os.makedirs(path.parent, exist_ok=True)
    file_exists = path.exists()
    if file_exists:
        with open(path, "r", newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            fieldnames = next(reader)
    else:
        # Collect all unique field names across all rows
        fieldnames = []
        seen = set()
        for row in rows:
            for k in row:
                if k not in seen:
                    fieldnames.append(k)
                    seen.add(k)
    with open(path, "a" if file_exists else "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction='ignore')
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


# ── CLI entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1:
        config_path = Path(sys.argv[1])
    else:
        config_path = Path(__file__).resolve().parents[2] / "configs" / "pilot_benchmark.yaml"
    if not config_path.exists():
        print(f"Config not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Running benchmark with config: {config_path}")
    summary = run_pilot(config_path)
    print(f"Done. {summary['raw_rows']} raw rows.")
    print(f"Raw CSV: {summary['raw_csv']}")
