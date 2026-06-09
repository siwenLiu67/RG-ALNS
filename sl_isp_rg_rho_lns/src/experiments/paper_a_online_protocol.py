"""Paper A online event-driven benchmark protocol.

This module keeps the Paper A benchmark protocol separate from legacy pilot
benchmark scripts.  Main-table algorithms run through the simulator's online
visibility mode and a shared current-time commit validator.
"""

from __future__ import annotations

import csv
import shutil
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
            "Online-Legacy-RG-ALNS",
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
                "Offline-Legacy-RG-ALNS",
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
) -> dict[str, Any]:
    """Run the Paper A online benchmark and write CSV/YAML outputs."""

    config_path = Path(config_path)
    output_dir = Path(output_dir)
    config = load_paper_a_config(config_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    specs = _select_algorithm_specs(config)
    per_instance_rows: list[dict[str, Any]] = []
    mechanism_rows: list[dict[str, Any]] = []
    trigger_rows: list[dict[str, Any]] = []

    for instance_key, instance_cfg in config.get("instances", {}).items():
        num_instances = int(instance_cfg.get("num_instances", 1))
        for instance_index in range(num_instances):
            for seed in seeds:
                instance = _build_instance(instance_key, instance_cfg, seed, instance_index)
                for spec in specs:
                    row, mechanism, trigger_counts = _run_one_algorithm(
                        instance=instance,
                        instance_key=instance_key,
                        instance_index=instance_index,
                        seed=seed,
                        spec=spec,
                        config=config,
                    )
                    per_instance_rows.append(row)
                    mechanism_rows.append(mechanism)
                    trigger_rows.extend(trigger_counts)

    summary_rows = _summarize_results(per_instance_rows)

    outputs = {
        "results_summary_csv": str(output_dir / "results_summary.csv"),
        "per_instance_results_csv": str(output_dir / "per_instance_results.csv"),
        "mechanism_stats_csv": str(output_dir / "mechanism_stats.csv"),
        "trigger_reason_counts_csv": str(output_dir / "trigger_reason_counts.csv"),
        "config_used_yaml": str(output_dir / "config_used.yaml"),
    }
    _write_csv(Path(outputs["per_instance_results_csv"]), per_instance_rows)
    _write_csv(Path(outputs["mechanism_stats_csv"]), mechanism_rows)
    _write_csv(Path(outputs["trigger_reason_counts_csv"]), trigger_rows)
    _write_csv(Path(outputs["results_summary_csv"]), summary_rows)
    shutil.copyfile(config_path, outputs["config_used_yaml"])

    return {
        "outputs": outputs,
        "per_instance_rows": len(per_instance_rows),
        "summary_rows": len(summary_rows),
    }


def _run_one_algorithm(
    *,
    instance: SLISPInstance,
    instance_key: str,
    instance_index: int,
    seed: int,
    spec: PaperAAlgorithmSpec,
    config: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
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
    row = {
        **base,
        "Z": "" if obj is None else obj.Z,
        "TT": "" if obj is None else obj.total_tardiness,
        "WSF": "" if obj is None else obj.weighted_service_shortfall,
        "zero_shortfall_entity_rate": "" if obj is None else obj.zero_shortfall_entity_rate,
        "error_type": error_type,
        "error_message": error_message,
    }

    trigger_count = _attr(wrapped.inner, "trigger_count", 0)
    number_of_events = wrapped.number_of_events
    mechanism = {
        **base,
        "trigger_count": trigger_count,
        "trigger_ratio": trigger_count / max(1, number_of_events),
        "avg_A_size": _attr(wrapped.inner, "avg_A_size", 0.0),
        "max_A_size": _attr(wrapped.inner, "max_A_size", 0),
        "alns_runtime_total": _attr(wrapped.inner, "alns_runtime_total", 0.0),
        "dispatch_fallback_count": _attr(wrapped.inner, "dispatch_fallback_count", 0),
        "number_of_events": number_of_events,
        "number_of_decision_events": wrapped.number_of_decision_events,
    }
    trigger_rows = [
        {**base, "trigger_reason": reason, "count": count}
        for reason, count in dict(_attr(wrapped.inner, "trigger_reason_counts", {})).items()
    ]
    return row, mechanism, trigger_rows


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
            "mean_Z": _mean(ok_rows, "Z"),
            "mean_TT": _mean(ok_rows, "TT"),
            "mean_WSF": _mean(ok_rows, "WSF"),
            "mean_zero_shortfall_entity_rate": _mean(ok_rows, "zero_shortfall_entity_rate"),
            "mean_runtime": _mean(ok_rows, "runtime"),
        })
    return summary


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
    "PaperAAlgorithmSpec",
    "create_paper_a_algorithm",
    "default_paper_a_algorithm_specs",
    "extract_current_feasible_decisions",
    "load_paper_a_config",
    "run_paper_a_online_benchmark",
    "validate_current_decisions",
]
