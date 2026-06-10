"""Recoverability-Guided Reactive ALNS (RG-RALNS).

This module implements the Paper A online main algorithm.  It expects the
simulator to pass an OnlineProblemView when the experiment is online; therefore
the job list seen here is exactly J_vis(t).  Future unreleased jobs are not
represented as Job objects in this interface and can only affect
recoverability diagnostics through entity_future_quantity.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Callable

from ..core.dataclasses import (
    Job,
    Machine,
    Operation,
    ScheduledOperation,
    ServiceEntity,
    SLISPInstance,
)
from ..core.online import OnlineProblemView
from ..core.schedule_state import ScheduleState

SchedulingProblem = SLISPInstance | OnlineProblemView


HIGH_RISK_CLASSES = {"at_risk", "arrival_dependent", "fragile"}


@dataclass(frozen=True)
class RGRALNSConfig:
    """Centralized parameters for RG-RALNS."""

    H_A: int = 12
    N_A: int = 30
    alpha: float | None = None
    beta: float | None = None
    regret_k: int = 2
    eps: float = 1e-9
    random_seed: int = 42
    destroy_fraction: float = 0.35
    enable_alns: bool = True
    acceptance_mode: str = "service_safe_z"
    bottleneck_trigger_mode: str = "strict"

    def __post_init__(self) -> None:
        if self.H_A <= 0:
            raise ValueError("H_A must be positive")
        if self.N_A < 0:
            raise ValueError("N_A must be non-negative")
        if self.regret_k <= 0:
            raise ValueError("regret_k must be positive")
        if self.eps <= 0:
            raise ValueError("eps must be positive")
        if not (0.0 < self.destroy_fraction <= 1.0):
            raise ValueError("destroy_fraction must be in (0, 1]")
        if self.acceptance_mode not in {"service_first", "service_safe_z"}:
            raise ValueError("acceptance_mode must be 'service_first' or 'service_safe_z'")
        if self.bottleneck_trigger_mode not in {"normal", "strict"}:
            raise ValueError("bottleneck_trigger_mode must be 'normal' or 'strict'")


@dataclass(frozen=True)
class ReadyOperation:
    """A currently executable operation-machine candidate."""

    job_id: int
    op_id: int
    machine_id: int
    processing_time: int


@dataclass
class EntityDiagnostics:
    """Recoverability diagnostics for one service entity."""

    entity_id: int
    q_sec: float
    q_rem: float
    q_rec: float
    q_future: float
    q_cover: float
    u_info: float
    mandatory_jobs: set[int] = field(default_factory=set)
    cover_jobs: list[int] = field(default_factory=list)
    recoverability_class: str = "stable"
    visible_recoverable_jobs: set[int] = field(default_factory=set)
    delivery_lb_by_job: dict[int, float] = field(default_factory=dict)
    remaining_work_by_job: dict[int, float] = field(default_factory=dict)


@dataclass
class RGRALNSDiagnostics:
    """All event-time diagnostics used by RG-RALNS."""

    by_entity: dict[int, EntityDiagnostics]
    mandatory_jobs: set[int]
    cover_jobs: set[int]
    high_risk_entities: set[int]
    newly_arrived_jobs: set[int]
    visible_job_ids: set[int]
    job_entity: dict[int, int]


@dataclass
class LocalSchedule:
    """Local schedule decoded from a job order over A(t)."""

    job_order: list[int]
    scheduled_operations: list[ScheduledOperation]
    completion_times: dict[int, int]


@dataclass(frozen=True)
class CandidateEvaluation:
    """Candidate comparison values for hierarchical acceptance."""

    z: float
    tt: float
    wsf: float
    risk_by_entity: dict[int, float]
    instability: float


DestroyOperator = Callable[
    [list[int], SchedulingProblem, ScheduleState, RGRALNSDiagnostics, list[ReadyOperation], int],
    tuple[list[int], list[int]],
]
RepairOperator = Callable[
    [list[int], list[int], SchedulingProblem, ScheduleState, RGRALNSDiagnostics],
    list[int],
]


def collect_ready_operations(
    problem: SchedulingProblem,
    state: ScheduleState,
) -> list[ReadyOperation]:
    """Build R(t) as operation-machine candidates on currently idle machines."""

    ready: list[ReadyOperation] = []
    idle_machines = {
        machine.machine_id
        for machine in problem.machines
        if state.is_machine_idle(machine.machine_id)
    }
    if not idle_machines:
        return ready

    for job in sorted(problem.jobs, key=lambda item: item.job_id):
        if state.is_job_completed(job.job_id):
            continue
        if job.release_time > state.current_time:
            continue
        if _job_has_ongoing_operation(job, state):
            continue
        next_idx = state.next_op_index_for_job(job.job_id)
        if next_idx >= job.num_operations:
            continue
        op = job.operation_at(next_idx)
        if state.is_operation_completed(job.job_id, op.op_id):
            continue
        if state.is_operation_ongoing(job.job_id, op.op_id):
            continue
        for machine_id in sorted(idle_machines):
            try:
                pt = op.processing_time_on(machine_id)
            except KeyError:
                continue
            ready.append(
                ReadyOperation(
                    job_id=job.job_id,
                    op_id=op.op_id,
                    machine_id=machine_id,
                    processing_time=pt,
                )
            )
    return ready


def compute_recoverability_diagnostics(
    problem: SchedulingProblem,
    state: ScheduleState,
    newly_arrived_job_ids: set[int] | None = None,
    *,
    eps: float = 1e-9,
) -> RGRALNSDiagnostics:
    """Compute the RG-RALNS recoverability diagnostics using J_vis(t) only."""

    newly_arrived = set(newly_arrived_job_ids or set())
    visible_job_ids = {job.job_id for job in problem.jobs}
    job_entity = {job.job_id: job.entity_id for job in problem.jobs}
    by_entity: dict[int, EntityDiagnostics] = {}

    for entity in sorted(problem.entities, key=lambda item: item.entity_id):
        q_sec = _secured_quantity(problem, state, entity)
        q_rem = max(0.0, float(entity.min_fulfillment) - q_sec)
        q_future = float(_future_quantity(problem, entity.entity_id))

        visible_recoverable: set[int] = set()
        delivery_lb_by_job: dict[int, float] = {}
        remaining_work_by_job: dict[int, float] = {}
        q_rec = 0.0

        for job in sorted(problem.jobs_of_entity(entity.entity_id), key=lambda item: item.job_id):
            if state.is_job_completed(job.job_id):
                continue
            remaining_work = _remaining_job_work(job, state)
            delivery_lb = max(state.current_time, job.release_time) + remaining_work + entity.transport_delay
            delivery_lb_by_job[job.job_id] = delivery_lb
            remaining_work_by_job[job.job_id] = remaining_work
            if delivery_lb <= entity.deadline + eps:
                visible_recoverable.add(job.job_id)
                q_rec += float(job.quantity)

        u_info = max(0.0, q_rem - q_rec - q_future)
        q_cover = max(0.0, q_rem - q_future)

        mandatory_jobs: set[int] = set()
        for job_id in sorted(visible_recoverable):
            job = _visible_job(problem, job_id)
            risk_without_job = max(0.0, q_rem - (q_rec - job.quantity) - q_future)
            if risk_without_job > eps:
                mandatory_jobs.add(job_id)

        provisional = EntityDiagnostics(
            entity_id=entity.entity_id,
            q_sec=q_sec,
            q_rem=q_rem,
            q_rec=q_rec,
            q_future=q_future,
            q_cover=q_cover,
            u_info=u_info,
            mandatory_jobs=mandatory_jobs,
            visible_recoverable_jobs=visible_recoverable,
            delivery_lb_by_job=delivery_lb_by_job,
            remaining_work_by_job=remaining_work_by_job,
        )
        provisional.cover_jobs = _heuristic_service_cover(problem, entity, provisional, eps)
        provisional.recoverability_class = _recoverability_class(problem, provisional, eps)
        by_entity[entity.entity_id] = provisional

    mandatory_all: set[int] = set()
    cover_all: set[int] = set()
    high_risk_entities: set[int] = set()
    for entity_id, diag in by_entity.items():
        mandatory_all.update(diag.mandatory_jobs)
        cover_all.update(diag.cover_jobs)
        if diag.recoverability_class in HIGH_RISK_CLASSES:
            high_risk_entities.add(entity_id)

    return RGRALNSDiagnostics(
        by_entity=by_entity,
        mandatory_jobs=mandatory_all,
        cover_jobs=cover_all,
        high_risk_entities=high_risk_entities,
        newly_arrived_jobs=newly_arrived.intersection(visible_job_ids),
        visible_job_ids=visible_job_ids,
        job_entity=job_entity,
    )


def _should_trigger_due_to_shortfall(diagnostics: RGRALNSDiagnostics) -> bool:
    return any(diag.u_info > 0.0 for diag in diagnostics.by_entity.values())


def _should_trigger_due_to_mandatory_ready(
    diagnostics: RGRALNSDiagnostics,
    ready_ops: list[ReadyOperation],
) -> bool:
    if not diagnostics.mandatory_jobs:
        return False
    return any(ready.job_id in diagnostics.mandatory_jobs for ready in ready_ops)


def _should_trigger_due_to_high_risk_arrival(
    diagnostics: RGRALNSDiagnostics,
) -> bool:
    for job_id in diagnostics.newly_arrived_jobs:
        entity_id = diagnostics.job_entity.get(job_id)
        if entity_id in diagnostics.high_risk_entities:
            return True
    return False


def _should_trigger_due_to_bottleneck_competition(
    problem: SchedulingProblem,
    state: ScheduleState,
    diagnostics: RGRALNSDiagnostics,
    ready_ops: list[ReadyOperation],
    mode: str = "strict",
) -> bool:
    del state
    by_machine: dict[int, list[ReadyOperation]] = {}
    for ready in ready_ops:
        by_machine.setdefault(ready.machine_id, []).append(ready)

    for machine_ready in by_machine.values():
        if mode == "normal":
            has_high_risk = any(
                diagnostics.job_entity.get(ready.job_id) in diagnostics.high_risk_entities
                for ready in machine_ready
            )
            has_low_risk = any(
                diagnostics.job_entity.get(ready.job_id) not in diagnostics.high_risk_entities
                for ready in machine_ready
            )
            if has_high_risk and has_low_risk:
                return True
            continue

        median_pt = _median_processing_time(machine_ready)
        has_high_risk = any(
            ready.job_id in diagnostics.mandatory_jobs
            or ready.job_id in diagnostics.cover_jobs
            for ready in machine_ready
        )
        has_low_risk = any(
            diagnostics.job_entity.get(ready.job_id) not in diagnostics.high_risk_entities
            and ready.processing_time >= median_pt
            for ready in machine_ready
        )
        if has_high_risk and has_low_risk:
            return True
    return False


def _should_trigger_due_to_cover_violation(
    problem: SchedulingProblem,
    state: ScheduleState,
    diagnostics: RGRALNSDiagnostics,
    ready_ops: list[ReadyOperation],
) -> bool:
    decisions = lightweight_rg_dispatch(problem, state, diagnostics, ready_ops)
    selected_jobs = {job_id for job_id, _op_id, _machine_id, _start in decisions}
    ready_jobs = {ready.job_id for ready in ready_ops}

    for diag in diagnostics.by_entity.values():
        if diag.recoverability_class == "secured":
            continue
        ready_cover_jobs = set(diag.cover_jobs).intersection(ready_jobs)
        if ready_cover_jobs and not selected_jobs.intersection(ready_cover_jobs):
            return True
    return False


def lightweight_rg_dispatch(
    problem: SchedulingProblem,
    state: ScheduleState,
    diagnostics: RGRALNSDiagnostics,
    ready_ops: list[ReadyOperation] | None = None,
) -> list[tuple[int, int, int, int]]:
    """Deterministic lightweight RG dispatch for non-triggered events."""

    ready = list(ready_ops if ready_ops is not None else collect_ready_operations(problem, state))
    decisions: list[tuple[int, int, int, int]] = []
    assigned_ops: set[tuple[int, int]] = set()
    assigned_machines: set[int] = set()

    idle_machines = sorted(
        machine.machine_id
        for machine in problem.machines
        if state.is_machine_idle(machine.machine_id)
    )

    for machine_id in idle_machines:
        if machine_id in assigned_machines:
            continue
        candidates = [
            ready_op
            for ready_op in ready
            if ready_op.machine_id == machine_id
            and (ready_op.job_id, ready_op.op_id) not in assigned_ops
        ]
        if not candidates:
            continue
        candidates.sort(
            key=lambda item: _dispatch_priority(problem, diagnostics, item)
        )
        selected = candidates[0]
        decisions.append(
            (selected.job_id, selected.op_id, selected.machine_id, state.current_time)
        )
        assigned_ops.add((selected.job_id, selected.op_id))
        assigned_machines.add(machine_id)

    return decisions


def construct_affected_set(
    problem: SchedulingProblem,
    state: ScheduleState,
    diagnostics: RGRALNSDiagnostics,
    ready_ops: list[ReadyOperation] | None = None,
    *,
    H_A: int,
    bottleneck_trigger_mode: str = "strict",
) -> set[int]:
    """Construct A(t), freeze non-mutable work, and apply the H_A cap."""

    ready = list(ready_ops if ready_ops is not None else collect_ready_operations(problem, state))
    ready_jobs = {ready_op.job_id for ready_op in ready}
    visible_jobs = {job.job_id: job for job in problem.jobs}
    candidate_jobs: set[int] = set()

    candidate_jobs.update(diagnostics.newly_arrived_jobs)
    candidate_jobs.update(diagnostics.mandatory_jobs)
    candidate_jobs.update(
        job_id
        for entity_diag in diagnostics.by_entity.values()
        if entity_diag.recoverability_class != "secured"
        for job_id in entity_diag.cover_jobs
    )
    candidate_jobs.update(
        job.job_id
        for job in problem.jobs
        if job.entity_id in diagnostics.high_risk_entities
        and not state.is_job_completed(job.job_id)
    )
    candidate_jobs.update(ready_jobs)

    mandatory_or_cover = diagnostics.mandatory_jobs.union(diagnostics.cover_jobs)
    reference_machines = {
        ready_op.machine_id
        for ready_op in ready
        if ready_op.job_id in mandatory_or_cover
    }
    competitor_jobs = {
        ready_op.job_id
        for ready_op in ready
        if ready_op.machine_id in reference_machines
    }
    candidate_jobs.update(competitor_jobs)

    bottleneck_machines = _bottleneck_machines(diagnostics, ready)
    bottleneck_competitors = _bottleneck_competitor_jobs(
        problem,
        diagnostics,
        ready,
        bottleneck_machines,
        bottleneck_trigger_mode,
    )
    candidate_jobs.update(bottleneck_competitors)

    frozen_removed: set[int] = set()
    for job_id in list(candidate_jobs):
        job = visible_jobs.get(job_id)
        if job is None:
            frozen_removed.add(job_id)
            continue
        if state.is_job_completed(job_id) or _job_has_ongoing_operation(job, state):
            frozen_removed.add(job_id)
            continue
        if job.entity_id not in diagnostics.high_risk_entities:
            if job_id not in mandatory_or_cover and job_id not in competitor_jobs:
                frozen_removed.add(job_id)
    candidate_jobs.difference_update(frozen_removed)
    candidate_jobs.intersection_update(diagnostics.visible_job_ids)

    ordered = sorted(
        candidate_jobs,
        key=lambda job_id: _affected_cap_priority(
            problem,
            state,
            diagnostics,
            job_id,
            ready_jobs,
            bottleneck_competitors,
        ),
    )
    return set(ordered[:H_A])


class RGRALNS:
    """Event-driven online Recoverability-Guided Reactive ALNS."""

    def __init__(self, config: RGRALNSConfig | None = None):
        self.config = config or RGRALNSConfig()
        self._rng = random.Random(self.config.random_seed)
        self._last_visible_job_ids: set[int] = set()

        self.trigger_count = 0
        self.trigger_reason_counts: dict[str, int] = {}
        self.affected_set_sizes: list[int] = []
        self.alns_runtime_total = 0.0
        self.dispatch_fallback_count = 0
        self.diagnostic_history: list[dict] = []

        self.last_triggered = False
        self.last_trigger_reasons: dict[str, bool] = {}
        self.last_affected_set: set[int] = set()
        self.last_local_job_order: list[int] = []
        self.last_diagnostics: RGRALNSDiagnostics | None = None

        self._destroy_weights = {
            "blocking_mandatory": 1.0,
            "low_service_contribution": 1.0,
            "over_secured": 1.0,
            "bottleneck_blockers": 1.0,
            "high_tardiness_low_service": 1.0,
        }
        self._repair_weights = {
            "mandatory_first": 1.0,
            "service_cover": 1.0,
            "service_safe_edd_spt": 1.4,
            "recoverability_gain": 1.0,
            "rg_regret_k": 1.0,
            "edd_spt": 1.0,
        }

    @property
    def avg_A_size(self) -> float:
        if not self.affected_set_sizes:
            return 0.0
        return sum(self.affected_set_sizes) / len(self.affected_set_sizes)

    @property
    def max_A_size(self) -> int:
        return max(self.affected_set_sizes, default=0)

    def __call__(
        self,
        problem: SchedulingProblem,
        state: ScheduleState,
    ) -> list[tuple[int, int, int, int]]:
        visible_job_ids = {job.job_id for job in problem.jobs}
        newly_arrived = visible_job_ids - self._last_visible_job_ids
        self._last_visible_job_ids = set(visible_job_ids)

        ready_ops = collect_ready_operations(problem, state)
        diagnostics = compute_recoverability_diagnostics(
            problem,
            state,
            newly_arrived,
            eps=self.config.eps,
        )
        self.last_diagnostics = diagnostics
        self._record_diagnostics(state, diagnostics)

        reasons = self._trigger_reasons(problem, state, diagnostics, ready_ops)
        should_run_alns = self.config.enable_alns and any(reasons.values())
        self.last_trigger_reasons = reasons
        self.last_triggered = bool(should_run_alns)

        if not should_run_alns:
            self.last_affected_set = set()
            self.last_local_job_order = []
            return lightweight_rg_dispatch(problem, state, diagnostics, ready_ops)

        self.trigger_count += 1
        for reason, active in reasons.items():
            if active:
                self.trigger_reason_counts[reason] = self.trigger_reason_counts.get(reason, 0) + 1

        affected_set = construct_affected_set(
            problem,
            state,
            diagnostics,
            ready_ops,
            H_A=self.config.H_A,
            bottleneck_trigger_mode=self.config.bottleneck_trigger_mode,
        )
        self.last_affected_set = set(affected_set)
        self.affected_set_sizes.append(len(affected_set))

        if not affected_set:
            self.dispatch_fallback_count += 1
            self.last_local_job_order = []
            return lightweight_rg_dispatch(problem, state, diagnostics, ready_ops)

        start = time.perf_counter()
        local_schedule = self._run_local_alns(problem, state, diagnostics, ready_ops, affected_set)
        self.alns_runtime_total += time.perf_counter() - start

        decisions = _extract_current_feasible_operations(problem, state, local_schedule, affected_set)
        if not decisions:
            self.dispatch_fallback_count += 1
            decisions = lightweight_rg_dispatch(problem, state, diagnostics, ready_ops)
        return decisions

    def _trigger_reasons(
        self,
        problem: SchedulingProblem,
        state: ScheduleState,
        diagnostics: RGRALNSDiagnostics,
        ready_ops: list[ReadyOperation],
    ) -> dict[str, bool]:
        return {
            "shortfall": _should_trigger_due_to_shortfall(diagnostics),
            "mandatory_ready": _should_trigger_due_to_mandatory_ready(diagnostics, ready_ops),
            "high_risk_arrival": _should_trigger_due_to_high_risk_arrival(diagnostics),
            "bottleneck_competition": _should_trigger_due_to_bottleneck_competition(
                problem, state, diagnostics, ready_ops, self.config.bottleneck_trigger_mode
            ),
            "cover_violation": _should_trigger_due_to_cover_violation(
                problem, state, diagnostics, ready_ops
            ),
        }

    def _record_diagnostics(
        self,
        state: ScheduleState,
        diagnostics: RGRALNSDiagnostics,
    ) -> None:
        self.diagnostic_history.append(
            {
                "time": state.current_time,
                "q_future": {
                    entity_id: diag.q_future
                    for entity_id, diag in sorted(diagnostics.by_entity.items())
                },
                "u_info": {
                    entity_id: diag.u_info
                    for entity_id, diag in sorted(diagnostics.by_entity.items())
                },
                "class": {
                    entity_id: diag.recoverability_class
                    for entity_id, diag in sorted(diagnostics.by_entity.items())
                },
            }
        )

    def _run_local_alns(
        self,
        problem: SchedulingProblem,
        state: ScheduleState,
        diagnostics: RGRALNSDiagnostics,
        ready_ops: list[ReadyOperation],
        affected_set: set[int],
    ) -> LocalSchedule:
        initial_order = _initial_local_order(problem, state, diagnostics, affected_set)
        incumbent = _decode_local_sequence(problem, state, initial_order)
        incumbent_eval = _evaluate_local_schedule(
            problem,
            state,
            incumbent,
            diagnostics,
            initial_order,
            self.config,
        )
        best = incumbent
        best_eval = incumbent_eval
        current_order = list(initial_order)

        destroy_ops: dict[str, DestroyOperator] = {
            "blocking_mandatory": _destroy_blocking_mandatory,
            "low_service_contribution": _destroy_low_service_contribution,
            "over_secured": _destroy_over_secured,
            "bottleneck_blockers": _destroy_bottleneck_blockers,
            "high_tardiness_low_service": _destroy_high_tardiness_low_service,
        }
        repair_ops: dict[str, RepairOperator] = {
            "mandatory_first": _repair_mandatory_first,
            "service_cover": _repair_service_cover,
            "service_safe_edd_spt": _repair_service_safe_edd_spt,
            "recoverability_gain": _repair_recoverability_gain,
            "rg_regret_k": self._repair_rg_regret_k,
            "edd_spt": _repair_edd_spt,
        }

        for _iter in range(self.config.N_A):
            destroy_name = _weighted_choice(self._rng, self._destroy_weights)
            repair_name = _weighted_choice(self._rng, self._repair_weights)
            destroy_size = max(1, math.ceil(len(current_order) * self.config.destroy_fraction))
            kept, removed = destroy_ops[destroy_name](
                current_order,
                problem,
                state,
                diagnostics,
                ready_ops,
                destroy_size,
            )
            candidate_order = repair_ops[repair_name](kept, removed, problem, state, diagnostics)
            candidate_order = _dedupe_order(candidate_order, affected_set)
            candidate = _decode_local_sequence(problem, state, candidate_order)
            candidate_eval = _evaluate_local_schedule(
                problem,
                state,
                candidate,
                diagnostics,
                initial_order,
                self.config,
            )

            accepted = _accept_candidate(
                candidate_eval,
                incumbent_eval,
                self.config.eps,
                self.config.acceptance_mode,
            )
            if accepted:
                current_order = list(candidate_order)
                incumbent = candidate
                incumbent_eval = candidate_eval
                self._destroy_weights[destroy_name] += 0.2
                self._repair_weights[repair_name] += 0.2
                if _accept_candidate(
                    candidate_eval,
                    best_eval,
                    self.config.eps,
                    self.config.acceptance_mode,
                ):
                    best = candidate
                    best_eval = candidate_eval
            else:
                self._destroy_weights[destroy_name] = max(0.2, self._destroy_weights[destroy_name] * 0.99)
                self._repair_weights[repair_name] = max(0.2, self._repair_weights[repair_name] * 0.99)

        self.last_local_job_order = list(best.job_order)
        return best

    def _repair_rg_regret_k(
        self,
        kept: list[int],
        removed: list[int],
        problem: SchedulingProblem,
        state: ScheduleState,
        diagnostics: RGRALNSDiagnostics,
    ) -> list[int]:
        del state
        order = list(kept)
        remaining = list(removed)
        while remaining:
            scored: list[tuple[float, tuple, int]] = []
            for job_id in remaining:
                costs = [
                    _insertion_cost(problem, diagnostics, job_id, pos)
                    for pos in range(len(order) + 1)
                ]
                costs.sort()
                best_cost = costs[0]
                kth_idx = min(self.config.regret_k - 1, len(costs) - 1)
                regret = _tuple_cost_value(costs[kth_idx]) - _tuple_cost_value(best_cost)
                scored.append((-regret, best_cost, job_id))
            scored.sort(key=lambda item: (item[0], item[1], item[2]))
            _neg_regret, _cost, selected = scored[0]
            best_pos = min(
                range(len(order) + 1),
                key=lambda pos: _insertion_cost(problem, diagnostics, selected, pos),
            )
            order.insert(best_pos, selected)
            remaining.remove(selected)
        return order


def run_rg_ralns(**kwargs) -> RGRALNS:
    """Factory matching the simulator SchedulingAlgorithm signature."""

    return RGRALNS(RGRALNSConfig(**kwargs))


def run_lightweight_rg_dispatch(**kwargs) -> RGRALNS:
    """Ablation factory: RG diagnostics plus dispatch, without local ALNS."""

    return RGRALNS(RGRALNSConfig(enable_alns=False, **kwargs))


def _heuristic_service_cover(
    problem: SchedulingProblem,
    entity: ServiceEntity,
    diag: EntityDiagnostics,
    eps: float,
) -> list[int]:
    uncovered = diag.q_cover
    remaining = sorted(diag.visible_recoverable_jobs)
    cover: list[int] = []

    while uncovered > eps and remaining:
        remaining.sort(
            key=lambda job_id: _cover_priority(problem, entity, diag, job_id, uncovered)
        )
        selected = remaining.pop(0)
        cover.append(selected)
        uncovered -= min(float(_visible_job(problem, selected).quantity), uncovered)
    return cover


def _cover_priority(
    problem: SchedulingProblem,
    entity: ServiceEntity,
    diag: EntityDiagnostics,
    job_id: int,
    uncovered: float,
) -> tuple[int, float, int, float, int]:
    job = _visible_job(problem, job_id)
    mandatory_flag = 0 if job_id in diag.mandatory_jobs else 1
    marginal = min(float(job.quantity), uncovered)
    effective_deadline = entity.deadline - entity.transport_delay
    remaining_work = diag.remaining_work_by_job.get(job_id, _remaining_job_work(job, ScheduleState()))
    return (
        mandatory_flag,
        -marginal,
        effective_deadline,
        remaining_work,
        job_id,
    )


def _recoverability_class(
    problem: SchedulingProblem,
    diag: EntityDiagnostics,
    eps: float,
) -> str:
    if diag.q_rem <= eps:
        return "secured"
    if diag.u_info > eps:
        return "at_risk"
    if diag.u_info <= eps and diag.q_rec + eps < diag.q_rem and diag.q_future > eps:
        return "arrival_dependent"

    surplus = diag.q_rec - diag.q_cover
    visible_quantities = [
        float(_visible_job(problem, job_id).quantity)
        for job_id in diag.visible_recoverable_jobs
    ]
    smallest_visible = min(visible_quantities) if visible_quantities else math.inf
    if (
        diag.u_info <= eps
        and diag.q_rec + eps >= diag.q_cover
        and (diag.mandatory_jobs or surplus + eps < smallest_visible)
    ):
        return "fragile"
    return "stable"


def _dispatch_priority(
    problem: SchedulingProblem,
    diagnostics: RGRALNSDiagnostics,
    ready: ReadyOperation,
) -> tuple[int, int, int, float, float, int, int]:
    job = _visible_job(problem, ready.job_id)
    return (
        _service_rank(job, diagnostics),
        _effective_production_deadline(problem, job),
        ready.processing_time,
        -_marginal_service_quantity(job, diagnostics),
        _remaining_job_work_from_diag(job, diagnostics),
        job.job_id,
        ready.op_id,
    )


def _service_rank(job: Job, diagnostics: RGRALNSDiagnostics) -> int:
    if job.job_id in diagnostics.mandatory_jobs:
        return 0
    entity_diag = diagnostics.by_entity[job.entity_id]
    if entity_diag.recoverability_class != "secured" and job.job_id in entity_diag.cover_jobs:
        return 1
    if job.entity_id in diagnostics.high_risk_entities:
        return 2
    return 3


def _marginal_service_quantity(job: Job, diagnostics: RGRALNSDiagnostics) -> float:
    diag = diagnostics.by_entity[job.entity_id]
    if diag.q_rem <= 0.0:
        return 0.0
    return min(float(job.quantity), diag.q_rem)


def _affected_cap_priority(
    problem: SchedulingProblem,
    state: ScheduleState,
    diagnostics: RGRALNSDiagnostics,
    job_id: int,
    ready_jobs: set[int],
    bottleneck_competitors: set[int],
) -> tuple[int, int, int, int, int, int, float, int]:
    job = _visible_job(problem, job_id)
    entity_id = job.entity_id
    new_high_risk = (
        job_id in diagnostics.newly_arrived_jobs
        and entity_id in diagnostics.high_risk_entities
    )
    ready_high_risk = job_id in ready_jobs and entity_id in diagnostics.high_risk_entities
    return (
        0 if job_id in diagnostics.mandatory_jobs else 1,
        0 if job_id in diagnostics.cover_jobs else 1,
        0 if new_high_risk else 1,
        0 if ready_high_risk else 1,
        0 if job_id in bottleneck_competitors else 1,
        _effective_production_deadline(problem, job),
        _remaining_job_work(job, state),
        job_id,
    )


def _bottleneck_machines(
    diagnostics: RGRALNSDiagnostics,
    ready_ops: list[ReadyOperation],
) -> set[int]:
    by_machine: dict[int, list[ReadyOperation]] = {}
    for ready in ready_ops:
        by_machine.setdefault(ready.machine_id, []).append(ready)

    bottlenecks: set[int] = set()
    for machine_id, machine_ready in by_machine.items():
        has_priority_job = any(
            ready.job_id in diagnostics.mandatory_jobs
            or ready.job_id in diagnostics.cover_jobs
            or diagnostics.job_entity.get(ready.job_id) in diagnostics.high_risk_entities
            for ready in machine_ready
        )
        priority_jobs = {
            ready.job_id
            for ready in machine_ready
            if ready.job_id in diagnostics.mandatory_jobs
            or ready.job_id in diagnostics.cover_jobs
            or diagnostics.job_entity.get(ready.job_id) in diagnostics.high_risk_entities
        }
        has_other_visible_job = any(
            ready.job_id not in priority_jobs
            for ready in machine_ready
        )
        if has_priority_job and has_other_visible_job:
            bottlenecks.add(machine_id)
    return bottlenecks


def _median_processing_time(ready_ops: list[ReadyOperation]) -> float:
    if not ready_ops:
        return 0.0
    pts = sorted(float(ready.processing_time) for ready in ready_ops)
    mid = len(pts) // 2
    if len(pts) % 2 == 1:
        return pts[mid]
    return (pts[mid - 1] + pts[mid]) / 2.0


def _bottleneck_competitor_jobs(
    problem: SchedulingProblem,
    diagnostics: RGRALNSDiagnostics,
    ready_ops: list[ReadyOperation],
    bottleneck_machines: set[int],
    mode: str,
) -> set[int]:
    by_machine: dict[int, list[ReadyOperation]] = {}
    for ready in ready_ops:
        if ready.machine_id in bottleneck_machines:
            by_machine.setdefault(ready.machine_id, []).append(ready)

    competitors: set[int] = set()
    for machine_ready in by_machine.values():
        median_pt = _median_processing_time(machine_ready)
        for ready in machine_ready:
            if mode == "normal":
                competitors.add(ready.job_id)
                continue
            job = _visible_job(problem, ready.job_id)
            rank = _service_rank(job, diagnostics)
            if rank >= 3 or ready.processing_time >= median_pt:
                competitors.add(ready.job_id)
    return competitors


def _initial_local_order(
    problem: SchedulingProblem,
    state: ScheduleState,
    diagnostics: RGRALNSDiagnostics,
    affected_set: set[int],
) -> list[int]:
    return sorted(
        affected_set,
        key=lambda job_id: (
            _service_rank(_visible_job(problem, job_id), diagnostics),
            _effective_production_deadline(problem, _visible_job(problem, job_id)),
            _remaining_job_work(_visible_job(problem, job_id), state),
            -_marginal_service_quantity(_visible_job(problem, job_id), diagnostics),
            job_id,
        ),
    )


def _decode_local_sequence(
    problem: SchedulingProblem,
    state: ScheduleState,
    job_order: list[int],
) -> LocalSchedule:
    machine_available = {
        machine.machine_id: max(
            state.current_time,
            state.machine_available_times.get(machine.machine_id, 0),
        )
        for machine in problem.machines
    }
    scheduled: list[ScheduledOperation] = []
    completion_times: dict[int, int] = {}

    for job_id in job_order:
        job = _visible_job(problem, job_id)
        if state.is_job_completed(job.job_id) or _job_has_ongoing_operation(job, state):
            continue
        job_ready = max(state.current_time, job.release_time)
        next_idx = state.next_op_index_for_job(job.job_id)
        for op in job.operations[next_idx:]:
            if state.is_operation_completed(job.job_id, op.op_id):
                continue
            if state.is_operation_ongoing(job.job_id, op.op_id):
                break
            best_machine, best_start, best_end = _best_machine_slot(
                op,
                machine_available,
                job_ready,
            )
            sop = ScheduledOperation(
                job_id=job.job_id,
                op_id=op.op_id,
                machine_id=best_machine,
                start_time=best_start,
                end_time=best_end,
            )
            scheduled.append(sop)
            machine_available[best_machine] = best_end
            job_ready = best_end
        if scheduled and scheduled[-1].job_id == job.job_id:
            completion_times[job.job_id] = scheduled[-1].end_time

    return LocalSchedule(
        job_order=list(job_order),
        scheduled_operations=scheduled,
        completion_times=completion_times,
    )


def _best_machine_slot(
    op: Operation,
    machine_available: dict[int, int],
    job_ready: int,
) -> tuple[int, int, int]:
    choices: list[tuple[int, int, int, int]] = []
    for alt in op.alternatives:
        machine_id = alt.machine_id
        start = max(job_ready, machine_available.get(machine_id, 0))
        end = start + alt.processing_time
        choices.append((end, start, alt.processing_time, machine_id))
    end, start, _pt, machine_id = min(choices)
    return machine_id, start, end


def _evaluate_local_schedule(
    problem: SchedulingProblem,
    state: ScheduleState,
    local_schedule: LocalSchedule,
    diagnostics: RGRALNSDiagnostics,
    reference_order: list[int],
    config: RGRALNSConfig,
) -> CandidateEvaluation:
    completion_times = dict(state.completed_jobs)
    completion_times.update(local_schedule.completion_times)

    tt = 0.0
    on_time_quantity = {entity.entity_id: 0.0 for entity in problem.entities}
    for job in problem.jobs:
        completion = completion_times.get(job.job_id)
        if completion is None:
            continue
        entity = problem.get_entity(job.entity_id)
        delivery = completion + entity.transport_delay
        tt += max(0.0, delivery - entity.deadline)
        if delivery <= entity.deadline:
            on_time_quantity[entity.entity_id] += float(job.quantity)

    wsf = 0.0
    risk_by_entity: dict[int, float] = {}
    for entity in problem.entities:
        q_min = float(entity.min_fulfillment)
        visible_shortfall = max(0.0, q_min - on_time_quantity[entity.entity_id])
        wsf += entity.weight * visible_shortfall
        q_future = diagnostics.by_entity[entity.entity_id].q_future
        risk_by_entity[entity.entity_id] = max(
            0.0,
            q_min - on_time_quantity[entity.entity_id] - q_future,
        )

    alpha = problem.alpha if config.alpha is None else config.alpha
    beta = problem.beta if config.beta is None else config.beta
    z = alpha * tt + beta * wsf
    instability = _order_instability(local_schedule.job_order, reference_order)

    return CandidateEvaluation(
        z=z,
        tt=tt,
        wsf=wsf,
        risk_by_entity=risk_by_entity,
        instability=instability,
    )


def _accept_candidate(
    candidate: CandidateEvaluation,
    incumbent: CandidateEvaluation,
    eps: float,
    acceptance_mode: str = "service_safe_z",
) -> bool:
    for entity_id, risk in candidate.risk_by_entity.items():
        if risk > incumbent.risk_by_entity.get(entity_id, 0.0) + eps:
            return False

    if (
        acceptance_mode == "service_safe_z"
        and incumbent.wsf <= eps
        and candidate.wsf <= eps
    ):
        if candidate.z < incumbent.z - eps:
            return True
        if abs(candidate.z - incumbent.z) <= eps and candidate.tt < incumbent.tt - eps:
            return True
        if (
            abs(candidate.z - incumbent.z) <= eps
            and abs(candidate.tt - incumbent.tt) <= eps
            and candidate.instability < incumbent.instability - eps
        ):
            return True
        return False

    if incumbent.wsf <= eps and candidate.wsf > incumbent.wsf + eps:
        return False
    if candidate.wsf < incumbent.wsf - eps:
        return True
    if abs(candidate.wsf - incumbent.wsf) <= eps and candidate.z < incumbent.z - eps:
        return True
    if (
        abs(candidate.wsf - incumbent.wsf) <= eps
        and abs(candidate.z - incumbent.z) <= eps
        and candidate.instability < incumbent.instability - eps
    ):
        return True
    return False


def _extract_current_feasible_operations(
    problem: SchedulingProblem,
    state: ScheduleState,
    local_schedule: LocalSchedule,
    affected_set: set[int],
) -> list[tuple[int, int, int, int]]:
    decisions: list[tuple[int, int, int, int]] = []
    assigned_ops: set[tuple[int, int]] = set()
    assigned_machines: set[int] = set()
    visible_job_ids = {job.job_id for job in problem.jobs}

    for sop in sorted(local_schedule.scheduled_operations, key=lambda item: (item.machine_id, item.job_id, item.op_id)):
        if sop.start_time != state.current_time:
            continue
        if sop.job_id not in affected_set or sop.job_id not in visible_job_ids:
            continue
        if (sop.job_id, sop.op_id) in assigned_ops or sop.machine_id in assigned_machines:
            continue
        if not state.is_machine_idle(sop.machine_id):
            continue
        job = _visible_job(problem, sop.job_id)
        if job.release_time > state.current_time or state.is_job_completed(job.job_id):
            continue
        next_idx = state.next_op_index_for_job(job.job_id)
        if next_idx >= job.num_operations:
            continue
        op = job.operation_at(next_idx)
        if op.op_id != sop.op_id:
            continue
        if state.is_operation_completed(job.job_id, op.op_id):
            continue
        if state.is_operation_ongoing(job.job_id, op.op_id):
            continue
        try:
            op.processing_time_on(sop.machine_id)
        except KeyError:
            continue
        decisions.append((sop.job_id, sop.op_id, sop.machine_id, state.current_time))
        assigned_ops.add((sop.job_id, sop.op_id))
        assigned_machines.add(sop.machine_id)

    return decisions


def _destroy_blocking_mandatory(
    order: list[int],
    problem: SchedulingProblem,
    state: ScheduleState,
    diagnostics: RGRALNSDiagnostics,
    ready_ops: list[ReadyOperation],
    destroy_size: int,
) -> tuple[list[int], list[int]]:
    mandatory_machines = {
        ready.machine_id
        for ready in ready_ops
        if ready.job_id in diagnostics.mandatory_jobs
    }
    candidates = [
        job_id
        for job_id in order
        if job_id not in diagnostics.mandatory_jobs
        and _next_ready_machines(problem, state, job_id).intersection(mandatory_machines)
    ]
    return _remove_selected(order, candidates, destroy_size)


def _destroy_low_service_contribution(
    order: list[int],
    problem: SchedulingProblem,
    state: ScheduleState,
    diagnostics: RGRALNSDiagnostics,
    ready_ops: list[ReadyOperation],
    destroy_size: int,
) -> tuple[list[int], list[int]]:
    del state, ready_ops
    candidates = sorted(
        order,
        key=lambda job_id: (
            _marginal_service_quantity(_visible_job(problem, job_id), diagnostics),
            -_remaining_job_work_from_diag(_visible_job(problem, job_id), diagnostics),
            -_service_rank(_visible_job(problem, job_id), diagnostics),
            job_id,
        ),
    )
    return _remove_selected(order, candidates, destroy_size)


def _destroy_over_secured(
    order: list[int],
    problem: SchedulingProblem,
    state: ScheduleState,
    diagnostics: RGRALNSDiagnostics,
    ready_ops: list[ReadyOperation],
    destroy_size: int,
) -> tuple[list[int], list[int]]:
    del state, ready_ops
    candidates = [
        job_id
        for job_id in order
        if diagnostics.by_entity[_visible_job(problem, job_id).entity_id].recoverability_class
        in {"secured", "stable"}
    ]
    candidates.sort(
        key=lambda job_id: (
            _effective_production_deadline(problem, _visible_job(problem, job_id)),
            job_id,
        ),
        reverse=True,
    )
    return _remove_selected(order, candidates, destroy_size)


def _destroy_bottleneck_blockers(
    order: list[int],
    problem: SchedulingProblem,
    state: ScheduleState,
    diagnostics: RGRALNSDiagnostics,
    ready_ops: list[ReadyOperation],
    destroy_size: int,
) -> tuple[list[int], list[int]]:
    bottlenecks = _bottleneck_machines(diagnostics, ready_ops)
    candidates = [
        job_id
        for job_id in order
        if _next_ready_machines(problem, state, job_id).intersection(bottlenecks)
        and _service_rank(_visible_job(problem, job_id), diagnostics) > 1
    ]
    return _remove_selected(order, candidates, destroy_size)


def _destroy_high_tardiness_low_service(
    order: list[int],
    problem: SchedulingProblem,
    state: ScheduleState,
    diagnostics: RGRALNSDiagnostics,
    ready_ops: list[ReadyOperation],
    destroy_size: int,
) -> tuple[list[int], list[int]]:
    del ready_ops
    scored = []
    for job_id in order:
        job = _visible_job(problem, job_id)
        entity = problem.get_entity(job.entity_id)
        d_lb = max(state.current_time, job.release_time) + _remaining_job_work(job, state) + entity.transport_delay
        visible_tardiness = max(0.0, d_lb - entity.deadline)
        service = _marginal_service_quantity(job, diagnostics)
        scored.append((-visible_tardiness, service, job_id))
    scored.sort()
    return _remove_selected(order, [job_id for _tard, _service, job_id in scored], destroy_size)


def _repair_mandatory_first(
    kept: list[int],
    removed: list[int],
    problem: SchedulingProblem,
    state: ScheduleState,
    diagnostics: RGRALNSDiagnostics,
) -> list[int]:
    del state
    return sorted(
        kept + removed,
        key=lambda job_id: (
            _service_rank(_visible_job(problem, job_id), diagnostics),
            _effective_production_deadline(problem, _visible_job(problem, job_id)),
            _remaining_job_work_from_diag(_visible_job(problem, job_id), diagnostics),
            job_id,
        ),
    )


def _repair_service_cover(
    kept: list[int],
    removed: list[int],
    problem: SchedulingProblem,
    state: ScheduleState,
    diagnostics: RGRALNSDiagnostics,
) -> list[int]:
    del state
    cover_jobs = diagnostics.cover_jobs
    all_jobs = _dedupe_order(list(cover_jobs) + kept + removed, set(kept + removed))
    return sorted(
        all_jobs,
        key=lambda job_id: (
            0 if job_id in cover_jobs else 1,
            _service_rank(_visible_job(problem, job_id), diagnostics),
            _effective_production_deadline(problem, _visible_job(problem, job_id)),
            job_id,
        ),
    )


def _repair_service_safe_edd_spt(
    kept: list[int],
    removed: list[int],
    problem: SchedulingProblem,
    state: ScheduleState,
    diagnostics: RGRALNSDiagnostics,
) -> list[int]:
    all_jobs = _dedupe_order(kept + removed, set(kept + removed))
    service_critical = [
        job_id
        for job_id in all_jobs
        if job_id in diagnostics.mandatory_jobs or job_id in diagnostics.cover_jobs
    ]
    remaining = [job_id for job_id in all_jobs if job_id not in set(service_critical)]
    service_critical.sort(
        key=lambda job_id: (
            _service_rank(_visible_job(problem, job_id), diagnostics),
            _effective_production_deadline(problem, _visible_job(problem, job_id)),
            _remaining_job_work(_visible_job(problem, job_id), state),
            job_id,
        )
    )
    remaining.sort(
        key=lambda job_id: _tt_oriented_insertion_key(problem, state, job_id)
    )
    return service_critical + remaining


def _repair_recoverability_gain(
    kept: list[int],
    removed: list[int],
    problem: SchedulingProblem,
    state: ScheduleState,
    diagnostics: RGRALNSDiagnostics,
) -> list[int]:
    del state
    return sorted(
        kept + removed,
        key=lambda job_id: (
            -_recoverability_gain(problem, diagnostics, job_id),
            _service_rank(_visible_job(problem, job_id), diagnostics),
            _effective_production_deadline(problem, _visible_job(problem, job_id)),
            job_id,
        ),
    )


def _repair_edd_spt(
    kept: list[int],
    removed: list[int],
    problem: SchedulingProblem,
    state: ScheduleState,
    diagnostics: RGRALNSDiagnostics,
) -> list[int]:
    del diagnostics
    return sorted(
        kept + removed,
        key=lambda job_id: (
            _effective_production_deadline(problem, _visible_job(problem, job_id)),
            _remaining_job_work(_visible_job(problem, job_id), state),
            job_id,
        ),
    )


def _tt_oriented_insertion_key(
    problem: SchedulingProblem,
    state: ScheduleState,
    job_id: int,
) -> tuple[int, float, float, float, int]:
    job = _visible_job(problem, job_id)
    entity = problem.get_entity(job.entity_id)
    remaining_work = _remaining_job_work(job, state)
    projected_delivery = max(state.current_time, job.release_time) + remaining_work + entity.transport_delay
    projected_tardiness = max(0.0, projected_delivery - entity.deadline)
    next_pt = _next_operation_min_processing_time(job, state)
    return (
        _effective_production_deadline(problem, job),
        projected_tardiness,
        next_pt,
        remaining_work,
        job_id,
    )


def _next_operation_min_processing_time(job: Job, state: ScheduleState) -> float:
    next_idx = state.next_op_index_for_job(job.job_id)
    if next_idx >= job.num_operations:
        return 0.0
    return float(job.operation_at(next_idx).min_processing_time)


def _recoverability_gain(
    problem: SchedulingProblem,
    diagnostics: RGRALNSDiagnostics,
    job_id: int,
) -> float:
    job = _visible_job(problem, job_id)
    diag = diagnostics.by_entity[job.entity_id]
    before = max(0.0, diag.q_rem - diag.q_future)
    after = max(0.0, diag.q_rem - diag.q_future - job.quantity)
    return before - after


def _remove_selected(
    order: list[int],
    candidates: list[int],
    destroy_size: int,
) -> tuple[list[int], list[int]]:
    if not candidates:
        candidates = list(reversed(order))
    selected = set(candidates[:destroy_size])
    kept = [job_id for job_id in order if job_id not in selected]
    removed = [job_id for job_id in order if job_id in selected]
    return kept, removed


def _weighted_choice(rng: random.Random, weights: dict[str, float]) -> str:
    names = sorted(weights)
    total = sum(max(0.0, weights[name]) for name in names)
    if total <= 0.0:
        return names[0]
    threshold = rng.random() * total
    cumulative = 0.0
    for name in names:
        cumulative += max(0.0, weights[name])
        if cumulative >= threshold:
            return name
    return names[-1]


def _dedupe_order(order: list[int], allowed: set[int]) -> list[int]:
    seen: set[int] = set()
    result: list[int] = []
    for job_id in order:
        if job_id not in allowed or job_id in seen:
            continue
        result.append(job_id)
        seen.add(job_id)
    for job_id in sorted(allowed - seen):
        result.append(job_id)
    return result


def _insertion_cost(
    problem: SchedulingProblem,
    diagnostics: RGRALNSDiagnostics,
    job_id: int,
    position: int,
) -> tuple[int, int, float, int]:
    job = _visible_job(problem, job_id)
    return (
        _service_rank(job, diagnostics),
        position,
        _remaining_job_work_from_diag(job, diagnostics),
        job_id,
    )


def _tuple_cost_value(cost: tuple[int, int, float, int]) -> float:
    return cost[0] * 1_000_000.0 + cost[1] * 1_000.0 + cost[2] + cost[3] * 1e-6


def _order_instability(order: list[int], reference_order: list[int]) -> float:
    position = {job_id: idx for idx, job_id in enumerate(reference_order)}
    instability = 0
    for idx, job_id in enumerate(order):
        instability += abs(idx - position.get(job_id, idx))
    return float(instability)


def _secured_quantity(
    problem: SchedulingProblem,
    state: ScheduleState,
    entity: ServiceEntity,
) -> float:
    total = 0.0
    for job in problem.jobs_of_entity(entity.entity_id):
        completion = state.completed_jobs.get(job.job_id)
        if completion is None:
            continue
        if completion + entity.transport_delay <= entity.deadline:
            total += float(job.quantity)
    return total


def _remaining_job_work(job: Job, state: ScheduleState) -> float:
    work = 0.0
    for op in job.operations:
        op_key = (job.job_id, op.op_id)
        if op_key in state.completed_operations:
            continue
        ongoing = state.ongoing_operations.get(op_key)
        if ongoing is not None:
            work += max(0, ongoing.end_time - state.current_time)
        else:
            work += float(op.min_processing_time)
    return work


def _remaining_job_work_from_diag(job: Job, diagnostics: RGRALNSDiagnostics) -> float:
    diag = diagnostics.by_entity[job.entity_id]
    return diag.remaining_work_by_job.get(job.job_id, 0.0)


def _future_quantity(problem: SchedulingProblem, entity_id: int) -> float:
    return float(getattr(problem, "entity_future_quantity", {}).get(entity_id, 0))


def _effective_production_deadline(problem: SchedulingProblem, job: Job) -> int:
    entity = problem.get_entity(job.entity_id)
    return entity.deadline - entity.transport_delay


def _visible_job(problem: SchedulingProblem, job_id: int) -> Job:
    return problem.get_job(job_id)


def _job_has_ongoing_operation(job: Job, state: ScheduleState) -> bool:
    return any((job.job_id, op.op_id) in state.ongoing_operations for op in job.operations)


def _next_ready_machines(
    problem: SchedulingProblem,
    state: ScheduleState,
    job_id: int,
) -> set[int]:
    job = _visible_job(problem, job_id)
    next_idx = state.next_op_index_for_job(job_id)
    if next_idx >= job.num_operations:
        return set()
    op = job.operation_at(next_idx)
    if state.is_operation_completed(job_id, op.op_id) or state.is_operation_ongoing(job_id, op.op_id):
        return set()
    return set(op.eligible_machines)


__all__ = [
    "CandidateEvaluation",
    "EntityDiagnostics",
    "LocalSchedule",
    "RGRALNS",
    "RGRALNSConfig",
    "RGRALNSDiagnostics",
    "ReadyOperation",
    "collect_ready_operations",
    "compute_recoverability_diagnostics",
    "construct_affected_set",
    "lightweight_rg_dispatch",
    "run_lightweight_rg_dispatch",
    "run_rg_ralns",
    "_accept_candidate",
    "_repair_service_safe_edd_spt",
    "_should_trigger_due_to_bottleneck_competition",
    "_should_trigger_due_to_cover_violation",
    "_should_trigger_due_to_high_risk_arrival",
    "_should_trigger_due_to_mandatory_ready",
    "_should_trigger_due_to_shortfall",
]
