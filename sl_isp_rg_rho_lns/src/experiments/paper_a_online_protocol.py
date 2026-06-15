"""Paper A online event-driven benchmark protocol.

This module keeps the Paper A benchmark protocol separate from legacy pilot
benchmark scripts.  Main-table algorithms run through the simulator's online
visibility mode and a shared current-time commit validator.
"""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

from src.algorithms.baselines_fast import (
    atc_rule,
    run_ga_fast,
    run_ils_fast,
    run_sa_fast,
    run_ts_fast,
    run_vns_fast,
    spt_rule,
    wspt_rule,
)
from src.algorithms.dispatching_rules import edd_rule, sfg_rule, swd_rule
from src.algorithms.rg_ralns import run_lightweight_rg_dispatch, run_rg_ralns
from src.algorithms.rg_rho_lns_fast import run_rg_alns
from src.core.dataclasses import ScheduledOperation, SLISPInstance
from src.core.objective import ObjectiveResult
from src.core.online import OnlineProblemView
from src.core.schedule_state import ScheduleState
from src.core.simulator import run_simulation
from src.generation.instance_generator import InstanceConfig, generate_instance
from src.generation.scenario_builder import build_dynamic_scenario

Decision = tuple[int, int, int, int]
SchedulingProblem = SLISPInstance | OnlineProblemView
SchedulingAlgorithm = Callable[[SchedulingProblem, ScheduleState], list[Decision]]

PROTOCOL_STATEMENT = (
    "All algorithms in the main comparison are evaluated under the same online "
    "event-driven simulation protocol. At each event time, an algorithm observes "
    "only arrived jobs, completed and ongoing operations, current machine states, "
    "and entity-level service parameters. Future jobs are not visible at the job "
    "level before arrival. Algorithms may generate internal local or rolling "
    "schedules, but only operations that are immediately executable at the current "
    "event time are committed to the simulator. The final performance is evaluated "
    "using the same global objective after the simulation terminates."
)


@dataclass(frozen=True)
class PaperAAlgorithmSpec:
    """Algorithm metadata for Paper A benchmark grouping."""

    key: str
    label: str
    algorithm_type: str
    table_group: str
    online_visibility: bool


@dataclass(frozen=True)
class ObjectiveCalibration:
    """Instance-level objective scale calibration for Paper A evaluation."""

    Theta_I: float
    Omega_I: float
    alpha_0: float
    beta_0: float
    alpha_I: float
    beta_I: float


class DecisionValidationError(ValueError):
    """Raised when an algorithm violates current-time execution policy."""


def default_paper_a_algorithm_specs(
    *,
    include_offline_oracle: bool = True,
) -> list[PaperAAlgorithmSpec]:
    """Return the default minimum Paper A algorithm list with explicit grouping."""

    specs = [
        PaperAAlgorithmSpec("edd", "EDD", "dispatching", "main_online", True),
        PaperAAlgorithmSpec("spt", "SPT", "dispatching", "main_online", True),
        PaperAAlgorithmSpec("wspt", "WSPT", "dispatching", "main_online", True),
        PaperAAlgorithmSpec("atc", "ATC", "dispatching", "main_online", True),
        PaperAAlgorithmSpec("swd", "SWD", "dispatching", "main_online", True),
        PaperAAlgorithmSpec("sfg", "SFG", "dispatching", "main_online", True),
        PaperAAlgorithmSpec(
            "lightweight_rg_dispatch",
            "Lightweight RG Dispatch",
            "lightweight_rg_dispatch",
            "main_online",
            True,
        ),
        PaperAAlgorithmSpec(
            "online_legacy_rg_alns",
            "Online-Legacy-ALNS",
            "legacy_rg_alns",
            "main_online",
            True,
        ),
        PaperAAlgorithmSpec(
            "rg_ralns",
            "RG-RALNS",
            "rg_ralns",
            "main_online",
            True,
        ),
    ]
    if include_offline_oracle:
        specs.append(
            PaperAAlgorithmSpec(
                "offline_legacy_rg_alns",
                "Offline-Legacy-ALNS",
                "legacy_rg_alns",
                "offline_oracle",
                False,
            )
        )
    return specs


def _available_paper_a_algorithm_specs() -> list[PaperAAlgorithmSpec]:
    """Return all known Paper A specs, including optional online metaheuristics."""

    specs = default_paper_a_algorithm_specs(include_offline_oracle=True)
    specs.extend([
        PaperAAlgorithmSpec("online_ils", "Online-ILS", "ils_fast", "main_online", True),
        PaperAAlgorithmSpec("online_vns", "Online-VNS", "vns_fast", "main_online", True),
        PaperAAlgorithmSpec("online_ts", "Online-TS", "ts_fast", "main_online", True),
        PaperAAlgorithmSpec("online_sa", "Online-SA", "sa_fast", "main_online", True),
        PaperAAlgorithmSpec("online_ga", "Online-GA", "ga_fast", "main_online", True),
    ])
    return specs


class CurrentTimeCommitWrapper:
    """Wrap an algorithm and enforce Paper A current-time commit policy."""

    def __init__(self, inner: SchedulingAlgorithm, *, label: str = ""):
        self.inner = inner
        self.label = label
        self.call_count = 0
        self.call_times: list[int] = []
        self.decision_times: list[int] = []
        self.observed_problem_types: set[str] = set()

    @property
    def number_of_events(self) -> int:
        return len(set(self.call_times))

    @property
    def number_of_decision_events(self) -> int:
        return len(set(self.decision_times))

    def __call__(
        self,
        problem: SchedulingProblem,
        state: ScheduleState,
    ) -> list[Decision]:
        self.call_count += 1
        self.call_times.append(state.current_time)
        self.observed_problem_types.add(type(problem).__name__)
        decisions = list(self.inner(problem, state))
        validated = validate_current_decisions(decisions, problem, state)
        if validated:
            self.decision_times.append(state.current_time)
        return validated


def validate_current_decisions(
    decisions: Iterable[Decision],
    problem: SchedulingProblem,
    state: ScheduleState,
    t: int | None = None,
) -> list[Decision]:
    """Validate that all decisions are executable at the current event time."""

    current_time = state.current_time if t is None else t
    validated: list[Decision] = []
    assigned_ops: set[tuple[int, int]] = set()
    assigned_machines: set[int] = set()

    for decision in decisions:
        job_id, op_id, machine_id, start_time = decision
        if start_time != current_time:
            raise DecisionValidationError(
                f"Decision {decision} must start at current time {current_time}"
            )
        try:
            job = problem.get_job(job_id)
        except KeyError as exc:
            raise DecisionValidationError(
                f"Decision {decision} schedules a job that is not visible"
            ) from exc

        op_key = (job_id, op_id)
        if op_key in assigned_ops:
            raise DecisionValidationError(f"Duplicate operation decision: {decision}")
        if machine_id in assigned_machines:
            raise DecisionValidationError(f"Duplicate machine decision: {decision}")
        if job.release_time > current_time:
            raise DecisionValidationError(f"Decision {decision} schedules an unreleased job")
        if state.is_job_completed(job_id):
            raise DecisionValidationError(f"Decision {decision} schedules a completed job")
        if state.is_operation_completed(job_id, op_id):
            raise DecisionValidationError(f"Decision {decision} schedules a completed operation")
        if state.is_operation_ongoing(job_id, op_id):
            raise DecisionValidationError(f"Decision {decision} schedules an ongoing operation")
        if not state.is_machine_idle(machine_id):
            raise DecisionValidationError(f"Decision {decision} schedules a busy machine")

        next_idx = state.next_op_index_for_job(job_id)
        if next_idx >= job.num_operations:
            raise DecisionValidationError(f"Decision {decision} has no next operation")
        op = job.operation_at(next_idx)
        if op.op_id != op_id:
            raise DecisionValidationError(
                f"Decision {decision} is not the next operation for job {job_id}"
            )
        for prev_idx in range(next_idx):
            prev_op = job.operation_at(prev_idx)
            if not state.is_operation_completed(job_id, prev_op.op_id):
                raise DecisionValidationError(
                    f"Decision {decision} has incomplete predecessors"
                )
        try:
            op.processing_time_on(machine_id)
        except KeyError as exc:
            raise DecisionValidationError(
                f"Decision {decision} uses an ineligible machine"
            ) from exc

        assigned_ops.add(op_key)
        assigned_machines.add(machine_id)
        validated.append(decision)
    return validated


def extract_current_feasible_decisions(
    local_plan: Iterable[ScheduledOperation | Decision],
    problem: SchedulingProblem,
    state: ScheduleState,
    t: int | None = None,
) -> list[Decision]:
    """Extract valid current-time decisions from a local/rolling plan."""

    current_time = state.current_time if t is None else t
    extracted: list[Decision] = []
    for item in local_plan:
        if isinstance(item, ScheduledOperation):
            decision = (item.job_id, item.op_id, item.machine_id, item.start_time)
        else:
            decision = item
        if decision[3] != current_time:
            continue
        try:
            validate_current_decisions(extracted + [decision], problem, state, current_time)
        except DecisionValidationError:
            continue
        extracted.append(decision)
    return extracted


def compute_objective_calibration(
    instance: SLISPInstance,
    *,
    alpha_0: float,
    beta_0: float,
) -> ObjectiveCalibration:
    """Compute instance-level scales for normalized Paper A evaluation."""

    theta = 0.0
    for job in instance.jobs:
        entity = instance.get_entity(job.entity_id)
        effective_deadline = entity.deadline - entity.transport_delay
        theta += max(1.0, float(effective_deadline - job.release_time))

    omega = 0.0
    for entity in instance.entities:
        # Keep the current project convention: min_fulfillment is deterministic
        # and equals max(1.0, rho_r * Q_r), without introducing a new rounding rule.
        omega += float(entity.weight) * float(entity.min_fulfillment)

    theta = max(theta, 1.0)
    omega = max(omega, 1.0)
    return ObjectiveCalibration(
        Theta_I=theta,
        Omega_I=omega,
        alpha_0=float(alpha_0),
        beta_0=float(beta_0),
        alpha_I=float(alpha_0) / theta,
        beta_I=float(beta_0) / omega,
    )


def evaluate_normalized_objective(
    objective: ObjectiveResult,
    calibration: ObjectiveCalibration,
) -> dict[str, float]:
    """Evaluate TT_hat, WSF_hat, and normalized_Z for one final schedule."""

    tt_hat = objective.total_tardiness / calibration.Theta_I
    wsf_hat = objective.weighted_service_shortfall / calibration.Omega_I
    normalized_z = calibration.alpha_0 * tt_hat + calibration.beta_0 * wsf_hat
    return {
        "TT_hat": tt_hat,
        "WSF_hat": wsf_hat,
        "normalized_Z": normalized_z,
    }


def create_paper_a_algorithm(
    spec: PaperAAlgorithmSpec,
    *,
    seed: int,
    algorithm_config: dict[str, Any] | None = None,
) -> SchedulingAlgorithm:
    """Create one Paper A algorithm from its explicit spec."""

    cfg = algorithm_config or {}
    if spec.key == "edd":
        return edd_rule
    if spec.key == "spt":
        return spt_rule
    if spec.key == "wspt":
        return wspt_rule
    if spec.key == "atc":
        return atc_rule
    if spec.key == "swd":
        return swd_rule
    if spec.key == "sfg":
        return sfg_rule
    if spec.key == "lightweight_rg_dispatch":
        return run_lightweight_rg_dispatch(**_rg_ralns_kwargs(cfg, seed))
    if spec.key == "rg_ralns":
        return run_rg_ralns(**_rg_ralns_kwargs(cfg, seed))
    if spec.key in {"online_legacy_rg_alns", "offline_legacy_rg_alns"}:
        legacy_cfg = cfg.get("legacy_rg_alns", {})
        return run_rg_alns(
            horizon=legacy_cfg.get("horizon", 120),
            lns_iterations=legacy_cfg.get("lns_iterations", 5),
            seed=seed,
        )
    if spec.key == "online_ils":
        return run_ils_fast(**_meta_kwargs(cfg, "ils_fast", seed))
    if spec.key == "online_vns":
        return run_vns_fast(**_meta_kwargs(cfg, "vns_fast", seed))
    if spec.key == "online_ts":
        ts_cfg = _meta_kwargs(cfg, "ts_fast", seed)
        ts_cfg["tabu_tenure"] = cfg.get("ts_fast", {}).get("tabu_tenure", 7)
        return run_ts_fast(**ts_cfg)
    if spec.key == "online_sa":
        return run_sa_fast(**_meta_kwargs(cfg, "sa_fast", seed))
    if spec.key == "online_ga":
        return run_ga_fast(**_meta_kwargs(cfg, "ga_fast", seed))
    raise ValueError(f"Unknown Paper A algorithm key: {spec.key}")


def load_paper_a_config(config_path: str | Path) -> dict[str, Any]:
    """Load and validate a Paper A online benchmark config."""

    path = Path(config_path)
    with path.open("r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    if config.get("experiment_protocol") != "paper_a_online":
        raise ValueError("experiment_protocol must be 'paper_a_online'")
    for key in ("online_visibility", "current_time_commit_only", "hide_future_job_details"):
        if config.get(key) is not True:
            raise ValueError(f"{key} must be true for Paper A online benchmark")
    return config


def run_paper_a_online_benchmark(
    *,
    config_path: str | Path,
    seeds: list[int],
    output_dir: str | Path,
    config_overrides: dict[str, Any] | None = None,
    beta_sensitivity: list[float] | None = None,
    rg_debug_trace: bool = False,
) -> dict[str, Any]:
    """Run the Paper A online benchmark and write CSV/YAML outputs."""

    config_path = Path(config_path)
    output_dir = Path(output_dir)
    config = load_paper_a_config(config_path)
    if config_overrides:
        config = _apply_config_overrides(config, config_overrides)
    objective_cfg = _objective_config(config)
    if beta_sensitivity is not None:
        objective_cfg["beta_sensitivity"] = [float(value) for value in beta_sensitivity]
    config["objective"] = objective_cfg
    if rg_debug_trace:
        rg_cfg = dict(config.get("rg_ralns", {}))
        rg_cfg["debug_trace"] = True
        config["rg_ralns"] = rg_cfg
    output_dir.mkdir(parents=True, exist_ok=True)

    specs = _select_algorithm_specs(config)
    per_instance_rows: list[dict[str, Any]] = []
    mechanism_rows: list[dict[str, Any]] = []
    trigger_rows: list[dict[str, Any]] = []
    calibration_rows: list[dict[str, Any]] = []
    event_trace_rows: list[dict[str, Any]] = []
    operator_rows: list[dict[str, Any]] = []
    fallback_rows: list[dict[str, Any]] = []
    rescue_failure_rows: list[dict[str, Any]] = []
    rescue_machine_contention_rows: list[dict[str, Any]] = []

    for instance_key, instance_cfg in config.get("instances", {}).items():
        num_instances = int(instance_cfg.get("num_instances", 1))
        for instance_index in range(num_instances):
            for seed in seeds:
                instance = _build_instance(instance_key, instance_cfg, seed, instance_index)
                calibration = compute_objective_calibration(
                    instance,
                    alpha_0=objective_cfg["alpha_0"],
                    beta_0=objective_cfg["beta_0"],
                )
                calibration_rows.append(_calibration_row(
                    instance_key,
                    instance_index,
                    seed,
                    calibration,
                ))
                for spec in specs:
                    (
                        row,
                        mechanism,
                        trigger_counts,
                        event_trace,
                        operator_stats,
                        fallback_stats,
                        rescue_failure,
                        rescue_machine_contention,
                    ) = _run_one_algorithm(
                        instance=instance,
                        instance_key=instance_key,
                        instance_index=instance_index,
                        seed=seed,
                        spec=spec,
                        config=config,
                        calibration=calibration,
                    )
                    per_instance_rows.append(row)
                    mechanism_rows.append(mechanism)
                    trigger_rows.extend(trigger_counts)
                    event_trace_rows.extend(event_trace)
                    operator_rows.extend(operator_stats)
                    fallback_rows.extend(fallback_stats)
                    rescue_failure_rows.extend(rescue_failure)
                    rescue_machine_contention_rows.extend(rescue_machine_contention)

    summary_rows = _summarize_results(per_instance_rows)
    sensitivity_rows = _summarize_beta_sensitivity(
        per_instance_rows,
        beta_values=objective_cfg["beta_sensitivity"],
        alpha_0=objective_cfg["alpha_0"],
    )

    outputs = {
        "results_summary_csv": str(output_dir / "results_summary.csv"),
        "per_instance_results_csv": str(output_dir / "per_instance_results.csv"),
        "mechanism_stats_csv": str(output_dir / "mechanism_stats.csv"),
        "trigger_reason_counts_csv": str(output_dir / "trigger_reason_counts.csv"),
        "objective_calibration_csv": str(output_dir / "objective_calibration.csv"),
        "beta_sensitivity_summary_csv": str(output_dir / "beta_sensitivity_summary.csv"),
        "rg_ralns_event_trace_seed2_csv": str(output_dir / "rg_ralns_event_trace_seed2.csv"),
        "operator_stats_csv": str(output_dir / "operator_stats.csv"),
        "fallback_stats_csv": str(output_dir / "fallback_stats.csv"),
        "rescue_failure_summary_csv": str(output_dir / "rescue_failure_summary.csv"),
        "rescue_machine_contention_trace_csv": str(output_dir / "rescue_machine_contention_trace.csv"),
        "tuning_comparison_csv": str(output_dir / "tuning_comparison.csv"),
        "config_used_yaml": str(output_dir / "config_used.yaml"),
    }
    _write_csv(Path(outputs["per_instance_results_csv"]), per_instance_rows)
    _write_csv(Path(outputs["mechanism_stats_csv"]), mechanism_rows)
    _write_csv(Path(outputs["trigger_reason_counts_csv"]), trigger_rows)
    _write_csv(Path(outputs["objective_calibration_csv"]), calibration_rows)
    _write_csv(Path(outputs["beta_sensitivity_summary_csv"]), sensitivity_rows)
    _write_csv(Path(outputs["rg_ralns_event_trace_seed2_csv"]), event_trace_rows)
    _write_csv(Path(outputs["operator_stats_csv"]), operator_rows)
    _write_csv(Path(outputs["fallback_stats_csv"]), fallback_rows)
    _write_csv(Path(outputs["rescue_failure_summary_csv"]), rescue_failure_rows)
    _write_csv(Path(outputs["rescue_machine_contention_trace_csv"]), rescue_machine_contention_rows)
    _write_csv(
        Path(outputs["tuning_comparison_csv"]),
        _tuning_comparison_rows(summary_rows, mechanism_rows, beta_0=objective_cfg["beta_0"]),
    )
    _write_csv(Path(outputs["results_summary_csv"]), summary_rows)
    with Path(outputs["config_used_yaml"]).open("w", encoding="utf-8") as fh:
        yaml.safe_dump(config, fh, sort_keys=False)

    return {
        "outputs": outputs,
        "per_instance_rows": len(per_instance_rows),
        "summary_rows": len(summary_rows),
        "sensitivity_rows": len(sensitivity_rows),
    }


def _objective_config(config: dict[str, Any]) -> dict[str, Any]:
    cfg = dict(config.get("objective", {}))
    objective_type = cfg.get("type", "normalized")
    if objective_type != "normalized":
        raise ValueError("Paper A objective.type must be 'normalized'")
    alpha_0 = float(cfg.get("alpha_0", 1.0))
    beta_0 = float(cfg.get("beta_0", 20.0))
    if alpha_0 < 0 or beta_0 < 0:
        raise ValueError("alpha_0 and beta_0 must be non-negative")
    beta_sensitivity = [float(value) for value in cfg.get(
        "beta_sensitivity",
        [1, 5, 10, 20, 50, 100],
    )]
    if any(value < 0 for value in beta_sensitivity):
        raise ValueError("beta_sensitivity values must be non-negative")
    return {
        "type": "normalized",
        "alpha_0": alpha_0,
        "beta_0": beta_0,
        "beta_sensitivity": beta_sensitivity,
    }


def _calibration_row(
    instance_key: str,
    instance_index: int,
    seed: int,
    calibration: ObjectiveCalibration,
) -> dict[str, Any]:
    return {
        "experiment_protocol": "paper_a_online",
        "instance_id": f"{instance_key}:{instance_index}:seed{seed}",
        "instance": instance_key,
        "instance_index": instance_index,
        "seed": seed,
        "Theta_I": calibration.Theta_I,
        "Omega_I": calibration.Omega_I,
        "alpha_0": calibration.alpha_0,
        "beta_0": calibration.beta_0,
        "alpha_I": calibration.alpha_I,
        "beta_I": calibration.beta_I,
        "q_min_rule": "max(1.0, rho_r * Q_r)",
    }


def _apply_config_overrides(
    config: dict[str, Any],
    overrides: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(config)
    for section, values in overrides.items():
        if not isinstance(values, dict):
            merged[section] = values
            continue
        current = dict(merged.get(section, {}))
        current.update(values)
        merged[section] = current
    return merged


def _run_one_algorithm(
    *,
    instance: SLISPInstance,
    instance_key: str,
    instance_index: int,
    seed: int,
    spec: PaperAAlgorithmSpec,
    config: dict[str, Any],
    calibration: ObjectiveCalibration,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    algorithm = create_paper_a_algorithm(spec, seed=seed, algorithm_config=config)
    wrapped = CurrentTimeCommitWrapper(algorithm, label=spec.label)
    start = time.perf_counter()
    status = "OK"
    error_type = ""
    error_message = ""
    obj = None

    try:
        _state, obj = run_simulation(
            instance,
            wrapped,
            online_visibility=spec.online_visibility,
        )
    except Exception as exc:
        status = "FAILED"
        error_type = exc.__class__.__name__
        error_message = str(exc)
    runtime = time.perf_counter() - start

    base = {
        "experiment_protocol": "paper_a_online",
        "instance": instance_key,
        "instance_index": instance_index,
        "seed": seed,
        "algorithm": spec.key,
        "algorithm_label": spec.label,
        "table_group": spec.table_group,
        "online_visibility": spec.online_visibility,
        "objective_scope": "global_final",
        "status": status,
        "runtime": round(runtime, 6),
    }
    normalized = evaluate_normalized_objective(obj, calibration) if obj is not None else {}
    row = {
        **base,
        "objective_type": "normalized",
        "Z_original": "" if obj is None else obj.Z,
        "Z_N": normalized.get("normalized_Z", ""),
        "normalized_Z": normalized.get("normalized_Z", ""),
        "TT": "" if obj is None else obj.total_tardiness,
        "WSF": "" if obj is None else obj.weighted_service_shortfall,
        "TT_hat": normalized.get("TT_hat", ""),
        "WSF_hat": normalized.get("WSF_hat", ""),
        "ZSR": "" if obj is None else obj.zero_shortfall_entity_rate,
        "zero_shortfall_entity_rate": "" if obj is None else obj.zero_shortfall_entity_rate,
        "Theta_I": calibration.Theta_I,
        "Omega_I": calibration.Omega_I,
        "alpha_0": calibration.alpha_0,
        "beta_0": calibration.beta_0,
        "alpha_I": calibration.alpha_I,
        "beta_I": calibration.beta_I,
        "error_type": error_type,
        "error_message": error_message,
    }

    trigger_count = _attr(wrapped.inner, "trigger_count", 0)
    number_of_events = wrapped.number_of_events
    algorithm_call_count = wrapped.call_count
    mechanism = {
        **base,
        "trigger_count": trigger_count,
        "trigger_ratio": trigger_count / max(1, algorithm_call_count),
        "avg_A_size": _attr(wrapped.inner, "avg_A_size", 0.0),
        "max_A_size": _attr(wrapped.inner, "max_A_size", 0),
        "alns_runtime_total": _attr(wrapped.inner, "alns_runtime_total", 0.0),
        "dispatch_fallback_count": _attr(wrapped.inner, "dispatch_fallback_count", 0),
        "local_extraction_success_count": _attr(wrapped.inner, "local_extraction_success_count", 0),
        "affected_set_rescue_success_count": _attr(wrapped.inner, "affected_set_rescue_success_count", 0),
        "rescue_fallback_count": _attr(wrapped.inner, "rescue_fallback_count", 0),
        "ordinary_fallback_count": _attr(wrapped.inner, "ordinary_fallback_count", 0),
        "rescue_fallback_success_count": _attr(wrapped.inner, "rescue_fallback_success_count", 0),
        "rescue_machine_contention_events": _attr(wrapped.inner, "rescue_machine_contention_events", 0),
        "rescue_machine_reservation_skip_count": _attr(wrapped.inner, "rescue_machine_reservation_skip_count", 0),
        "mandatory_precursor_in_A_count": _attr(wrapped.inner, "mandatory_precursor_in_A_count", 0),
        "cover_precursor_in_A_count": _attr(wrapped.inner, "cover_precursor_in_A_count", 0),
        "mandatory_precursor_selected_count": _attr(wrapped.inner, "mandatory_precursor_selected_count", 0),
        "cover_precursor_selected_count": _attr(wrapped.inner, "cover_precursor_selected_count", 0),
        "algorithm_call_count": algorithm_call_count,
        "number_of_events": number_of_events,
        "number_of_decision_events": wrapped.number_of_decision_events,
    }
    trigger_rows = [
        {**base, "trigger_reason": reason, "count": count}
        for reason, count in dict(_attr(wrapped.inner, "trigger_reason_counts", {})).items()
    ]
    event_trace_rows = [
        {**base, **trace_row}
        for trace_row in list(_attr(wrapped.inner, "event_trace_rows", []))
    ]
    operator_rows = [
        {**base, **operator_row}
        for operator_row in list(_attr(wrapped.inner, "operator_stats_rows", []))
    ]
    fallback_rows = [
        {**base, "fallback_reason": reason, "count": count}
        for reason, count in dict(_attr(wrapped.inner, "fallback_failure_reason_counts", {})).items()
    ]
    fallback_rows.append({
        **base,
        "fallback_reason": "summary",
        "dispatch_fallback_count": _attr(wrapped.inner, "dispatch_fallback_count", 0),
        "local_extraction_success_count": _attr(wrapped.inner, "local_extraction_success_count", 0),
        "affected_set_rescue_success_count": _attr(wrapped.inner, "affected_set_rescue_success_count", 0),
        "rescue_fallback_count": _attr(wrapped.inner, "rescue_fallback_count", 0),
        "ordinary_fallback_count": _attr(wrapped.inner, "ordinary_fallback_count", 0),
        "rescue_fallback_success_count": _attr(wrapped.inner, "rescue_fallback_success_count", 0),
        "rescue_machine_contention_events": _attr(wrapped.inner, "rescue_machine_contention_events", 0),
        "rescue_machine_reservation_skip_count": _attr(wrapped.inner, "rescue_machine_reservation_skip_count", 0),
        "mandatory_precursor_in_A_count": _attr(wrapped.inner, "mandatory_precursor_in_A_count", 0),
        "cover_precursor_in_A_count": _attr(wrapped.inner, "cover_precursor_in_A_count", 0),
        "mandatory_precursor_selected_count": _attr(wrapped.inner, "mandatory_precursor_selected_count", 0),
        "cover_precursor_selected_count": _attr(wrapped.inner, "cover_precursor_selected_count", 0),
    })
    rescue_failure_rows = [{
        **base,
        "final_WSF": "" if obj is None else obj.weighted_service_shortfall,
        "final_ZSR": "" if obj is None else obj.zero_shortfall_entity_rate,
        "no_ready_operation_available_count": dict(_attr(wrapped.inner, "fallback_failure_reason_counts", {})).get(
            "no_ready_operation_available",
            0,
        ),
        "ordinary_fallback_count": _attr(wrapped.inner, "ordinary_fallback_count", 0),
        "rescue_fallback_success_count": _attr(wrapped.inner, "rescue_fallback_success_count", 0),
        "affected_set_rescue_success_count": _attr(wrapped.inner, "affected_set_rescue_success_count", 0),
        "rescue_machine_contention_events": _attr(wrapped.inner, "rescue_machine_contention_events", 0),
        "mandatory_precursor_in_A_count": _attr(wrapped.inner, "mandatory_precursor_in_A_count", 0),
        "cover_precursor_in_A_count": _attr(wrapped.inner, "cover_precursor_in_A_count", 0),
        "mandatory_precursor_selected_count": _attr(wrapped.inner, "mandatory_precursor_selected_count", 0),
        "cover_precursor_selected_count": _attr(wrapped.inner, "cover_precursor_selected_count", 0),
        "failed_entity": "",
        "final_shortfall": "" if obj is None else obj.weighted_service_shortfall,
    }]
    rescue_machine_contention_rows = [
        {**base, **trace_row}
        for trace_row in list(_attr(wrapped.inner, "rescue_machine_contention_rows", []))
    ]
    return (
        row,
        mechanism,
        trigger_rows,
        event_trace_rows,
        operator_rows,
        fallback_rows,
        rescue_failure_rows,
        rescue_machine_contention_rows,
    )


def _select_algorithm_specs(config: dict[str, Any]) -> list[PaperAAlgorithmSpec]:
    defaults = {
        spec.key: spec
        for spec in _available_paper_a_algorithm_specs()
    }
    algorithms_cfg = config.get("algorithms", {})
    main_keys = list(algorithms_cfg.get("main_online", [
        "edd",
        "spt",
        "wspt",
        "atc",
        "swd",
        "sfg",
        "lightweight_rg_dispatch",
        "online_legacy_rg_alns",
        "rg_ralns",
    ]))
    offline_keys = list(algorithms_cfg.get("offline_oracle", []))
    selected: list[PaperAAlgorithmSpec] = []
    for key in main_keys:
        spec = defaults.get(key)
        if spec is None:
            raise ValueError(f"Unknown main online algorithm: {key}")
        if spec.table_group != "main_online" or not spec.online_visibility:
            raise ValueError(f"{key} is not allowed in the main online table")
        selected.append(spec)
    for key in offline_keys:
        spec = defaults.get(key)
        if spec is None:
            raise ValueError(f"Unknown offline/oracle algorithm: {key}")
        if spec.table_group != "offline_oracle" or spec.online_visibility:
            raise ValueError(f"{key} is not an offline/oracle algorithm")
        selected.append(spec)
    return selected


def _build_instance(
    instance_key: str,
    cfg: dict[str, Any],
    seed: int,
    instance_index: int,
) -> SLISPInstance:
    instance_config = InstanceConfig(
        group_name=cfg.get("group_name", instance_key),
        num_instances=1,
        num_jobs=cfg["num_jobs"],
        num_machines=cfg["num_machines"],
        num_entities=cfg["num_entities"],
        ops_per_job=tuple(cfg.get("ops_per_job", [2, 4])),
        rho_range=tuple(cfg.get("rho_range", [0.7, 0.8])),
        deadline_tightness=cfg.get("deadline_tightness", 1.0),
        weight_pattern=cfg.get("weight_pattern", "mild"),
        quantity_range=tuple(cfg.get("quantity_range", [1, 10])),
        proc_time_range=tuple(cfg.get("proc_time_range", [1, 100])),
        transport_delay_range=tuple(cfg.get("transport_delay_range", [0, 50])),
        eligible_machines_range=tuple(cfg.get("eligible_machines_range", [2, 4])),
        alpha=cfg.get("alpha", 1.0),
        beta=cfg.get("beta", 1.0),
        effective_due_spread=cfg.get("effective_due_spread", 0.0),
        effective_due_multipliers=(
            tuple(cfg["effective_due_multipliers"])
            if cfg.get("effective_due_multipliers") is not None
            else None
        ),
        release_time_mode=cfg.get("release_time_mode", "static"),
        arrival_intensity=cfg.get("arrival_intensity", "static"),
    )
    instance_seed = seed + instance_index * 10007
    base = generate_instance(instance_config, instance_seed, instance_index=0)
    return build_dynamic_scenario(
        base,
        arrival_intensity=cfg.get("arrival_intensity", "static"),
        seed=instance_seed + 1,
    )


def _rg_ralns_kwargs(config: dict[str, Any], seed: int) -> dict[str, Any]:
    cfg = config.get("rg_ralns", {})
    return {
        "H_A": cfg.get("H_A", 8),
        "N_A": cfg.get("N_A", 8),
        "regret_k": cfg.get("regret_k", 2),
        "eps": cfg.get("eps", 1e-9),
        "random_seed": cfg.get("random_seed", seed),
        "destroy_fraction": cfg.get("destroy_fraction", 0.35),
        "acceptance_mode": cfg.get("acceptance_mode", "service_safe_z"),
        "bottleneck_trigger_mode": cfg.get("bottleneck_trigger_mode", "strict"),
        "rescue_fallback_enabled": cfg.get("rescue_fallback_enabled", True),
        "protect_zero_wsf": cfg.get("protect_zero_wsf", True),
        "adaptive_destroy_size": cfg.get("adaptive_destroy_size", True),
        "destroy_fraction_low": cfg.get("destroy_fraction_low", 0.25),
        "destroy_fraction_mid": cfg.get("destroy_fraction_mid", 0.35),
        "destroy_fraction_high": cfg.get("destroy_fraction_high", 0.50),
        "tt_polish_max_moves": cfg.get("tt_polish_max_moves", 0),
        "recoverability_slack_margin": cfg.get("recoverability_slack_margin", 0.0),
        "early_rescue_trigger": cfg.get("early_rescue_trigger", False),
        "capacity_rescue_enabled": cfg.get("capacity_rescue_enabled", False),
        "rescue_reservation_window": cfg.get("rescue_reservation_window", 1),
        "rescue_machine_pressure_threshold": cfg.get("rescue_machine_pressure_threshold", 1),
        "low_risk_on_rescue_machine_penalty": cfg.get("low_risk_on_rescue_machine_penalty", True),
        "debug_trace": cfg.get("debug_trace", False),
    }


def _meta_kwargs(config: dict[str, Any], key: str, seed: int) -> dict[str, Any]:
    cfg = config.get(key, {})
    return {
        "horizon": cfg.get("horizon", 120),
        "max_iter": cfg.get("max_iter", 10),
        "seed": seed,
    }


def _attr(obj: Any, name: str, default: Any) -> Any:
    return getattr(obj, name, default)


def _summarize_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(
            (row["algorithm"], row["algorithm_label"], row["table_group"]),
            [],
        ).append(row)

    summary: list[dict[str, Any]] = []
    for (algorithm, label, group), group_rows in sorted(groups.items()):
        ok_rows = [row for row in group_rows if row["status"] == "OK"]
        summary.append({
            "algorithm": algorithm,
            "algorithm_label": label,
            "table_group": group,
            "runs": len(group_rows),
            "ok_runs": len(ok_rows),
            "mean_Z_N": _mean(ok_rows, "Z_N"),
            "mean_normalized_Z": _mean(ok_rows, "normalized_Z"),
            "mean_Z_original": _mean(ok_rows, "Z_original"),
            "mean_TT": _mean(ok_rows, "TT"),
            "mean_WSF": _mean(ok_rows, "WSF"),
            "mean_TT_hat": _mean(ok_rows, "TT_hat"),
            "mean_WSF_hat": _mean(ok_rows, "WSF_hat"),
            "mean_ZSR": _mean(ok_rows, "ZSR"),
            "mean_zero_shortfall_entity_rate": _mean(ok_rows, "zero_shortfall_entity_rate"),
            "mean_runtime": _mean(ok_rows, "runtime"),
        })
    return summary


def _tuning_comparison_rows(
    summary_rows: list[dict[str, Any]],
    mechanism_rows: list[dict[str, Any]],
    *,
    beta_0: float,
) -> list[dict[str, Any]]:
    mechanism_by_algorithm: dict[str, list[dict[str, Any]]] = {}
    for row in mechanism_rows:
        mechanism_by_algorithm.setdefault(row["algorithm"], []).append(row)

    rows: list[dict[str, Any]] = []
    for row in summary_rows:
        mech = mechanism_by_algorithm.get(row["algorithm"], [])
        rows.append({
            "config_name": "paper_a_rg_ralns_tuned",
            "beta_0": beta_0,
            "algorithm": row["algorithm"],
            "algorithm_label": row["algorithm_label"],
            "mean_Z_N": row["mean_Z_N"],
            "mean_TT": row["mean_TT"],
            "mean_WSF": row["mean_WSF"],
            "mean_ZSR": row["mean_ZSR"],
            "mean_runtime": row["mean_runtime"],
            "mean_trigger_ratio": _mean(mech, "trigger_ratio"),
            "mean_avg_A_size": _mean(mech, "avg_A_size"),
            "mean_dispatch_fallback_count": _mean(mech, "dispatch_fallback_count"),
            "mean_local_extraction_success_count": _mean(mech, "local_extraction_success_count"),
            "mean_affected_set_rescue_success_count": _mean(mech, "affected_set_rescue_success_count"),
            "mean_rescue_fallback_success_count": _mean(mech, "rescue_fallback_success_count"),
        })
    return rows


def _summarize_beta_sensitivity(
    rows: list[dict[str, Any]],
    *,
    beta_values: list[float],
    alpha_0: float,
) -> list[dict[str, Any]]:
    summary_rows: list[dict[str, Any]] = []
    for beta_0 in beta_values:
        groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for row in rows:
            groups.setdefault(
                (row["algorithm"], row["algorithm_label"], row["table_group"]),
                [],
            ).append(row)

        beta_rows: list[dict[str, Any]] = []
        for (algorithm, label, group), group_rows in sorted(groups.items()):
            ok_rows = [row for row in group_rows if row["status"] == "OK"]
            mean_tt_hat = _mean(ok_rows, "TT_hat")
            mean_wsf_hat = _mean(ok_rows, "WSF_hat")
            if mean_tt_hat == "" or mean_wsf_hat == "":
                mean_z_n: float | str = ""
            else:
                mean_z_n = alpha_0 * float(mean_tt_hat) + beta_0 * float(mean_wsf_hat)
            beta_rows.append({
                "beta_0": beta_0,
                "algorithm": algorithm,
                "algorithm_label": label,
                "table_group": group,
                "runs": len(group_rows),
                "ok_runs": len(ok_rows),
                "mean_Z_N": mean_z_n,
                "mean_TT": _mean(ok_rows, "TT"),
                "mean_WSF": _mean(ok_rows, "WSF"),
                "mean_TT_hat": mean_tt_hat,
                "mean_WSF_hat": mean_wsf_hat,
                "mean_ZSR": _mean(ok_rows, "ZSR"),
                "mean_runtime": _mean(ok_rows, "runtime"),
            })

        ranked = sorted(
            [row for row in beta_rows if row["mean_Z_N"] != ""],
            key=lambda row: (float(row["mean_Z_N"]), row["algorithm"]),
        )
        for rank, row in enumerate(ranked, start=1):
            row["rank_by_Z_N"] = rank
        _add_rg_gap_columns(beta_rows)
        summary_rows.extend(beta_rows)
    return summary_rows


def _add_rg_gap_columns(rows: list[dict[str, Any]]) -> None:
    values = {row["algorithm"]: row for row in rows if row["mean_Z_N"] != ""}
    rg = values.get("rg_ralns")
    targets = {
        "edd": "vs_EDD_gap_percent",
        "lightweight_rg_dispatch": "vs_Lightweight_RG_gap_percent",
        "online_legacy_rg_alns": "vs_Online_Legacy_ALNS_gap_percent",
    }
    for row in rows:
        for column in targets.values():
            row[column] = ""
    if rg is None:
        return
    rg_value = float(rg["mean_Z_N"])
    for target, column in targets.items():
        baseline = values.get(target)
        if baseline is None:
            continue
        baseline_value = float(baseline["mean_Z_N"])
        if abs(baseline_value) <= 1e-12:
            continue
        rg[column] = (rg_value - baseline_value) / baseline_value * 100.0


def _mean(rows: list[dict[str, Any]], key: str) -> float | str:
    values = [float(row[key]) for row in rows if row.get(key) != ""]
    if not values:
        return ""
    return sum(values) / len(values)


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


__all__ = [
    "CurrentTimeCommitWrapper",
    "DecisionValidationError",
    "PROTOCOL_STATEMENT",
    "ObjectiveCalibration",
    "PaperAAlgorithmSpec",
    "compute_objective_calibration",
    "create_paper_a_algorithm",
    "default_paper_a_algorithm_specs",
    "evaluate_normalized_objective",
    "extract_current_feasible_decisions",
    "load_paper_a_config",
    "run_paper_a_online_benchmark",
    "validate_current_decisions",
]
