"""RG-ALNS: recoverability-guided adaptive large-neighborhood search.

The main path uses rolling-horizon projected schedule construction, adaptive
LNS destroy-repair, local search, and bounded exact local repair.
Optional exact support is limited to small local repairs selected by the
recoverability logic; it is not used as a global fallback in the main variant.
"""

import logging
import time
from dataclasses import dataclass, field
from fractions import Fraction
from math import ceil

from ..core.dataclasses import Job, Operation, SLISPInstance
from ..core.schedule_state import ScheduleState
from ..core.objective import compute_objective
from ..recoverability.earliest_bounds import (
    eligible_recovery_jobs,
    optimistic_delivery_lower_bound,
    optimistic_remaining_operation_time,
    remaining_service_quantity,
)
from ..recoverability.knapsack_recovery import (
    exclusion_recoverable_quantity,
    maximum_recoverable_service_quantity,
)
from ..recoverability.mandatory_jobs import mandatory_rescue_jobs
from ..recoverability.shortfall_bounds import (
    current_information_shortfall_risk,
    known_future_quantity,
    unavoidable_shortfall_lower_bound,
)
from ..utils.random_seed import create_rng

EPS = 1e-9
TIME_DENOM_EPS = 1.0
DESTROY_OPERATOR_NAMES = [
    "random",
    "worst_tardiness",
    "low_rg_score",
    "entity_shortfall",
    "time_window",
]
REPAIR_OPERATOR_NAMES = [
    "regret_k",
    "random_order",
    "edf",
    "rg_priority",
]
SEQUENCE_CROSSOVER_REPAIR = "sequence_crossover"
ALL_REPAIR_OPERATOR_NAMES = REPAIR_OPERATOR_NAMES + [SEQUENCE_CROSSOVER_REPAIR]
logger = logging.getLogger(__name__)


def _effective_deadline(instance: SLISPInstance, job: Job) -> int:
    """Production-side cutoff before entity-specific transport delay."""
    entity = instance.get_entity(job.entity_id)
    return entity.deadline - entity.transport_delay


def _entity_quota_pressure(
    instance: SLISPInstance,
    state: ScheduleState,
    entity_id: int,
) -> float:
    """How much of the still-eligible quantity is needed to meet service quota.

    Values near one mean the entity has little room for additional late jobs.
    The entity weight is applied outside this helper when ranking jobs.
    """
    q_rem = remaining_service_quantity(entity_id, state, instance)
    if q_rem <= 0:
        return 0.0

    entity = instance.get_entity(entity_id)
    eligible_qty = 0.0
    for job in instance.jobs:
        if job.entity_id != entity_id or state.is_job_completed(job.job_id):
            continue
        if optimistic_delivery_lower_bound(job, state, instance) <= entity.deadline:
            eligible_qty += job.quantity

    if eligible_qty <= 0:
        return 2.0
    return min(2.0, q_rem / max(1.0, eligible_qty))


def _remaining_job_work(job: Job, state: ScheduleState) -> int:
    """Optimistic remaining processing work of a job."""
    return sum(
        optimistic_remaining_operation_time(op, job, state)
        for op in job.operations
    )


def _job_total_min_work(instance: SLISPInstance, job_id: int) -> int:
    """Total minimum remaining-independent processing work of a job."""
    return sum(op.min_processing_time for op in instance.get_job(job_id).operations)


def _useful_service_quantity(
    instance: SLISPInstance,
    state: ScheduleState,
    job: Job,
) -> float:
    """Quantity of this job that can still reduce entity service shortfall."""
    q_rem = remaining_service_quantity(job.entity_id, state, instance)
    if q_rem <= 0:
        return 0.0
    return min(float(job.quantity), float(q_rem))


def _quota_marginal_service_quantity(
    instance: SLISPInstance,
    state: ScheduleState,
    pool_B: set[int],
    job: Job,
) -> float:
    """Service quantity whose loss would increase the entity shortfall bound."""
    q_rem = remaining_service_quantity(job.entity_id, state, instance)
    if q_rem <= 0:
        return 0.0

    q_rec_all, _ = maximum_recoverable_service_quantity(
        job.entity_id, pool_B, state, instance, method="dp"
    )
    q_rec_without = exclusion_recoverable_quantity(
        job.entity_id, job.job_id, pool_B, state, instance, method="dp"
    )
    marginal = max(0.0, min(float(q_rem), float(q_rec_all)) - min(float(q_rem), float(q_rec_without)))
    return min(_useful_service_quantity(instance, state, job), marginal)


def _tardiness_opportunity_gain(
    instance: SLISPInstance,
    state: ScheduleState,
    job: Job,
    op: Operation,
    processing_time: int,
    delay_duration: int,
) -> float:
    """How much projected tardiness grows if this operation waits once more."""
    remaining_work = max(1, _remaining_job_work(job, state))
    current_op_work = optimistic_remaining_operation_time(op, job, state)
    remaining_after_current = max(0, remaining_work - current_op_work)
    completion_if_now = state.current_time + processing_time + remaining_after_current
    completion_if_delayed = completion_if_now + max(0, delay_duration)
    effective_due = _effective_deadline(instance, job)
    tard_now = max(0, completion_if_now - effective_due)
    tard_delayed = max(0, completion_if_delayed - effective_due)
    return instance.alpha * max(0, tard_delayed - tard_now)


def _quantity_scale_for_target(q_rem: float) -> int:
    return Fraction(str(q_rem)).limit_denominator(1_000).denominator


def _minimum_work_service_cover(
    instance: SLISPInstance,
    state: ScheduleState,
    entity_id: int,
) -> set[int]:
    """Minimum-work subset that covers the remaining service requirement.

    This is a quota-aware recovery-cover problem.  It is deliberately different
    from boosting every job of a fragile entity: only the cheapest quantity
    cover receives the strong service-recovery signal.
    """
    q_rem = remaining_service_quantity(entity_id, state, instance)
    if q_rem <= 0:
        return set()

    entity = instance.get_entity(entity_id)
    scale = _quantity_scale_for_target(q_rem)
    target = ceil(q_rem * scale - 1e-9)

    items: list[tuple[int, int, int]] = []
    for job in instance.jobs:
        if job.entity_id != entity_id or state.is_job_completed(job.job_id):
            continue
        if optimistic_delivery_lower_bound(job, state, instance) > entity.deadline:
            continue
        work = max(1, _remaining_job_work(job, state))
        items.append((job.job_id, job.quantity * scale, work))

    if not items or sum(q for _jid, q, _work in items) < target:
        return set()

    dp: dict[int, tuple[int, set[int]]] = {0: (0, set())}
    for jid, quantity, work in items:
        for achieved, (prev_work, selected) in list(dp.items()):
            new_achieved = min(target, achieved + quantity)
            new_work = prev_work + work
            incumbent = dp.get(new_achieved)
            if incumbent is None or new_work < incumbent[0]:
                dp[new_achieved] = (new_work, selected | {jid})

    return set(dp.get(target, (0, set()))[1])


# ── Scheduled operation assignment ──────────────────────────────────────────

@dataclass
class JobAssignment:
    """Complete assignment for one job: list of (machine_id, start_time) per op."""
    job_id: int
    ops: list[tuple[int, int, int]] = field(default_factory=list)  # (op_id, machine_id, start_time)

    @property
    def completion_time(self) -> int:
        raise AttributeError(
            "JobAssignment.completion_time requires operation processing times; "
            "use end_times(instance) or _projected_completion_time instead."
        )

    def end_times(self, instance: SLISPInstance) -> list[int]:
        job = instance.get_job(self.job_id)
        ends = []
        for op_id, m_id, start in self.ops:
            for op in job.operations:
                if op.op_id == op_id:
                    try:
                        pt = op.processing_time_on(m_id)
                    except KeyError:
                        pt = 1
                    ends.append(start + pt)
                    break
        return ends


# ── Solver-free Schedule ────────────────────────────────────────────────────

@dataclass
class FastSchedule:
    """Mutable schedule representation for solver-free manipulation."""
    assignments: dict[int, list[tuple[int, int, int]]] = field(default_factory=dict)
    machine_slots: dict[int, list[tuple[int, int, int, int]]] = field(default_factory=dict)

    def clone(self) -> "FastSchedule":
        import copy
        return FastSchedule(
            assignments=copy.deepcopy(self.assignments),
            machine_slots=copy.deepcopy(self.machine_slots),
        )

    def add_op(self, job_id: int, op_id: int, machine_id: int, start: int, end: int):
        if job_id not in self.assignments:
            self.assignments[job_id] = []
        self.assignments[job_id].append((op_id, machine_id, start))
        if machine_id not in self.machine_slots:
            self.machine_slots[machine_id] = []
        self.machine_slots[machine_id].append((job_id, op_id, start, end))
        self.machine_slots[machine_id].sort(key=lambda x: x[2])

    def remove_op(self, job_id: int, op_id: int):
        if job_id in self.assignments:
            self.assignments[job_id] = [
                a for a in self.assignments[job_id] if a[0] != op_id
            ]
            if not self.assignments[job_id]:
                del self.assignments[job_id]
        for m_id in list(self.machine_slots.keys()):
            self.machine_slots[m_id] = [
                s for s in self.machine_slots[m_id]
                if not (s[0] == job_id and s[1] == op_id)
            ]

    def remove_job(self, job_id: int):
        """Remove all operations of a job from the schedule."""
        if job_id in self.assignments:
            for op_id, _m, _s in self.assignments[job_id]:
                for m_id in list(self.machine_slots.keys()):
                    self.machine_slots[m_id] = [
                        s for s in self.machine_slots[m_id]
                        if not (s[0] == job_id and s[1] == op_id)
                    ]
            del self.assignments[job_id]

    def earliest_machine_time(self, machine_id: int, after: int = 0, duration: int = 0) -> int:
        """Find earliest feasible start after 'after' with no overlap on this machine."""
        slots = self.machine_slots.get(machine_id, [])
        t = after
        max_iters = len(slots) + 2
        for _ in range(max_iters):
            conflict = False
            for _jid, _oid, s, e in slots:
                if t < e and t + duration > s:  # overlap
                    t = e
                    conflict = True
                    break
            if not conflict:
                break
        return t

    def to_decisions(self) -> list[tuple[int, int, int, int]]:
        result = []
        for job_id, ops in self.assignments.items():
            for op_id, machine_id, start in ops:
                result.append((job_id, op_id, machine_id, start))
        return result


# ── Objective helpers ───────────────────────────────────────────────────────

def _compute_job_tardiness(
    job_id: int, completion_time: int, instance: SLISPInstance
) -> int:
    job = instance.get_job(job_id)
    entity = instance.get_entity(job.entity_id)
    delivery = completion_time + entity.transport_delay
    return max(0, delivery - entity.deadline)


def _projected_completion_time(
    job: Job,
    schedule: FastSchedule,
    instance: SLISPInstance,
    state: ScheduleState | None = None,
) -> int:
    """Estimate completion without treating missing projected work as done."""
    if state is not None and state.is_job_completed(job.job_id):
        return state.completed_jobs[job.job_id]

    op_by_id = {op.op_id: op for op in job.operations}
    if state is not None:
        latest_seq = state.next_op_index_for_job(job.job_id) - 1
        latest_end = max(state.current_time, job.release_time)
        for op in job.operations:
            key = (job.job_id, op.op_id)
            if state.is_operation_ongoing(job.job_id, op.op_id):
                ongoing = state.ongoing_operations[key]
                latest_seq = max(latest_seq, op.sequence_index)
                latest_end = max(latest_end, ongoing.end_time)
    else:
        latest_seq = -1
        latest_end = job.release_time

    for op_id, mid, start in schedule.assignments.get(job.job_id, []):
        op = op_by_id.get(op_id)
        if op is None:
            continue
        try:
            end = start + op.processing_time_on(mid)
        except KeyError:
            end = start + op.min_processing_time
        if op.sequence_index > latest_seq:
            latest_seq = op.sequence_index
            latest_end = end
        elif op.sequence_index == latest_seq:
            latest_end = max(latest_end, end)

    if latest_seq >= job.num_operations - 1:
        return latest_end

    for seq in range(latest_seq + 1, job.num_operations):
        latest_end += job.operation_at(seq).min_processing_time
    return latest_end


def _projected_job_completions(
    schedule: FastSchedule,
    instance: SLISPInstance,
    state: ScheduleState | None = None,
) -> dict[int, int]:
    """Projected job completion times under current history plus schedule."""
    job_completions = {
        job.job_id: _projected_completion_time(job, schedule, instance, state)
        for job in instance.jobs
    }
    if state is not None:
        for jid, c_time in state.completed_jobs.items():
            job_completions[jid] = c_time
    return job_completions


def _fast_eval_components(
    schedule: FastSchedule,
    instance: SLISPInstance,
    state: ScheduleState | None = None,
) -> tuple[float, float]:
    """Return projected (total tardiness, weighted service shortfall)."""
    job_completions = _projected_job_completions(schedule, instance, state)
    tt = 0.0
    for job in instance.jobs:
        c = job_completions.get(job.job_id, 0)
        entity = instance.get_entity(job.entity_id)
        delivery = c + entity.transport_delay
        tt += max(0, delivery - entity.deadline)

    wsf = 0.0
    for entity in instance.entities:
        on_time_qty = 0
        for job in instance.jobs:
            if job.entity_id == entity.entity_id and job.job_id in job_completions:
                c = job_completions[job.job_id]
                delivery = c + entity.transport_delay
                if delivery <= entity.deadline:
                    on_time_qty += job.quantity
        on_time_qty += known_future_quantity(entity.entity_id, instance)
        shortfall = max(0, entity.min_fulfillment - on_time_qty)
        wsf += entity.weight * shortfall

    return tt, wsf


def _fast_eval_wsf(
    schedule: FastSchedule,
    instance: SLISPInstance,
    state: ScheduleState | None = None,
) -> float:
    """Return only projected weighted service shortfall."""
    return _fast_eval_components(schedule, instance, state)[1]


def _fast_eval_Z(schedule: FastSchedule, instance: SLISPInstance,
                  state: ScheduleState | None = None) -> float:
    """Compute projected Z = alpha*TT + beta*WSF from a FastSchedule.

    If state is provided, completed jobs contribute their actual completion
    times.  Missing future work is charged through optimistic remaining work
    rather than being silently treated as complete at time zero.
    """
    tt, wsf = _fast_eval_components(schedule, instance, state)
    return instance.alpha * tt + instance.beta * wsf


def _normalize_operator_probabilities(
    names: list[str],
    raw_weights: dict[str, float],
    min_weight: float = 1e-6,
) -> list[float]:
    """Normalize nonnegative operator weights in a stable name order."""
    clipped = [max(min_weight, raw_weights.get(name, 0.0)) for name in names]
    total = sum(clipped)
    if total <= 0:
        return [1.0 / len(names) for _name in names]
    return [weight / total for weight in clipped]


def _combine_context_and_learned_weights(
    names: list[str],
    context_probs: list[float],
    learned_weights: dict[str, float],
    min_weight: float = 1e-6,
) -> list[float]:
    """Use RG context as a prior and learned operator weights as feedback."""
    raw = {
        name: context_probs[idx] * max(min_weight, learned_weights.get(name, 1.0))
        for idx, name in enumerate(names)
    }
    return _normalize_operator_probabilities(names, raw, min_weight=1e-12)


def _weighted_operator_choice(names: list[str], probs: list[float], rng) -> str:
    roll = rng.random()
    cumulative = 0.0
    for name, prob in zip(names, probs):
        cumulative += prob
        if roll <= cumulative:
            return name
    return names[-1]


def _operator_learning_reward(
    old_Z: float,
    new_Z: float,
    accepted: bool,
    wsf_tolerance_accept: bool,
) -> float:
    """Score one operator attempt for ALNS-style weight learning."""
    if not accepted:
        return 0.20
    if wsf_tolerance_accept:
        return 2.00
    delta = max(0.0, old_Z - new_Z)
    relative_gain = delta / max(1.0, abs(old_Z))
    return 3.00 + min(4.00, 80.0 * relative_gain)


def _update_operator_weight(
    weights: dict[str, float],
    name: str,
    reward: float,
    reaction_factor: float,
    min_weight: float,
    max_weight: float,
) -> None:
    """Exponential moving-average update for one learned operator weight."""
    old_weight = weights.get(name, 1.0)
    target = min(max_weight, max(min_weight, reward))
    weights[name] = (1.0 - reaction_factor) * old_weight + reaction_factor * target


def _event_search_budget(
    base_lns_iterations: int,
    base_local_search_iters: int,
    rg_intensity: float,
    projected_wsf: float,
    mandatory_count: int,
) -> dict[str, int | str]:
    """Scale search effort down on low-risk events."""
    if projected_wsf > EPS or mandatory_count > 0 or rg_intensity >= 0.50:
        return {
            "risk_level": "high",
            "lns_iterations": base_lns_iterations,
            "local_search_iters": base_local_search_iters,
        }
    if rg_intensity > 0.0:
        return {
            "risk_level": "medium",
            "lns_iterations": max(3, min(base_lns_iterations, ceil(base_lns_iterations * 0.50))),
            "local_search_iters": max(5, min(base_local_search_iters, ceil(base_local_search_iters * 0.50))),
        }
    return {
        "risk_level": "low",
        "lns_iterations": max(1, min(base_lns_iterations, ceil(base_lns_iterations * 0.25))),
        "local_search_iters": max(3, min(base_local_search_iters, ceil(base_local_search_iters * 0.25))),
    }


def _should_run_exact_local_repair(
    use_exact_local_repair: bool,
    projected_wsf: float,
    mandatory_count: int,
    rg_intensity: float,
    no_improve: int,
) -> bool:
    """Gate bounded CP-SAT local repair to service-risk events."""
    if not use_exact_local_repair:
        return False
    return (
        projected_wsf > EPS
        or mandatory_count > 0
        or rg_intensity >= 0.50
        or (rg_intensity > 0.0 and no_improve > 0)
    )


# ── Adaptive RG: Entity Classification & Intensity ──────────────────────────

def _classify_entities_and_intensity(
    instance: SLISPInstance,
    state: ScheduleState,
    pool_B: set[int],
) -> tuple[list[dict], float]:
    """Classify each entity by recoverability and compute overall RG intensity.

    Returns (entity_classifications, rg_intensity) where rg_intensity ∈ [0, 1].
    """
    classifications = []
    intensities = []

    for entity in instance.entities:
        eid = entity.entity_id
        q_rem = remaining_service_quantity(eid, state, instance)

        if q_rem <= 0:
            classifications.append({"entity_id": eid, "class": "secured", "q_rem": q_rem})
            intensities.append(0.0)
            continue

        q_rec, _ = maximum_recoverable_service_quantity(eid, pool_B, state, instance, method="dp")
        q_future = known_future_quantity(eid, instance)
        q_available = q_rec + q_future
        u_lb = current_information_shortfall_risk(
            eid, pool_B, state, instance, method="dp"
        )
        s_rec = q_available - q_rem  # recovery surplus including hidden aggregate quantity

        if u_lb > 0 or q_available < q_rem:
            # Partially unrecoverable: recovery is structurally impossible
            # Low RG intensity — don't over-invest in impossible recovery
            classifications.append({
                "entity_id": eid, "class": "partially_unrecoverable",
                "q_rem": q_rem, "q_rec": q_rec, "q_future": q_future,
                "u_lb": u_lb, "s_rec": s_rec,
            })
            intensities.append(0.2)
        elif q_rec < q_rem and q_future > 0:
            # The current visible pool is insufficient, but known future
            # aggregate quantity can still satisfy the remaining commitment.
            classifications.append({
                "entity_id": eid, "class": "arrival_dependent_recoverable",
                "q_rem": q_rem, "q_rec": q_rec, "q_future": q_future,
                "u_lb": u_lb, "s_rec": s_rec,
            })
            intensities.append(0.4)
        elif q_available >= q_rem * 1.5 and s_rec > q_rem * 0.3:
            # Stable-recoverable: large surplus, recovery is easy
            classifications.append({
                "entity_id": eid, "class": "stable_recoverable",
                "q_rem": q_rem, "q_rec": q_rec, "q_future": q_future,
                "u_lb": u_lb, "s_rec": s_rec,
            })
            intensities.append(0.2)
        elif s_rec > 0:
            # Fragile-recoverable: small surplus, RG guidance is most valuable here
            classifications.append({
                "entity_id": eid, "class": "fragile_recoverable",
                "q_rem": q_rem, "q_rec": q_rec, "q_future": q_future,
                "u_lb": u_lb, "s_rec": s_rec,
            })
            intensities.append(0.6)
        else:
            # Secured: no remaining quantity needed
            classifications.append({
                "entity_id": eid, "class": "secured",
                "q_rem": q_rem, "q_rec": q_rec, "q_future": q_future,
                "u_lb": u_lb, "s_rec": s_rec,
            })
            intensities.append(0.0)

    # Overall intensity: max across entities (most urgent entity drives RG)
    rg_intensity = max(intensities) if intensities else 0.0
    return classifications, rg_intensity


# ── RG Priority Score ───────────────────────────────────────────────────────

def _compute_rg_scores(
    instance: SLISPInstance,
    state: ScheduleState,
    pool_B: set[int],
    a1: float = 0.3, a2: float = 0.3, a3: float = 0.3, a4: float = 0.1, a5: float = 0.0,
    a6: float = 0.0, a7: float = 0.0,
) -> dict[int, float]:
    """Compute RG priority score for each candidate job.

    a1: tardiness urgency, a2: service pressure, a3: mandatory rescue,
    a4: marginal recovery, a5: processing burden,
    a6: SPT efficiency (inverse processing time), a7: WSPT efficiency (weight/pt ratio).
    """
    scores: dict[int, float] = {}

    # Precompute entity-level metrics
    entity_shortfall: dict[int, float] = {}
    entity_mandatory: dict[int, set[int]] = {}
    entity_quota_pressure: dict[int, float] = {}
    entity_cover: dict[int, set[int]] = {}
    for entity in instance.entities:
        eid = entity.entity_id
        q_rem = remaining_service_quantity(eid, state, instance)
        mand = set(mandatory_rescue_jobs(eid, pool_B, state, instance, method="dp"))
        entity_mandatory[eid] = mand
        entity_quota_pressure[eid] = _entity_quota_pressure(instance, state, eid)
        entity_cover[eid] = _minimum_work_service_cover(instance, state, eid)
        if q_rem > 0:
            entity_shortfall[eid] = current_information_shortfall_risk(
                eid, pool_B, state, instance, method="dp"
            )
        else:
            entity_shortfall[eid] = 0

    max_shortfall = max(entity_shortfall.values()) if entity_shortfall else 1
    max_proc = 1
    min_proc = 10**9
    for job in instance.jobs:
        total_pt = sum(op.min_processing_time for op in job.operations)
        max_proc = max(max_proc, total_pt)
        min_proc = min(min_proc, total_pt)

    for job in instance.jobs:
        if state.is_job_completed(job.job_id):
            continue
        entity = instance.get_entity(job.entity_id)
        eid = entity.entity_id

        # a1: tardiness urgency
        d_lower = optimistic_delivery_lower_bound(job, state, instance)
        tardiness_urgency = 1.0 / max(TIME_DENOM_EPS, entity.deadline - d_lower + 1)

        # a2: service pressure.  A positive unavoidable shortfall is severe,
        # but a high quota/eligible-quantity ratio is also fragile before the
        # shortfall becomes unavoidable.
        sf = entity_shortfall.get(eid, 0)
        hard_pressure = sf / max(1, max_shortfall)
        cover_flag = 1.0 if job.job_id in entity_cover.get(eid, set()) else 0.0
        quota_pressure = entity_quota_pressure.get(eid, 0.0) * entity.weight * cover_flag
        service_pressure = max(hard_pressure, quota_pressure)

        # a3: mandatory rescue
        mandatory_flag = 1.0 if job.job_id in entity_mandatory.get(eid, set()) else 0.0

        # a4: marginal recovery
        q_rem = remaining_service_quantity(eid, state, instance)
        quota_marginal_qty = _quota_marginal_service_quantity(
            instance, state, pool_B, job
        )
        marginal = quota_marginal_qty / max(1.0, q_rem) if q_rem > 0 else 0.0

        # a5: processing burden (normalized, lower is better → subtract)
        total_pt = sum(op.min_processing_time for op in job.operations)
        proc_burden = total_pt / max(1, max_proc)

        # a6: SPT efficiency (inverse normalized proc time, higher for short jobs)
        spt_signal = 1.0 - (total_pt - min_proc) / max(1, max_proc - min_proc) if max_proc > min_proc else 0.5

        # a7: service efficiency (weighted quantity per unit remaining work)
        w = entity.weight if entity.weight > 0 else 1.0
        wspt_raw = w * quota_marginal_qty / max(1, total_pt)
        wspt_signal = wspt_raw  # raw ratio, will be added positively

        scores[job.job_id] = (
            a1 * tardiness_urgency
            + a2 * service_pressure
            + a3 * mandatory_flag
            + a4 * marginal
            - a5 * proc_burden
            + a6 * spt_signal
            + a7 * wspt_signal
        )

    return scores


# ── Greedy construction ─────────────────────────────────────────────────────

def _greedy_construct_sgs(
    instance: SLISPInstance,
    state: ScheduleState,
    job_ids: list[int],
    scores: dict[int, float],
) -> FastSchedule:
    """Release-aware serial/parallel schedule generation for RHO projection."""
    sched = FastSchedule()
    for m in instance.machines:
        sched.machine_slots[m.machine_id] = []
    for (jid, oid), sop in state.ongoing_operations.items():
        sched.add_op(jid, oid, sop.machine_id, sop.start_time, sop.end_time)

    priority_rank = {jid: pos for pos, jid in enumerate(job_ids)}
    candidate_set = set(job_ids)
    next_seq: dict[int, int] = {}
    job_ready: dict[int, int] = {}
    machine_ready: dict[int, int] = {
        m.machine_id: max(state.current_time, state.machine_available_times.get(m.machine_id, 0))
        for m in instance.machines
    }

    for job_id in candidate_set:
        job = instance.get_job(job_id)
        if state.is_job_completed(job_id):
            continue
        seq = state.next_op_index_for_job(job_id)
        ready_time = max(state.current_time, job.release_time)
        while seq < job.num_operations:
            op = job.operation_at(seq)
            if state.is_operation_completed(job_id, op.op_id):
                seq += 1
                continue
            if state.is_operation_ongoing(job_id, op.op_id):
                ongoing = state.ongoing_operations[(job_id, op.op_id)]
                ready_time = max(ready_time, ongoing.end_time)
                seq += 1
                continue
            break
        if seq < job.num_operations:
            next_seq[job_id] = seq
            job_ready[job_id] = ready_time

    t = state.current_time
    max_steps = max(1, sum(instance.get_job(jid).num_operations for jid in candidate_set) * 3)
    steps = 0

    while next_seq and steps < max_steps:
        steps += 1
        assigned_this_time: set[int] = set()
        scheduled_any = False
        idle_machines = [
            m.machine_id for m in instance.machines
            if machine_ready.get(m.machine_id, state.current_time) <= t
        ]

        for m_id in idle_machines:
            ready_ops = []
            for jid, seq in next_seq.items():
                if jid in assigned_this_time:
                    continue
                if job_ready.get(jid, state.current_time) > t:
                    continue
                job = instance.get_job(jid)
                op = job.operation_at(seq)
                try:
                    pt = op.processing_time_on(m_id)
                except KeyError:
                    continue
                rank = priority_rank.get(jid, len(priority_rank))
                score = scores.get(jid, 0.0)
                score_shift = score * max(1, len(priority_rank)) * 0.15
                ready_ops.append((
                    rank - score_shift,
                    _effective_deadline(instance, job),
                    pt,
                    jid,
                    op,
                ))

            if not ready_ops:
                continue

            _priority, _deadline, pt, jid, op = min(ready_ops)
            start = max(
                t,
                job_ready[jid],
                machine_ready.get(m_id, state.current_time),
                sched.earliest_machine_time(m_id, t, pt),
            )
            if start > t:
                continue
            end = start + pt
            sched.add_op(jid, op.op_id, m_id, start, end)
            machine_ready[m_id] = end
            job_ready[jid] = end
            assigned_this_time.add(jid)
            scheduled_any = True

            seq = next_seq[jid] + 1
            if seq >= instance.get_job(jid).num_operations:
                del next_seq[jid]
                del job_ready[jid]
            else:
                next_seq[jid] = seq

        if scheduled_any:
            continue

        next_times = [
            tm for tm in list(job_ready.values()) + list(machine_ready.values())
            if tm > t
        ]
        if not next_times:
            break
        t = min(next_times)

    return sched


def _greedy_construct(
    instance: SLISPInstance,
    state: ScheduleState,
    job_ids: list[int],
    scores: dict[int, float],
    rng,
) -> FastSchedule:
    """Compatibility wrapper for the release-aware SGS constructor."""
    return _greedy_construct_sgs(instance, state, job_ids, scores)


def _extract_immediate_decisions(
    sched: FastSchedule,
    instance: SLISPInstance,
    state: ScheduleState,
    dispatch_mode: str = "standard_projected",
    # ── service_aware mode params (configurable) ──
    quota_pressure_rescue_threshold: float = 0.75,
    service_gain_delay_ratio: float = 1.5,
    cover_bonus_weight: float = 0.25,
    mandatory_bonus_weight: float = 0.50,
) -> list[tuple[int, int, int, int]]:
    """Return only decisions that are valid in the current simulator state.

    Supports three dispatch modes:
      - "standard_projected": projected schedule dominates; fair baseline dispatch.
      - "service_aware": RG-based rescue ranking; proposed-method enhanced dispatch.
      - "replay_plan": exact projected plan replay at current time (diagnostic only).
    """
    if dispatch_mode == "replay_plan":
        return _extract_replay_plan_decisions(sched, instance, state)

    service_aware = (dispatch_mode == "service_aware")

    t_now = state.current_time
    projected_start = {
        (job_id, op_id): start
        for job_id, ops in sched.assignments.items()
        for op_id, _machine_id, start in ops
    }
    projected_machine = {
        (job_id, op_id): machine_id
        for job_id, ops in sched.assignments.items()
        for op_id, machine_id, _start in ops
    }
    immediate: list[tuple[int, int, int, int]] = []
    assigned_ops: set[tuple[int, int]] = set()
    assigned_machines: set[int] = set()

    # ── Service context (used by both modes as light tie-breaker) ──
    machine_pool = {machine.machine_id for machine in instance.machines}
    cover_jobs: set[int] = set()
    mandatory_jobs: set[int] = set()
    quota_pressure: dict[int, float] = {}
    for entity in instance.entities:
        quota_pressure[entity.entity_id] = _entity_quota_pressure(instance, state, entity.entity_id)
        cover_jobs.update(_minimum_work_service_cover(instance, state, entity.entity_id))
        mandatory_jobs.update(
            mandatory_rescue_jobs(entity.entity_id, machine_pool, state, instance, method="dp")
        )

    # ── service_aware additional context ──
    quota_marginal_qty_cache: dict[int, float] = {}
    if service_aware:
        service_risk_active = _fast_eval_wsf(sched, instance, state) > EPS
        for entity in instance.entities:
            if unavoidable_shortfall_lower_bound(
                entity.entity_id, machine_pool, state, instance, method="dp"
            ) > EPS:
                service_risk_active = True
    else:
        service_risk_active = False

    def is_ready_on_machine(job: Job, op: Operation, machine_id: int) -> int | None:
        if state.is_job_completed(job.job_id):
            return None
        if job.release_time > t_now:
            return None
        if state.is_operation_completed(job.job_id, op.op_id):
            return None
        if state.is_operation_ongoing(job.job_id, op.op_id):
            return None
        if op.sequence_index != state.next_op_index_for_job(job.job_id):
            return None
        if not state.is_machine_idle(machine_id):
            return None
        try:
            return op.processing_time_on(machine_id)
        except KeyError:
            return None

    def dispatch_key_standard(
        job: Job, op: Operation, machine_id: int, pt: int, _best_ready_pt: int
    ) -> tuple:
        """Projected-schedule-dominant key for fair baseline comparison."""
        entity = instance.get_entity(job.entity_id)
        p_start = projected_start.get((job.job_id, op.op_id), 10**12)
        p_machine = projected_machine.get((job.job_id, op.op_id))
        projection_arrived = 0 if p_start <= t_now else 1
        projected_machine_penalty = 0 if p_machine == machine_id else 1
        effective_due = _effective_deadline(instance, job)
        # Light service tie-breaker (does not override projected order)
        w = entity.weight if entity.weight > 0 else 1.0
        cover_flag = 1 if job.job_id in cover_jobs else 0
        mandatory_flag = 1 if job.job_id in mandatory_jobs else 0
        qty = _useful_service_quantity(instance, state, job)
        service_tie = -(
            cover_bonus_weight * w * qty * cover_flag
            + mandatory_bonus_weight * w * qty * mandatory_flag
        )
        return (
            projection_arrived,        # 0=in projected plan at t, 1=not → primary
            p_start,                   # earlier projected start first
            projected_machine_penalty, # prefer projected machine
            effective_due,             # fallback: EDD
            pt,                        # fallback: SPT
            service_tie,               # fallback: service contribution
            job.job_id,                # deterministic tie-break
            op.op_id,
        )

    def dispatch_key_service_aware(
        job: Job, op: Operation, machine_id: int, pt: int, best_ready_pt: int
    ) -> tuple:
        """RG-based rescue ranking for proposed-method enhanced dispatch."""
        entity = instance.get_entity(job.entity_id)
        p_start = projected_start.get((job.job_id, op.op_id), 10**12)
        p_machine = projected_machine.get((job.job_id, op.op_id))
        projected_machine_penalty = 0 if p_machine == machine_id else 1
        effective_due = _effective_deadline(instance, job)
        projection_arrived = 0 if p_start <= t_now else 1
        tardiness_gain = _tardiness_opportunity_gain(
            instance, state, job, op, pt, delay_duration=best_ready_pt,
        )

        if not service_risk_active:
            return (
                projection_arrived,
                p_start,
                projected_machine_penalty,
                -tardiness_gain,
                effective_due,
                pt,
                job.job_id,
                op.op_id,
            )

        cover_flag = 1 if job.job_id in cover_jobs else 0
        mandatory_flag = 1 if job.job_id in mandatory_jobs else 0
        remaining_work = max(1, _remaining_job_work(job, state))
        current_op_optimistic = optimistic_remaining_operation_time(op, job, state)
        remaining_after_current = max(0, remaining_work - current_op_optimistic)
        completion_if_now = t_now + pt + remaining_after_current
        completion_if_delayed_once = t_now + best_ready_pt + pt + remaining_after_current

        if job.job_id not in quota_marginal_qty_cache:
            quota_marginal_qty_cache[job.job_id] = (
                _quota_marginal_service_quantity(instance, state, machine_pool, job)
            )
        service_qty = quota_marginal_qty_cache[job.job_id]
        service_gain = instance.beta * entity.weight * service_qty
        delay_cost = instance.alpha * max(0, pt - best_ready_pt)
        immediately_at_risk = (
            completion_if_now <= effective_due
            and completion_if_delayed_once > effective_due
        )
        rescue_surplus = service_gain - delay_cost
        rescue_rank = 0 if (
            immediately_at_risk
            and (mandatory_flag or cover_flag or quota_pressure.get(job.entity_id, 0.0) >= quota_pressure_rescue_threshold)
            and service_gain > service_gain_delay_ratio * delay_cost + EPS
        ) else 1
        service_tie_break = -(
            cover_bonus_weight * service_gain * cover_flag
            + mandatory_bonus_weight * service_gain * mandatory_flag
        )
        return (
            rescue_rank,
            -rescue_surplus if rescue_rank == 0 else 0.0,
            -tardiness_gain,
            effective_due,
            pt,
            service_tie_break,
            projection_arrived,
            p_start,
            projected_machine_penalty,
            job.job_id,
            op.op_id,
        )

    dispatch_key = dispatch_key_service_aware if service_aware else dispatch_key_standard

    # ── Dispatch one operation per idle machine ──
    for machine in instance.machines:
        m_id = machine.machine_id
        if m_id in assigned_machines or not state.is_machine_idle(m_id):
            continue
        ready_for_machine: list[tuple[Job, Operation, int]] = []
        for job in instance.jobs:
            if state.is_job_completed(job.job_id) or job.release_time > t_now:
                continue
            next_idx = state.next_op_index_for_job(job.job_id)
            if next_idx >= job.num_operations:
                continue
            op = job.operation_at(next_idx)
            if (job.job_id, op.op_id) in assigned_ops:
                continue
            pt = is_ready_on_machine(job, op, m_id)
            if pt is None:
                continue
            ready_for_machine.append((job, op, pt))
        if not ready_for_machine:
            continue
        best_ready_pt = min(pt for _job, _op, pt in ready_for_machine)
        candidates = [
            (dispatch_key(job, op, m_id, pt, best_ready_pt), job.job_id, op.op_id)
            for job, op, pt in ready_for_machine
        ]
        if not candidates:
            continue
        _key, job_id, op_id = min(candidates, key=lambda item: item[0])
        immediate.append((job_id, op_id, m_id, t_now))
        assigned_ops.add((job_id, op_id))
        assigned_machines.add(m_id)

    return immediate


def _extract_replay_plan_decisions(
    sched: FastSchedule,
    instance: SLISPInstance,
    state: ScheduleState,
) -> list[tuple[int, int, int, int]]:
    """Replay a pre-evaluated rollout plan at the current simulator time."""
    t_now = state.current_time
    decisions: list[tuple[int, int, int, int]] = []
    assigned_ops: set[tuple[int, int]] = set()
    assigned_machines: set[int] = set()

    for job_id, op_id, machine_id, start in sorted(
        sched.to_decisions(), key=lambda d: (d[3], d[2], d[0], d[1])
    ):
        if start > t_now:
            continue
        if (job_id, op_id) in assigned_ops or machine_id in assigned_machines:
            continue
        job = instance.get_job(job_id)
        if state.is_job_completed(job_id) or job.release_time > t_now:
            continue
        next_idx = state.next_op_index_for_job(job_id)
        if next_idx >= job.num_operations:
            continue
        op = job.operation_at(next_idx)
        if op.op_id != op_id:
            continue
        if state.is_operation_completed(job_id, op_id) or state.is_operation_ongoing(job_id, op_id):
            continue
        if not state.is_machine_idle(machine_id):
            continue
        try:
            op.processing_time_on(machine_id)
        except KeyError:
            continue
        decisions.append((job_id, op_id, machine_id, t_now))
        assigned_ops.add((job_id, op_id))
        assigned_machines.add(machine_id)

    return decisions


def _rollout_dispatch_by_key(
    instance: SLISPInstance,
    state: ScheduleState,
    key_fn,
) -> list[tuple[int, int, int, int]]:
    """Local dispatch helper used by the no-regret rollout portfolio."""
    ready: list[tuple[Job, Operation]] = []
    for job in instance.jobs:
        if state.is_job_completed(job.job_id) or job.release_time > state.current_time:
            continue
        next_idx = state.next_op_index_for_job(job.job_id)
        if next_idx >= job.num_operations:
            continue
        op = job.operation_at(next_idx)
        if state.is_operation_completed(job.job_id, op.op_id):
            continue
        if state.is_operation_ongoing(job.job_id, op.op_id):
            continue
        ready.append((job, op))

    decisions: list[tuple[int, int, int, int]] = []
    assigned_ops: set[tuple[int, int]] = set()
    for machine in instance.machines:
        m_id = machine.machine_id
        if not state.is_machine_idle(m_id):
            continue
        candidates = []
        for job, op in ready:
            if (job.job_id, op.op_id) in assigned_ops:
                continue
            try:
                pt = op.processing_time_on(m_id)
            except KeyError:
                continue
            candidates.append((key_fn(job, op, m_id, pt), job, op))
        if not candidates:
            continue
        _key, job, op = min(candidates, key=lambda item: item[0])
        decisions.append((job.job_id, op.op_id, m_id, state.current_time))
        assigned_ops.add((job.job_id, op.op_id))
    return decisions


def _rollout_edd_rule(
    instance: SLISPInstance, state: ScheduleState
) -> list[tuple[int, int, int, int]]:
    return _rollout_dispatch_by_key(
        instance,
        state,
        lambda job, _op, _mid, pt: (_effective_deadline(instance, job), pt),
    )


def _insert_job_greedy(
    instance: SLISPInstance,
    job: Job,
    sched: FastSchedule,
    state: ScheduleState,
) -> None:
    """Insert all operations of a job greedily — each op at earliest feasible position."""
    prev_end = max(state.current_time, job.release_time)

    for op in job.operations:
        if state.is_operation_completed(job.job_id, op.op_id):
            continue
        if state.is_operation_ongoing(job.job_id, op.op_id):
            prev_end = state.ongoing_operations[(job.job_id, op.op_id)].end_time
            continue

        best_m = None
        best_start = 10**9
        best_end = 10**9

        for alt in op.alternatives:
            m_id = alt.machine_id
            pt = alt.processing_time
            state_avail = state.machine_available_times.get(m_id, 0)
            earliest = max(prev_end, state_avail, sched.earliest_machine_time(m_id, prev_end, pt))
            end_t = earliest + pt
            if end_t < best_end:
                best_end = end_t
                best_start = earliest
                best_m = m_id

        if best_m is not None:
            sched.add_op(job.job_id, op.op_id, best_m, best_start, best_end)
            prev_end = best_end


def _job_has_ongoing_operation(job_id: int, state: ScheduleState) -> bool:
    return any(jid == job_id for jid, _op_id in state.ongoing_operations)


def _job_schedule_span(sched: FastSchedule, job_id: int) -> tuple[int, int] | None:
    starts: list[int] = []
    ends: list[int] = []
    for machine_slots in sched.machine_slots.values():
        for jid, _op_id, start, end in machine_slots:
            if jid == job_id:
                starts.append(start)
                ends.append(end)
    if not starts:
        return None
    return min(starts), max(ends)


def _job_schedule_slots(
    sched: FastSchedule,
    job_id: int,
) -> list[tuple[int, int, int, int]]:
    """Return projected slots for one job as (machine, op, start, end)."""
    result: list[tuple[int, int, int, int]] = []
    for machine_id, slots in sched.machine_slots.items():
        for jid, op_id, start, end in slots:
            if jid == job_id:
                result.append((machine_id, op_id, start, end))
    result.sort(key=lambda item: (item[2], item[0], item[1]))
    return result


def _add_if_repair_eligible(
    scores: dict[int, float],
    jid: int,
    score: float,
    eligible_set: set[int],
    active_set: set[int],
) -> None:
    if jid in active_set or jid not in eligible_set:
        return
    scores[jid] = scores.get(jid, 0.0) + score


def _blocker_candidate_scores(
    instance: SLISPInstance,
    state: ScheduleState,
    sched: FastSchedule,
    active_jobs: list[int],
    eligible_set: set[int],
    rg_scores: dict[int, float],
) -> dict[int, float]:
    """Score jobs that block or neighbor the current exact-repair seeds."""
    active_set = set(active_jobs)
    blocker_scores: dict[int, float] = {}

    for active_jid in active_jobs:
        active_job = instance.get_job(active_jid)
        active_completion = _projected_completion_time(active_job, sched, instance, state)
        lateness = max(0, active_completion - _effective_deadline(instance, active_job))
        neighbor_depth = 2 if lateness > 0 else 1
        span = _job_schedule_span(sched, active_jid)
        if span is None:
            continue
        span_start, span_end = span
        window_pad = max(4, int(lateness))
        window_start = max(state.current_time, span_start - window_pad)
        window_end = span_end + max(3, window_pad // 2)

        for machine_id, slots in sched.machine_slots.items():
            ordered = sorted(slots, key=lambda item: (item[2], item[3], item[0], item[1]))
            active_indices = [
                idx for idx, (jid, _op_id, _start, _end) in enumerate(ordered)
                if jid == active_jid
            ]
            for idx in active_indices:
                for n_idx in range(
                    max(0, idx - neighbor_depth),
                    min(len(ordered), idx + 2),
                ):
                    if n_idx == idx:
                        continue
                    bjid, _bop, _bs, _be = ordered[n_idx]
                    proximity = 1.0 / (1.0 + abs(n_idx - idx))
                    _add_if_repair_eligible(
                        blocker_scores,
                        bjid,
                        5.0 * proximity + 0.20 * lateness + rg_scores.get(bjid, 0.0),
                        eligible_set,
                        active_set,
                    )

            for bjid, _bop, start, end in ordered:
                if bjid in active_set:
                    continue
                overlap = max(0, min(end, window_end) - max(start, window_start))
                if overlap <= 0:
                    continue
                distance = min(abs(end - span_start), abs(start - span_end))
                _add_if_repair_eligible(
                    blocker_scores,
                    bjid,
                    overlap + 1.0 / (1.0 + distance) + 0.10 * lateness
                    + rg_scores.get(bjid, 0.0),
                    eligible_set,
                    active_set,
                )

    return blocker_scores


def _select_exact_repair_jobs(
    instance: SLISPInstance,
    state: ScheduleState,
    sched: FastSchedule,
    candidates: list[int],
    scores: dict[int, float],
    max_jobs: int,
) -> list[int]:
    """Select a small repair neighborhood from service-cover and conflict signals."""
    if max_jobs <= 0:
        return []

    eligible = [
        jid for jid in candidates
        if jid in sched.assignments
        and not state.is_job_completed(jid)
        and not _job_has_ongoing_operation(jid, state)
        and state.next_op_index_for_job(jid) < instance.get_job(jid).num_operations
    ]
    if not eligible:
        return []
    eligible_set = set(eligible)

    cover_jobs: set[int] = set()
    mandatory_jobs: set[int] = set()
    quota_pressure: dict[int, float] = {}
    machine_pool = {machine.machine_id for machine in instance.machines}
    for entity in instance.entities:
        eid = entity.entity_id
        quota_pressure[eid] = _entity_quota_pressure(instance, state, eid)
        cover_jobs.update(_minimum_work_service_cover(instance, state, eid))
        mandatory_jobs.update(
            mandatory_rescue_jobs(eid, machine_pool, state, instance, method="dp")
        )

    ranked: list[tuple[float, int]] = []
    for jid in eligible:
        job = instance.get_job(jid)
        entity = instance.get_entity(job.entity_id)
        completion = _projected_completion_time(job, sched, instance, state)
        tardiness = max(0, completion + entity.transport_delay - entity.deadline)
        slack = entity.deadline - entity.transport_delay - completion
        total_work = max(1, _remaining_job_work(job, state))
        useful_qty = _useful_service_quantity(instance, state, job)
        service_efficiency = entity.weight * useful_qty / total_work
        service_signal = quota_pressure.get(job.entity_id, 0.0) * entity.weight
        priority = (
            4.0 * (1.0 if jid in mandatory_jobs else 0.0)
            + 3.0 * (1.0 if jid in cover_jobs else 0.0)
            + 1.5 * service_signal
            + 0.20 * tardiness
            + 0.10 * max(0, -slack)
            + service_efficiency
            + scores.get(jid, 0.0)
        )
        ranked.append((priority, jid))

    ranked.sort(reverse=True)
    active: list[int] = []
    active_set: set[int] = set()
    if max_jobs <= 3:
        seed_limit = max(1, (max_jobs + 1) // 2)
    else:
        seed_limit = max(2, min(max_jobs, ceil(max_jobs * 0.70)))
    for priority, jid in ranked:
        if priority <= 0 and active:
            break
        active.append(jid)
        active_set.add(jid)
        if len(active) >= seed_limit:
            break

    if not active:
        return []

    blocker_scores = _blocker_candidate_scores(
        instance,
        state,
        sched,
        active,
        eligible_set,
        scores,
    )
    for jid, _score in sorted(blocker_scores.items(), key=lambda item: -item[1]):
        if len(active) >= max_jobs:
            break
        if jid in active_set:
            continue
        active.append(jid)
        active_set.add(jid)

    conflict_scores: dict[int, float] = {}
    active_spans = [
        span for jid in active
        if (span := _job_schedule_span(sched, jid)) is not None
    ]
    if active_spans:
        window_start = min(start for start, _end in active_spans) - 5
        window_end = max(end for _start, end in active_spans) + 5
        for machine_slots in sched.machine_slots.values():
            for jid, _op_id, start, end in machine_slots:
                if jid in active_set or jid not in eligible:
                    continue
                overlap = max(0, min(end, window_end) - max(start, window_start))
                if overlap <= 0:
                    continue
                job = instance.get_job(jid)
                conflict_scores[jid] = conflict_scores.get(jid, 0.0) + overlap + scores.get(jid, 0.0)

    for jid, _score in sorted(conflict_scores.items(), key=lambda item: -item[1]):
        if len(active) >= max_jobs:
            break
        active.append(jid)
        active_set.add(jid)

    if len(active) < max_jobs:
        for _priority, jid in ranked:
            if len(active) >= max_jobs:
                break
            if jid in active_set:
                continue
            active.append(jid)
            active_set.add(jid)

    return active


def _apply_exact_local_repair(
    instance: SLISPInstance,
    state: ScheduleState,
    sched: FastSchedule,
    current_Z: float,
    candidates: list[int],
    scores: dict[int, float],
    max_jobs: int = 8,
    time_limit_s: float = 1.0,
) -> tuple[FastSchedule, float, dict]:
    """Run one recoverability-guided exact local repair and accept improvements."""
    active_jobs = _select_exact_repair_jobs(
        instance, state, sched, candidates, scores, max_jobs=max_jobs
    )
    info = {
        "attempted": bool(active_jobs),
        "accepted": False,
        "active_jobs": active_jobs,
        "status": "SKIPPED" if not active_jobs else None,
        "old_Z": current_Z,
        "new_Z": current_Z,
        "runtime_ms": 0.0,
    }
    if not active_jobs:
        return sched, current_Z, info

    active_set = set(active_jobs)
    fixed_machine_slots: dict[int, list[tuple[int, int, int, int]]] = {
        machine.machine_id: [] for machine in instance.machines
    }
    for machine_id, slots in sched.machine_slots.items():
        fixed_machine_slots.setdefault(machine_id, [])
        for jid, op_id, start, end in slots:
            if jid not in active_set:
                fixed_machine_slots[machine_id].append((jid, op_id, start, end))

    fixed_completion_times = _projected_job_completions(sched, instance, state)
    for jid in active_set:
        fixed_completion_times.pop(jid, None)

    try:
        from ..solvers.exact_local_repair_cp_sat import solve_exact_local_repair_cp_sat
    except Exception as exc:
        info["status"] = f"IMPORT_FAILED: {exc.__class__.__name__}"
        return sched, current_Z, info

    result = solve_exact_local_repair_cp_sat(
        instance,
        state,
        active_set,
        fixed_machine_slots=fixed_machine_slots,
        fixed_completion_times=fixed_completion_times,
        time_limit_s=time_limit_s,
        num_workers=1,
    )
    info["status"] = result.status
    info["runtime_ms"] = result.wall_time_s * 1000
    if result.status not in {"OPTIMAL", "FEASIBLE"} or not result.scheduled_operations:
        return sched, current_Z, info

    repaired = sched.clone()
    for jid in active_set:
        repaired.remove_job(jid)
    for sop in result.scheduled_operations:
        repaired.add_op(
            sop.job_id,
            sop.op_id,
            sop.machine_id,
            sop.start_time,
            sop.end_time,
        )

    new_Z = _fast_eval_Z(repaired, instance, state)
    info["new_Z"] = new_Z
    if new_Z < current_Z - EPS:
        info["accepted"] = True
        return repaired, new_Z, info
    return sched, current_Z, info


# ── Hybrid Priority Score ──────────────────────────────────────────────────

def _compute_hybrid_scores(
    instance: SLISPInstance,
    state: ScheduleState,
    candidates: list[int],
    w_spt: float = 0.50,
    w_due: float = 0.20,
    w_wspt: float = 0.15,
    w_rg: float = 0.10,
    w_marginal: float = 0.05,
    rg_scores: dict[int, float] | None = None,
) -> dict[int, float]:
    """SPT-dominant hybrid priority score for construction ordering."""
    scores: dict[int, float] = {}
    max_proc = max((sum(op.min_processing_time for op in instance.get_job(jid).operations)
                     for jid in candidates), default=1)
    min_proc = min((sum(op.min_processing_time for op in instance.get_job(jid).operations)
                     for jid in candidates), default=1)
    proc_range = max(1, max_proc - min_proc)

    for jid in candidates:
        job = instance.get_job(jid)
        entity = instance.get_entity(job.entity_id)
        total_pt = sum(op.min_processing_time for op in job.operations)
        w = entity.weight if entity.weight > 0 else 1.0

        # SPT: normalized inverse processing time
        spt_score = 1.0 - (total_pt - min_proc) / proc_range if proc_range > 0 else 0.5

        # Due-date urgency
        d_eff = entity.deadline - entity.transport_delay
        due_urgency = 1.0 / max(1, d_eff - state.current_time + 1)

        # WSPT: weight / processing time
        useful_qty = _useful_service_quantity(instance, state, job)
        wspt_score = w * useful_qty / max(1, total_pt)

        # RG recoverability risk
        rg_risk = rg_scores.get(jid, 0.0) if rg_scores else 0.0

        # Marginal recovery uses only quantity that can still reduce shortfall.
        q_rem = remaining_service_quantity(entity.entity_id, state, instance)
        marginal = useful_qty / max(1.0, q_rem) if q_rem > 0 else 0.0

        scores[jid] = (
            w_spt * spt_score
            + w_due * due_urgency
            + w_wspt * wspt_score
            + w_rg * rg_risk
            + w_marginal * marginal
        )
    return scores


# ── Regret-k Insertion ─────────────────────────────────────────────────────


# ── Multi-Start Initial Solution ────────────────────────────────────────────

# Construction heuristics (name, ordering function)
def _build_candidate_pool(
    instance: SLISPInstance,
    state: ScheduleState,
    candidates: list[int],
    rg_scores: dict[int, float],
    rng,
) -> list[tuple[str, FastSchedule]]:
    """Generate diverse construction candidates. Returns [(name, schedule), ...]."""
    results: list[tuple[str, FastSchedule]] = []
    orderings: list[tuple[str, list[int]]] = []
    quota_pressure = {
        entity.entity_id: _entity_quota_pressure(instance, state, entity.entity_id)
        for entity in instance.entities
    }
    cover_jobs: set[int] = set()
    for entity in instance.entities:
        cover_jobs.update(_minimum_work_service_cover(instance, state, entity.entity_id))

    # Only fast basic rules + SPT/RG-SPT hybrid candidates (no regret-k)
    # 1. Effective due date (production cutoff = deadline - transport delay)
    orderings.append(("EDD", sorted(candidates, key=lambda jid: _effective_deadline(
        instance, instance.get_job(jid)))))
    # 2. SPT
    orderings.append(("SPT", sorted(candidates, key=lambda jid: sum(
        op.min_processing_time for op in instance.get_job(jid).operations))))
    # 3. ATC
    orderings.append(("ATC", sorted(candidates, key=lambda jid: (
        instance.get_entity(instance.get_job(jid).entity_id).deadline
        - instance.get_entity(instance.get_job(jid).entity_id).transport_delay)
        / max(1, sum(op.min_processing_time for op in instance.get_job(jid).operations)))))
    # 4. RG-priority
    orderings.append(("RG", sorted(candidates, key=lambda jid: -rg_scores.get(jid, 0))))
    # 5. Recovery cover: only the min-work quota cover is promoted strongly.
    orderings.append(("Cover", sorted(candidates, key=lambda jid: (
        0 if jid in cover_jobs else 1,
        -quota_pressure.get(instance.get_job(jid).entity_id, 0.0)
        * instance.get_entity(instance.get_job(jid).entity_id).weight
        * _useful_service_quantity(instance, state, instance.get_job(jid))
        / max(1, sum(op.min_processing_time for op in instance.get_job(jid).operations)),
        _effective_deadline(instance, instance.get_job(jid)),
        sum(op.min_processing_time for op in instance.get_job(jid).operations),
    ))))
    # 6. RG-SPT-H1 (SPT-dominant hybrid)
    hs = _compute_hybrid_scores(instance, state, candidates, 0.50, 0.20, 0.15, 0.10, 0.05, rg_scores)
    orderings.append(("RG-SPT", sorted(candidates, key=lambda jid: -hs.get(jid, 0))))

    # Build schedules from orderings only
    for name, order in orderings:
        sched = _greedy_construct(instance, state, order, rg_scores, rng)
        results.append((name, sched))

    return results


def _initial_local_polish(
    sched: FastSchedule,
    instance: SLISPInstance,
    state: ScheduleState,
    max_moves: int = 30,
    z_tolerance: float = 0.005,
    rng=None,
) -> FastSchedule:
    """Lightweight polishing: adjacent swap, relocate, pull-forward."""
    import random
    if rng is None:
        rng = random.Random(42)
    current_Z = _fast_eval_Z(sched, instance, state)

    for _ in range(max_moves):
        job_ids = [jid for jid in sched.assignments if len(sched.assignments.get(jid, [])) >= 1]
        if len(job_ids) < 2:
            break

        improved = False
        for _attempt in range(5):
            idx = rng.randint(0, 2)
            if idx == 0:
                # Adjacent order swap
                j1 = rng.choice(job_ids)
                j2 = rng.choice(job_ids)
                if j1 == j2:
                    continue
                copy = sched.clone()
                if j1 in copy.assignments and j2 in copy.assignments:
                    copy.remove_job(j1)
                    copy.remove_job(j2)
                    _insert_job_greedy(instance, instance.get_job(j2), copy, state)
                    _insert_job_greedy(instance, instance.get_job(j1), copy, state)
                    nz = _fast_eval_Z(copy, instance, state)
                    if nz < current_Z - EPS:
                        sched = copy; current_Z = nz; improved = True
            elif idx == 1:
                # Relocate one job
                jid = rng.choice(job_ids)
                copy = sched.clone()
                if jid in copy.assignments:
                    copy.remove_job(jid)
                    _insert_job_greedy(instance, instance.get_job(jid), copy, state)
                    nz = _fast_eval_Z(copy, instance, state)
                    if nz < current_Z - EPS:
                        sched = copy; current_Z = nz; improved = True
            else:
                # Pull-forward: reinsert with earlier start
                jid = rng.choice(job_ids)
                if jid not in sched.assignments:
                    continue
                ops = sched.assignments[jid]
                if not ops:
                    continue
                first_op = ops[0]
                # Just do a relocate with slightly earlier priority
                copy = sched.clone()
                if jid in copy.assignments:
                    copy.remove_job(jid)
                    _insert_job_greedy(instance, instance.get_job(jid), copy, state)
                    nz = _fast_eval_Z(copy, instance, state)
                    if nz < current_Z - EPS:
                        sched = copy; current_Z = nz; improved = True

        if not improved:
            break
        if improved:
            # Continue polishing
            continue

    return sched


def _multi_start_initial_solution(
    instance: SLISPInstance,
    state: ScheduleState,
    candidates: list[int],
    rg_scores: dict[int, float],
    rng,
    top_k: int = 2,
    polish_moves: int = 30,
) -> tuple[FastSchedule, float, list[dict]]:
    """Generate candidates, polish, select top-k, return best.

    Returns (best_schedule, best_Z, candidate_diagnostics).
    """
    pool = _build_candidate_pool(instance, state, candidates, rg_scores, rng)

    # Evaluate and polish all candidates
    evaluated: list[tuple[str, FastSchedule, float]] = []
    diag: list[dict] = []

    for name, sched in pool:
        z_before = _fast_eval_Z(sched, instance, state)
        polished = _initial_local_polish(sched, instance, state, polish_moves, 0.005, rng)
        z_after = _fast_eval_Z(polished, instance, state)
        evaluated.append((name, polished, z_after))
        diag.append({
            "candidate": name,
            "Z_before_polish": z_before,
            "Z_after_polish": z_after,
            "polish_improvement": z_before - z_after,
            "selected": False,
            "rank": -1,
        })

    # Sort by Z
    evaluated.sort(key=lambda x: x[2])

    # Select top-k incumbents
    best_sched = None
    best_Z = float('inf')

    for i, (name, sched, z_val) in enumerate(evaluated[:top_k]):
        if z_val < best_Z - EPS:
            best_Z = z_val
            best_sched = sched.clone()
        diag.append({"candidate": name, "Z_before_polish": 0, "Z_after_polish": z_val,
                     "polish_improvement": 0, "selected": True, "rank": i + 1})

    # Also try diverse candidate (best WSF within 2% of best Z)
    best_WSF_sched = None
    best_WSF_Z = float('inf')
    for name, sched, z_val in evaluated:
        if z_val <= best_Z * 1.02:
            wsf_val = _fast_eval_wsf(sched, instance, state)
            if wsf_val < best_WSF_Z - EPS:
                best_WSF_Z = wsf_val
                best_WSF_sched = sched

    if best_WSF_sched is not None:
        wsf_z = _fast_eval_Z(best_WSF_sched, instance, state)
        if wsf_z < best_Z - EPS:
            best_Z = wsf_z
            best_sched = best_WSF_sched.clone()

    return best_sched, best_Z, diag


# ── GA-inspired sequence crossover neighborhood ─────────────────────────────

def _schedule_job_order(
    sched: FastSchedule,
    candidates: list[int],
    instance: SLISPInstance,
) -> list[int]:
    """Extract a job permutation from a schedule by first projected start time."""
    candidate_set = set(candidates)
    ordered: list[tuple[int, int, int]] = []
    seen: set[int] = set()
    for jid, ops in sched.assignments.items():
        if jid not in candidate_set or not ops:
            continue
        first_start = min(start for _op_id, _machine_id, start in ops)
        first_end = min(
            start + instance.get_job(jid).operation_at(0).min_processing_time
            for _op_id, _machine_id, start in ops
        )
        ordered.append((first_start, first_end, jid))
        seen.add(jid)
    ordered.sort(key=lambda item: (item[0], item[1], item[2]))
    result = [jid for _start, _end, jid in ordered]
    result.extend(jid for jid in candidates if jid not in seen)
    return result


def _sequence_crossover_donor_orders(
    instance: SLISPInstance,
    state: ScheduleState,
    candidates: list[int],
    scores: dict[int, float],
) -> list[list[int]]:
    """Build parent orders that encode useful dispatching/RG structures."""
    if not candidates:
        return []

    quota_pressure = {
        entity.entity_id: _entity_quota_pressure(instance, state, entity.entity_id)
        for entity in instance.entities
    }
    cover_jobs: set[int] = set()
    for entity in instance.entities:
        cover_jobs.update(_minimum_work_service_cover(instance, state, entity.entity_id))

    def entity_weight(jid: int) -> float:
        return instance.get_entity(instance.get_job(jid).entity_id).weight

    def effective_due(jid: int) -> int:
        return _effective_deadline(instance, instance.get_job(jid))

    def service_efficiency(jid: int) -> float:
        job = instance.get_job(jid)
        useful_qty = _useful_service_quantity(instance, state, job)
        return entity_weight(jid) * useful_qty / max(1, _job_total_min_work(instance, jid))

    orders = [
        sorted(candidates, key=effective_due),
        sorted(candidates, key=lambda jid: _job_total_min_work(instance, jid)),
        sorted(
            candidates,
            key=lambda jid: (
                _job_total_min_work(instance, jid)
                / max(1e-9, entity_weight(jid))
            ),
        ),
        sorted(candidates, key=lambda jid: -scores.get(jid, 0.0)),
        sorted(
            candidates,
            key=lambda jid: (
                0 if jid in cover_jobs else 1,
                -quota_pressure.get(instance.get_job(jid).entity_id, 0.0)
                * service_efficiency(jid),
                effective_due(jid),
                _job_total_min_work(instance, jid),
            ),
        ),
        sorted(
            candidates,
            key=lambda jid: (
                -service_efficiency(jid),
                effective_due(jid),
                _job_total_min_work(instance, jid),
            ),
        ),
    ]

    unique: list[list[int]] = []
    seen: set[tuple[int, ...]] = set()
    for order in orders:
        key = tuple(order)
        if key in seen:
            continue
        seen.add(key)
        unique.append(order)
    return unique


def _order_crossover(
    parent_a: list[int],
    parent_b: list[int],
    rng,
    anchor_jobs: list[int] | None = None,
) -> list[int]:
    """Order-crossover for two permutations over the same job set."""
    if len(parent_a) <= 2:
        return list(parent_b if parent_b else parent_a)

    parent_b_filtered = [jid for jid in parent_b if jid in set(parent_a)]
    missing = [jid for jid in parent_a if jid not in set(parent_b_filtered)]
    parent_b_aligned = parent_b_filtered + missing
    if len(parent_b_aligned) != len(parent_a):
        return list(parent_a)

    n = len(parent_a)
    if anchor_jobs:
        anchor_pos = [idx for idx, jid in enumerate(parent_a) if jid in set(anchor_jobs)]
        if anchor_pos:
            left = max(0, min(anchor_pos) - 1)
            right = min(n - 1, max(anchor_pos) + 1)
        else:
            left, right = sorted(rng.sample(range(n), 2))
    else:
        left, right = sorted(rng.sample(range(n), 2))

    child: list[int | None] = [None] * n
    child[left:right + 1] = parent_a[left:right + 1]
    used = {jid for jid in child if jid is not None}
    fill = [jid for jid in parent_b_aligned if jid not in used]
    fill_idx = 0
    for idx in list(range(0, left)) + list(range(right + 1, n)):
        child[idx] = fill[fill_idx]
        fill_idx += 1

    result = [int(jid) for jid in child if jid is not None]
    if result == parent_a and len(result) >= 2:
        i, j = rng.sample(range(len(result)), 2)
        result[i], result[j] = result[j], result[i]
    return result


def _mutate_job_order(order: list[int], rng) -> list[int]:
    """Small mutation used after sequence crossover."""
    mutated = list(order)
    if len(mutated) < 2:
        return mutated
    if rng.random() < 0.5:
        i, j = rng.sample(range(len(mutated)), 2)
        mutated[i], mutated[j] = mutated[j], mutated[i]
    else:
        i, j = sorted(rng.sample(range(len(mutated)), 2))
        mutated[i:j + 1] = reversed(mutated[i:j + 1])
    return mutated


def _repair_by_sequence_crossover(
    instance: SLISPInstance,
    sched: FastSchedule,
    state: ScheduleState,
    candidates: list[int],
    scores: dict[int, float],
    rng,
    anchor_jobs: list[int] | None = None,
    trials: int = 4,
) -> FastSchedule:
    """GA-inspired large neighborhood: order-crossover followed by SGS decode.

    This absorbs the useful part of GA observed in small exact-gap cases: a
    global job-sequence recombination move.  Parent A is the current schedule
    order; parent B is drawn from dispatch/RG/service-cover structural orders.
    """
    parent_a = _schedule_job_order(sched, candidates, instance)
    donors = _sequence_crossover_donor_orders(instance, state, candidates, scores)
    if not parent_a or not donors:
        return sched.clone()

    job_set = set(parent_a)
    population_size = min(24, max(8, 2 * len(parent_a)))
    generations = max(1, trials)
    population: list[list[int]] = [list(parent_a)]
    population.extend(list(order) for order in donors)
    while len(population) < population_size:
        if rng.random() < 0.60:
            base = list(rng.choice(donors))
            population.append(_mutate_job_order(base, rng))
        else:
            base = list(parent_a)
            rng.shuffle(base)
            population.append(base)
    population = population[:population_size]

    def evaluate(order_population: list[list[int]]):
        evaluated = []
        seen_orders: set[tuple[int, ...]] = set()
        for order in order_population:
            if set(order) != job_set:
                continue
            key = tuple(order)
            if key in seen_orders:
                continue
            seen_orders.add(key)
            trial_sched = _greedy_construct(instance, state, order, {}, rng)
            trial_Z = _fast_eval_Z(trial_sched, instance, state)
            evaluated.append((trial_Z, order, trial_sched))
        evaluated.sort(key=lambda item: item[0])
        return evaluated

    evaluated = evaluate(population)
    if not evaluated:
        return sched.clone()

    incumbent_Z = _fast_eval_Z(sched, instance, state)
    best_Z, _best_order, best_sched = evaluated[0]
    if incumbent_Z < best_Z - EPS:
        best_Z = incumbent_Z
        best_sched = sched.clone()

    for _gen in range(generations):
        if not evaluated:
            break
        next_population = [list(order) for _z, order, _sched in evaluated[:2]]
        while len(next_population) < population_size:
            sample_size = min(3, len(evaluated))
            parent_1 = min(rng.sample(evaluated, sample_size), key=lambda item: item[0])[1]
            parent_2 = min(rng.sample(evaluated, sample_size), key=lambda item: item[0])[1]
            child = _order_crossover(parent_1, parent_2, rng, anchor_jobs=anchor_jobs)
            if rng.random() < 0.25:
                child = _mutate_job_order(child, rng)
            next_population.append(child)

        evaluated = evaluate(next_population)
        if evaluated and evaluated[0][0] < best_Z - EPS:
            best_Z, _best_order, best_sched = evaluated[0]

    return best_sched


# ── Destroy operators ──────────────────────────────────────────────────────

def _destroy_random_jobs(
    sched: FastSchedule, k: int, rng,
) -> list[int]:
    """Destroy k randomly selected jobs from the schedule."""
    candidates = [jid for jid in sched.assignments]
    if len(candidates) <= k:
        return candidates
    return list(rng.sample(candidates, k))


def _destroy_worst_tardiness_jobs(
    sched: FastSchedule, instance: SLISPInstance, k: int, state: ScheduleState,
) -> list[int]:
    """Destroy k jobs with the highest projected tardiness."""
    scored = []
    for jid in sched.assignments:
        job = instance.get_job(jid)
        completion = _projected_completion_time(job, sched, instance, state)
        tardiness = _compute_job_tardiness(jid, completion, instance)
        scored.append((tardiness, jid))
    scored.sort(reverse=True)
    return [jid for _t, jid in scored[:k]]


def _destroy_low_rg_score_jobs(
    sched: FastSchedule, scores: dict[int, float], k: int, rng,
) -> list[int]:
    """Destroy k jobs with the lowest RG scores (with some randomness)."""
    candidates = [(scores.get(jid, 0.0), jid) for jid in sched.assignments]
    candidates.sort()
    if len(candidates) <= k:
        return [jid for _s, jid in candidates]
    # Softmax selection: pick from the lower half with noise
    pool = candidates[:max(k, len(candidates) // 2)]
    return [jid for _s, jid in rng.sample(pool, min(k, len(pool)))]


def _destroy_entity_jobs(
    sched: FastSchedule, instance: SLISPInstance, state: ScheduleState, k: int,
) -> list[int]:
    """Destroy k jobs belonging to entities with the highest service shortfall."""
    machine_pool = {m.machine_id for m in instance.machines}
    entity_risk = {}
    for entity in instance.entities:
        sf = current_information_shortfall_risk(
            entity.entity_id, machine_pool, state, instance, method="dp"
        )
        entity_risk[entity.entity_id] = sf * entity.weight
    scored = []
    for jid in sched.assignments:
        job = instance.get_job(jid)
        scored.append((entity_risk.get(job.entity_id, 0.0), jid))
    scored.sort(reverse=True)
    return [jid for _r, jid in scored[:k]]


def _destroy_time_window(
    sched: FastSchedule, k: int, rng,
) -> list[int]:
    """Destroy k jobs whose projected start times fall in a random window."""
    spans = []
    for jid, ops in sched.assignments.items():
        starts = [start for _op_id, _m_id, start in ops]
        if starts:
            spans.append((min(starts), jid))
    if not spans:
        return []
    spans.sort()
    if len(spans) <= k:
        return [jid for _s, jid in spans]
    i = rng.randint(0, max(0, len(spans) - k))
    return [jid for _s, jid in spans[i:i + k]]


# ── Repair operators ───────────────────────────────────────────────────────

def _repair_regret_k(
    instance: SLISPInstance,
    sched: FastSchedule,
    state: ScheduleState,
    destroyed: list[int],
    rng,
) -> None:
    """Reinsert destroyed jobs using regret-2 insertion heuristic."""
    remaining = list(destroyed)
    rng.shuffle(remaining)
    while remaining:
        best_jid = None
        best_regret = -1.0
        best_sched = None
        for jid in remaining:
            job = instance.get_job(jid)
            insertion_costs = []
            for alt in job.operations[0].alternatives:
                m_id = alt.machine_id
                pt = alt.processing_time
                prev_end = max(state.current_time, job.release_time,
                               state.machine_available_times.get(m_id, 0))
                earliest = max(prev_end, sched.earliest_machine_time(m_id, prev_end, pt))
                trial = sched.clone()
                trial.add_op(jid, job.operations[0].op_id, m_id, earliest, earliest + pt)
                cur_end = earliest + pt
                for op in job.operations[1:]:
                    best_end = 10**9
                    best_m = -1
                    for a in op.alternatives:
                        e = max(cur_end, state.machine_available_times.get(a.machine_id, 0),
                                trial.earliest_machine_time(a.machine_id, cur_end, a.processing_time))
                        fin = e + a.processing_time
                        if fin < best_end:
                            best_end = fin
                            best_m = a.machine_id
                    if best_m >= 0:
                        trial.add_op(jid, op.op_id, best_m, cur_end, best_end)
                        cur_end = best_end
                cost = _fast_eval_Z(trial, instance, state)
                insertion_costs.append((cost, trial))
            if len(insertion_costs) >= 2:
                insertion_costs.sort(key=lambda x: x[0])
                regret = insertion_costs[1][0] - insertion_costs[0][0]
            elif len(insertion_costs) == 1:
                regret = 100.0
            else:
                regret = -1.0
            if regret > best_regret:
                best_regret = regret
                best_jid = jid
        if best_jid is None:
            break
        remaining.remove(best_jid)
        _insert_job_greedy(instance, instance.get_job(best_jid), sched, state)


def _repair_random_order(
    instance: SLISPInstance,
    sched: FastSchedule,
    state: ScheduleState,
    destroyed: list[int],
    rng,
) -> None:
    """Reinsert destroyed jobs in random order."""
    order = list(destroyed)
    rng.shuffle(order)
    for jid in order:
        _insert_job_greedy(instance, instance.get_job(jid), sched, state)


def _repair_by_edf(
    instance: SLISPInstance,
    sched: FastSchedule,
    state: ScheduleState,
    destroyed: list[int],
) -> None:
    """Reinsert destroyed jobs by earliest effective deadline first."""
    order = sorted(
        destroyed,
        key=lambda jid: _effective_deadline(instance, instance.get_job(jid)),
    )
    for jid in order:
        _insert_job_greedy(instance, instance.get_job(jid), sched, state)


def _repair_by_rg_score(
    instance: SLISPInstance,
    sched: FastSchedule,
    state: ScheduleState,
    destroyed: list[int],
    scores: dict[int, float],
) -> None:
    """Reinsert destroyed jobs by descending RG priority score."""
    order = sorted(destroyed, key=lambda jid: -scores.get(jid, 0.0))
    for jid in order:
        _insert_job_greedy(instance, instance.get_job(jid), sched, state)


# ── Local search ───────────────────────────────────────────────────────────

def _local_search(
    instance: SLISPInstance,
    sched: FastSchedule,
    state: ScheduleState,
    current_Z: float,
    rng,
    max_iters: int = 40,
) -> tuple[FastSchedule, float]:
    """Local search: adjacent swap, relocate, pull-forward moves."""
    job_ids = [jid for jid in sched.assignments if len(sched.assignments.get(jid, [])) >= 1]

    for _iter in range(max_iters):
        if len(job_ids) < 2:
            break
        improved = False
        for _attempt in range(min(5, len(job_ids))):
            move = rng.randint(0, 2)
            if move == 0:
                # Adjacent order swap
                j1, j2 = rng.sample(job_ids, 2) if len(job_ids) >= 2 else (job_ids[0], job_ids[0])
                if j1 == j2:
                    continue
                copy = sched.clone()
                copy.remove_job(j1)
                copy.remove_job(j2)
                _insert_job_greedy(instance, instance.get_job(j2), copy, state)
                _insert_job_greedy(instance, instance.get_job(j1), copy, state)
                nz = _fast_eval_Z(copy, instance, state)
                if nz < current_Z - EPS:
                    sched = copy
                    current_Z = nz
                    improved = True
            elif move == 1:
                # Relocate one job
                jid = rng.choice(job_ids)
                copy = sched.clone()
                copy.remove_job(jid)
                _insert_job_greedy(instance, instance.get_job(jid), copy, state)
                nz = _fast_eval_Z(copy, instance, state)
                if nz < current_Z - EPS:
                    sched = copy
                    current_Z = nz
                    improved = True
            else:
                # Pull-forward reinsert
                jid = rng.choice(job_ids)
                copy = sched.clone()
                copy.remove_job(jid)
                _insert_job_greedy(instance, instance.get_job(jid), copy, state)
                nz = _fast_eval_Z(copy, instance, state)
                if nz < current_Z - EPS:
                    sched = copy
                    current_Z = nz
                    improved = True
        if not improved:
            break
        # Refresh job list after changes
        job_ids = [jid for jid in sched.assignments if len(sched.assignments.get(jid, [])) >= 1]
    return sched, current_Z


# ── Main algorithm class ─────────────────────────────────────────────────────


class RGRHOLNSFast:
    """RG-RHO-LNS with greedy construction, adaptive LNS, and local search."""

    def __init__(
        self,
        horizon: int = 300,
        lns_iterations: int = 40,
        destroy_fraction: float = 0.4,
        local_search_iters: int = 40,
        rg_weight_a1: float = 0.40,
        rg_weight_a2: float = 0.15,
        rg_weight_a3: float = 0.10,
        rg_weight_a4: float = 0.05,
        rg_weight_a5: float = 0.10,
        rg_weight_a6: float = 0.50,
        rg_weight_a7: float = 0.20,
        use_rg_guidance: bool = True,
        use_rg_construction: bool = False,
        use_lns: bool = True,
        use_local_search: bool = True,
        rg_repair_prob: float = 0.40,
        rg_destroy_prob: float = 0.25,
        max_total_repairs: int = 60,
        max_no_improve: int = 15,
        use_multi_construction: bool = False,
        use_tabu_memory: bool = False,
        tabu_tenure: int = 5,
        z_tolerance: float = 0.0,
        use_adaptive_rg: bool = False,
        use_multi_start_init: bool = False,
        use_operator_adaptation: bool = False,
        operator_reaction_factor: float = 0.20,
        operator_min_weight: float = 0.05,
        operator_max_weight: float = 8.0,
        use_sequence_crossover: bool = False,
        sequence_crossover_trials: int = 4,
        prefer_sequence_crossover_dispatch: bool = False,
        dispatch_mode: str = "standard_projected",
        quota_pressure_rescue_threshold: float = 0.75,
        service_gain_delay_ratio: float = 1.5,
        cover_bonus_weight: float = 0.25,
        mandatory_bonus_weight: float = 0.50,
        use_exact_local_repair: bool = False,
        exact_local_job_limit: int = 8,
        exact_local_time_limit_s: float = 1.0,
        use_exact_small_portfolio: bool = False,
        exact_small_job_limit: int = 12,
        exact_small_time_limit_s: float = 60.0,
        seed: int = 42,
    ):
        self.seed = seed
        self.horizon = horizon
        self.lns_iterations = lns_iterations
        self.destroy_fraction = destroy_fraction
        self.local_search_iters = local_search_iters
        self.rg_weights = (rg_weight_a1, rg_weight_a2, rg_weight_a3, rg_weight_a4, rg_weight_a5, rg_weight_a6, rg_weight_a7)
        self.use_rg_guidance = use_rg_guidance
        self.use_rg_construction = use_rg_construction
        self.use_lns = use_lns
        self.use_local_search = use_local_search
        self.rg_repair_prob = rg_repair_prob
        self.rg_destroy_prob = rg_destroy_prob
        self.max_total_repairs = max_total_repairs
        self.max_no_improve = max_no_improve
        self.use_multi_construction = use_multi_construction
        self.use_tabu_memory = use_tabu_memory
        self.tabu_tenure = tabu_tenure
        self.z_tolerance = z_tolerance
        self.use_adaptive_rg = use_adaptive_rg
        self.use_multi_start_init = use_multi_start_init
        self.use_operator_adaptation = use_operator_adaptation
        self.operator_reaction_factor = operator_reaction_factor
        self.operator_min_weight = operator_min_weight
        self.operator_max_weight = operator_max_weight
        self.use_sequence_crossover = use_sequence_crossover
        self.sequence_crossover_trials = sequence_crossover_trials
        self.prefer_sequence_crossover_dispatch = prefer_sequence_crossover_dispatch
        self.dispatch_mode = dispatch_mode
        self.quota_pressure_rescue_threshold = quota_pressure_rescue_threshold
        self.service_gain_delay_ratio = service_gain_delay_ratio
        self.cover_bonus_weight = cover_bonus_weight
        self.mandatory_bonus_weight = mandatory_bonus_weight
        self.use_exact_local_repair = use_exact_local_repair
        self.exact_local_job_limit = exact_local_job_limit
        self.exact_local_time_limit_s = exact_local_time_limit_s
        self.use_exact_small_portfolio = use_exact_small_portfolio
        self.exact_small_job_limit = exact_small_job_limit
        self.exact_small_time_limit_s = exact_small_time_limit_s
        self.rng = create_rng(seed)

        self._last_event_time: int = -1
        self._current_decisions: list[tuple[int, int, int, int]] = []
        self._event_logs: list[dict] = []
        self._convergence_log: list[dict] = []
        self._pool_B: set[int] | None = None

        # ── Diagnostic instrumentation (non-invasive) ─────────────────
        self._diag_destroy_usage: dict[str, int] = {}
        self._diag_repair_usage: dict[str, int] = {}
        self._diag_destroy_improvements: dict[str, int] = {}
        self._diag_repair_improvements: dict[str, int] = {}
        self._diag_destroy_improvement_magnitudes: dict[str, list[float]] = {}
        self._diag_repair_improvement_magnitudes: dict[str, list[float]] = {}
        self._diag_rg_score_samples: list[dict] = []  # per-event RG score stats
        self._diag_mandatory_counts: list[int] = []
        self._diag_total_ls_attempts: int = 0
        self._diag_total_ls_improvements: int = 0
        self._diag_total_ls_magnitudes: list[float] = []
        self._diag_lns_iterations_total: int = 0
        self._diag_lns_improvements_total: int = 0
        self._destroy_operator_weights: dict[str, float] = {
            name: 1.0 for name in DESTROY_OPERATOR_NAMES
        }
        self._repair_operator_weights: dict[str, float] = {
            name: 1.0 for name in ALL_REPAIR_OPERATOR_NAMES
        }
        self._diag_operator_weight_log: list[dict] = []
        # Adaptive RG diagnostics
        self._diag_trigger_log: list[dict] = []
        self._diag_rg_intensities: list[float] = []
        # Initial solution diagnostics
        self._diag_init_candidates: list[dict] = []
        # Exact local repair diagnostics
        self._diag_exact_local_repairs: list[dict] = []
        self._diag_exact_local_attempts: int = 0
        self._diag_exact_local_accepts: int = 0


    def __call__(
        self, instance: SLISPInstance, state: ScheduleState
    ) -> list[tuple[int, int, int, int]]:
        if state.current_time == self._last_event_time:
            return []
        self._last_event_time = state.current_time

        if self._pool_B is None:
            self._pool_B = {m.machine_id for m in instance.machines}
        pool_B = self._pool_B
        # Candidate jobs: released, uncompleted, within horizon
        candidates = [
            j.job_id for j in instance.jobs
            if not state.is_job_completed(j.job_id)
            and j.release_time <= state.current_time + self.horizon
        ]
        if not candidates:
            return []

        # RG scoring
        scores = _compute_rg_scores(instance, state, pool_B, *self.rg_weights)

        # ── Diagnostics: RG score distribution ─────────────────────
        score_vals = [scores.get(j.job_id, 0) for j in instance.jobs if not state.is_job_completed(j.job_id)]
        if score_vals:
            score_vals.sort()
            n = len(score_vals)
            self._diag_rg_score_samples.append({
                "time": state.current_time,
                "n_jobs": n,
                "min": score_vals[0],
                "p25": score_vals[max(0, n // 4)],
                "median": score_vals[n // 2],
                "p75": score_vals[min(n - 1, 3 * n // 4)],
                "max": score_vals[-1],
                "mean": sum(score_vals) / n,
            })
        # Mandatory job count
        mand_count = 0
        for entity in instance.entities:
            mand = mandatory_rescue_jobs(entity.entity_id, pool_B, state, instance, method="dp")
            mand_count += len(mand)
        self._diag_mandatory_counts.append(mand_count)

        # Sort candidates for greedy construction
        if self.use_rg_construction:
            sorted_candidates = sorted(candidates, key=lambda jid: -scores.get(jid, 0))
        else:
            sorted_candidates = sorted(
                candidates,
                key=lambda jid: _effective_deadline(instance, instance.get_job(jid)),
            )

        # ── Construction: multi-start or multi-construction or single ─
        t0 = time.perf_counter()
        init_diag: list[dict] = []

        if self.use_multi_start_init:
            sched, best_Z, init_diag = _multi_start_initial_solution(
                instance, state, candidates, scores, self.rng, top_k=2, polish_moves=30)
            if not hasattr(self, '_diag_init_candidates'):
                self._diag_init_candidates: list[dict] = []
            for d in init_diag:
                d["event_time"] = state.current_time
            self._diag_init_candidates.extend(init_diag)
        elif self.use_multi_construction:
            # Try multiple construction heuristics, pick best
            constructions = [
                ("EDF", sorted(
                    candidates,
                    key=lambda jid: _effective_deadline(instance, instance.get_job(jid)),
                )),
                ("SPT", sorted(candidates, key=lambda jid: sum(
                    op.min_processing_time for op in instance.get_job(jid).operations))),
            ]
            # ATC-like: sort by (deadline_effective / proc_time)
            constructions.append(
                ("ATC", sorted(candidates, key=lambda jid: (
                    instance.get_entity(instance.get_job(jid).entity_id).deadline
                    - instance.get_entity(instance.get_job(jid).entity_id).transport_delay)
                    / max(1, sum(op.min_processing_time for op in instance.get_job(jid).operations))))
            )
            # RG-priority
            constructions.append(("RG", sorted(candidates, key=lambda jid: -scores.get(jid, 0))))
            # RG-SPT hybrid: RG score * SPT signal
            constructions.append(("RG-SPT", sorted(candidates, key=lambda jid: -(
                scores.get(jid, 0) * (1.0 / max(1, sum(
                    op.min_processing_time for op in instance.get_job(jid).operations))))
            )))

            best_sched = None
            best_Z = float('inf')
            for c_name, c_order in constructions:
                sched = _greedy_construct(instance, state, c_order, scores, self.rng)
                z = _fast_eval_Z(sched, instance, state)
                if z < best_Z - EPS:
                    best_Z = z
                    best_sched = sched
            sched = best_sched
        else:
            sched = _greedy_construct(instance, state, sorted_candidates, scores, self.rng)
            best_Z = _fast_eval_Z(sched, instance, state)
        projected_wsf = _fast_eval_wsf(sched, instance, state)

        # ── Convergence logging: iteration 0 = initial construction ──
        conv_entry = {
            "iteration": 0,
            "current_Z": best_Z,
            "best_so_far_Z": best_Z,
            "runtime_elapsed": 0.0,
        }

        no_improve = 0
        total_repairs = 0
        prefer_projected_dispatch = False

        # ── Adaptive RG: compute entity classification & intensity ────
        rg_intensity = 0.0
        entity_classes: list[dict] = []
        if self.use_adaptive_rg:
            entity_classes, rg_intensity = _classify_entities_and_intensity(
                instance, state, pool_B)
            self._diag_rg_intensities.append(rg_intensity)
            self._diag_trigger_log.append({
                "time": state.current_time,
                "rg_intensity": rg_intensity,
                "n_candidates": len(candidates),
                "entity_classes": [(e["entity_id"], e["class"]) for e in entity_classes],
            })

        # Determine effective RG mode for this event
        if self.use_adaptive_rg:
            effective_rg = rg_intensity > 0.0
            effective_rg_repair_prob = self.rg_repair_prob * rg_intensity
            effective_rg_destroy_prob = self.rg_destroy_prob * rg_intensity
        else:
            effective_rg = self.use_rg_guidance
            effective_rg_repair_prob = self.rg_repair_prob
            effective_rg_destroy_prob = self.rg_destroy_prob

        event_budget = _event_search_budget(
            self.lns_iterations,
            self.local_search_iters,
            rg_intensity,
            projected_wsf,
            mand_count,
        )
        event_lns_iterations = int(event_budget["lns_iterations"])
        event_local_search_iters = int(event_budget["local_search_iters"])
        event_risk_level = str(event_budget["risk_level"])

        if self.use_lns:
            if effective_rg and effective_rg_destroy_prob > 0:
                rd = effective_rg_destroy_prob
                rr = 1.0 - rd
                destroy_context_probs = [
                    0.15 * rr / 0.75,
                    0.20 * rr / 0.75,
                    rd,
                    0.25 * rr / 0.75,
                    0.15 * rr / 0.75,
                ]
            else:
                destroy_context_probs = [0.30, 0.30, 0.00, 0.20, 0.20]
            destroy_context_probs = _normalize_operator_probabilities(
                DESTROY_OPERATOR_NAMES,
                dict(zip(DESTROY_OPERATOR_NAMES, destroy_context_probs)),
            )

            if effective_rg and effective_rg_repair_prob > 0:
                rp = effective_rg_repair_prob
                rr = (1.0 - rp) / 3.0
                repair_context_probs = [rr, rr, rr, rp]
            else:
                repair_context_probs = [0.35, 0.25, 0.25, 0.15]
            repair_context_probs = _normalize_operator_probabilities(
                REPAIR_OPERATOR_NAMES,
                dict(zip(REPAIR_OPERATOR_NAMES, repair_context_probs)),
            )
            repair_operator_names = list(REPAIR_OPERATOR_NAMES)
            if self.use_sequence_crossover and len(candidates) >= 4:
                repair_operator_names.append(SEQUENCE_CROSSOVER_REPAIR)
                sequence_prob = 0.20
                if effective_rg and effective_rg_repair_prob > 0:
                    rg_prob = min(effective_rg_repair_prob, 1.0 - sequence_prob)
                    base_prob = max(0.0, 1.0 - rg_prob - sequence_prob) / 3.0
                    repair_context_probs = [
                        base_prob,
                        base_prob,
                        base_prob,
                        rg_prob,
                        sequence_prob,
                    ]
                else:
                    repair_context_probs = [0.28, 0.20, 0.20, 0.12, sequence_prob]
                repair_context_probs = _normalize_operator_probabilities(
                    repair_operator_names,
                    dict(zip(repair_operator_names, repair_context_probs)),
            )

            tabu_set: set[int] = set()  # recently moved job ids
            for _lns_iter in range(event_lns_iterations):
                if no_improve >= self.max_no_improve or total_repairs >= self.max_total_repairs:
                    break

                k = max(1, int(len(candidates) * self.destroy_fraction))

                if self.use_operator_adaptation:
                    destroy_probs = _combine_context_and_learned_weights(
                        DESTROY_OPERATOR_NAMES,
                        destroy_context_probs,
                        self._destroy_operator_weights,
                        min_weight=self.operator_min_weight,
                    )
                    repair_probs = _combine_context_and_learned_weights(
                        repair_operator_names,
                        repair_context_probs,
                        self._repair_operator_weights,
                        min_weight=self.operator_min_weight,
                    )
                else:
                    destroy_probs = destroy_context_probs
                    repair_probs = repair_context_probs

                # ── Destroy (with diag tracking + tabu avoidance) ────
                d_name = _weighted_operator_choice(
                    DESTROY_OPERATOR_NAMES, destroy_probs, self.rng
                )
                if d_name == "random":
                    destroyed_jobs = _destroy_random_jobs(sched, k, self.rng)
                elif d_name == "worst_tardiness":
                    destroyed_jobs = _destroy_worst_tardiness_jobs(sched, instance, k, state)
                elif d_name == "low_rg_score":
                    destroyed_jobs = _destroy_low_rg_score_jobs(sched, scores, k, self.rng)
                elif d_name == "entity_shortfall":
                    destroyed_jobs = _destroy_entity_jobs(sched, instance, state, k)
                else:
                    destroyed_jobs = _destroy_time_window(sched, k, self.rng)

                # Tabu: avoid re-destroying recently repaired jobs
                if self.use_tabu_memory and tabu_set:
                    destroyed_jobs = [j for j in destroyed_jobs if j not in tabu_set]
                    if not destroyed_jobs:
                        no_improve += 1
                        continue

                if not destroyed_jobs:
                    no_improve += 1
                    continue

                copy = sched.clone()
                for jid in destroyed_jobs:
                    copy.remove_job(jid)

                # ── Repair (with diag tracking) ─────────────────────
                r_name = _weighted_operator_choice(
                    repair_operator_names, repair_probs, self.rng
                )
                if r_name == "regret_k":
                    _repair_regret_k(instance, copy, state, destroyed_jobs, self.rng)
                elif r_name == "random_order":
                    _repair_random_order(instance, copy, state, destroyed_jobs, self.rng)
                elif r_name == "edf":
                    _repair_by_edf(instance, copy, state, destroyed_jobs)
                elif r_name == SEQUENCE_CROSSOVER_REPAIR:
                    copy = _repair_by_sequence_crossover(
                        instance,
                        sched,
                        state,
                        candidates,
                        scores,
                        self.rng,
                        anchor_jobs=destroyed_jobs,
                        trials=self.sequence_crossover_trials,
                    )
                else:
                    _repair_by_rg_score(instance, copy, state, destroyed_jobs, scores)

                new_Z = _fast_eval_Z(copy, instance, state)
                total_repairs += 1
                self._diag_lns_iterations_total += 1

                # ── Record usage ────────────────────────────────────
                combo = f"{d_name}+{r_name}"
                self._diag_destroy_usage[d_name] = self._diag_destroy_usage.get(d_name, 0) + 1
                self._diag_repair_usage[r_name] = self._diag_repair_usage.get(r_name, 0) + 1

                # ── Acceptance with tolerance ────────────────────────
                tol = self.z_tolerance
                # Accept if: strictly better, OR within tolerance AND improves WSF
                strict_improve = new_Z < best_Z - EPS
                accept = strict_improve
                wsf_tolerance_accept = False
                if not accept and tol > 0:
                    # Compute WSF change
                    def _quick_wsf(s):
                        return _fast_eval_wsf(s, instance, state)
                    current_wsf = _quick_wsf(sched)
                    new_wsf = _quick_wsf(copy)
                    if new_Z <= best_Z * (1.0 + tol) and new_wsf < current_wsf - EPS:
                        accept = True
                        wsf_tolerance_accept = True

                if self.use_operator_adaptation:
                    reward = _operator_learning_reward(
                        best_Z,
                        new_Z,
                        accepted=accept,
                        wsf_tolerance_accept=wsf_tolerance_accept,
                    )
                    _update_operator_weight(
                        self._destroy_operator_weights,
                        d_name,
                        reward,
                        self.operator_reaction_factor,
                        self.operator_min_weight,
                        self.operator_max_weight,
                    )
                    _update_operator_weight(
                        self._repair_operator_weights,
                        r_name,
                        reward,
                        self.operator_reaction_factor,
                        self.operator_min_weight,
                        self.operator_max_weight,
                    )
                    self._diag_operator_weight_log.append({
                        "time": state.current_time,
                        "iteration": total_repairs,
                        "destroy": d_name,
                        "repair": r_name,
                        "reward": reward,
                        "accepted": accept,
                        "old_Z": best_Z,
                        "new_Z": new_Z,
                        "destroy_weights": dict(self._destroy_operator_weights),
                        "repair_weights": dict(self._repair_operator_weights),
                    })

                if accept:
                    delta = best_Z - new_Z
                    if (
                        r_name == SEQUENCE_CROSSOVER_REPAIR
                        and self.prefer_sequence_crossover_dispatch
                    ):
                        prefer_projected_dispatch = True
                    self._diag_lns_improvements_total += 1
                    self._diag_destroy_improvements[d_name] = self._diag_destroy_improvements.get(d_name, 0) + 1
                    self._diag_repair_improvements[r_name] = self._diag_repair_improvements.get(r_name, 0) + 1
                    self._diag_destroy_improvement_magnitudes.setdefault(d_name, []).append(delta)
                    self._diag_repair_improvement_magnitudes.setdefault(r_name, []).append(delta)
                    # Tabu: mark destroyed jobs as recently moved
                    if self.use_tabu_memory:
                        for jid in destroyed_jobs:
                            tabu_set.add(jid)
                        if len(tabu_set) > self.tabu_tenure:
                            tabu_set.clear()
                    best_Z = new_Z
                    sched = copy
                    no_improve = 0
                else:
                    no_improve += 1

                # Convergence log entry
                conv_entry = {
                    "iteration": total_repairs,
                    "current_Z": new_Z,
                    "best_so_far_Z": best_Z,
                    "runtime_elapsed": time.perf_counter() - t0,
                }
                self._convergence_log.append(conv_entry)

        if self.use_local_search:
            ls_before = best_Z
            sched, best_Z = _local_search(
                instance,
                sched,
                state,
                best_Z,
                self.rng,
                event_local_search_iters,
            )
            if best_Z < ls_before - EPS:
                self._diag_total_ls_improvements += 1
                self._diag_total_ls_magnitudes.append(ls_before - best_Z)
            self._diag_total_ls_attempts += 1

        run_exact_local = _should_run_exact_local_repair(
            self.use_exact_local_repair,
            projected_wsf,
            mand_count,
            rg_intensity,
            no_improve,
        )
        if run_exact_local:
            repair_before = best_Z
            sched, best_Z, repair_info = _apply_exact_local_repair(
                instance,
                state,
                sched,
                best_Z,
                candidates,
                scores,
                max_jobs=self.exact_local_job_limit,
                time_limit_s=self.exact_local_time_limit_s,
            )
            repair_info["time"] = state.current_time
            self._diag_exact_local_repairs.append(repair_info)
            if repair_info.get("attempted"):
                self._diag_exact_local_attempts += 1
                self._diag_repair_usage["exact_local"] = self._diag_repair_usage.get("exact_local", 0) + 1
            if repair_info.get("accepted"):
                self._diag_exact_local_accepts += 1
                delta = repair_before - best_Z
                self._diag_repair_improvements["exact_local"] = (
                    self._diag_repair_improvements.get("exact_local", 0) + 1
                )
                self._diag_repair_improvement_magnitudes.setdefault("exact_local", []).append(delta)
        elif self.use_exact_local_repair:
            self._diag_exact_local_repairs.append({
                "attempted": False,
                "accepted": False,
                "active_jobs": [],
                "status": "SKIPPED_LOW_RISK",
                "old_Z": best_Z,
                "new_Z": best_Z,
                "runtime_ms": 0.0,
                "time": state.current_time,
            })

        # Return only decisions that are feasible in the current real state.
        t_now = state.current_time
        immediate = _extract_immediate_decisions(
            sched,
            instance,
            state,
            dispatch_mode=self.dispatch_mode,
            quota_pressure_rescue_threshold=self.quota_pressure_rescue_threshold,
            service_gain_delay_ratio=self.service_gain_delay_ratio,
            cover_bonus_weight=self.cover_bonus_weight,
            mandatory_bonus_weight=self.mandatory_bonus_weight,
        )
        self._current_decisions = immediate

        self._event_logs.append({
            "time": t_now,
            "candidates": len(candidates),
            "best_Z": best_Z,
            "projected_wsf": projected_wsf,
            "risk_level": event_risk_level,
            "lns_budget": event_lns_iterations,
            "local_search_budget": event_local_search_iters,
            "immediate_ops": len(immediate),
            "runtime_ms": (time.perf_counter() - t0) * 1000,
            "exact_local_attempts": self._diag_exact_local_attempts,
            "exact_local_accepts": self._diag_exact_local_accepts,
            "destroy_operator_weights": dict(self._destroy_operator_weights),
            "repair_operator_weights": dict(self._repair_operator_weights),
        })

        return immediate


# ── Variant factories ──────────────────────────────────────────────────────

def run_plain_rho_fast(
    horizon: int = 300, seed: int = 42
) -> RGRHOLNSFast:
    """Plain RHO-Fast: EDF greedy construction only, no LNS, no RG."""
    return RGRHOLNSFast(
        horizon=horizon, lns_iterations=0, destroy_fraction=0.3,
        local_search_iters=0,
        use_rg_guidance=False, use_rg_construction=False,
        use_lns=False, use_local_search=False,
        seed=seed,
    )


def run_rho_lns_fast(
    horizon: int = 300, lns_iterations: int = 20, seed: int = 42,
) -> RGRHOLNSFast:
    """RHO-LNS-Fast: EDF greedy + LNS + local search, no RG guidance in LNS."""
    return RGRHOLNSFast(
        horizon=horizon, lns_iterations=lns_iterations, destroy_fraction=0.4,
        local_search_iters=30,
        use_rg_guidance=False, use_rg_construction=False,
        use_lns=True, use_local_search=True,
        seed=seed,
    )


def run_rg_rho_fast(
    horizon: int = 300, seed: int = 42,
) -> RGRHOLNSFast:
    """RG-RHO-Fast: RG-guided greedy construction, no LNS."""
    return RGRHOLNSFast(
        horizon=horizon, lns_iterations=0, destroy_fraction=0.3,
        local_search_iters=0,
        use_rg_guidance=False, use_rg_construction=True,
        use_lns=False, use_local_search=False,
        rg_weight_a1=0.15, rg_weight_a2=0.40, rg_weight_a3=0.35, rg_weight_a4=0.10, rg_weight_a5=0.0,
        seed=seed,
    )


def run_rg_rho_lns_fast(
    horizon: int = 300, lns_iterations: int = 20, seed: int = 42,
) -> RGRHOLNSFast:
    """RG-RHO-LNS-Fast v1.0: EDF construction + RG-guided LNS."""
    return RGRHOLNSFast(
        horizon=horizon, lns_iterations=lns_iterations, destroy_fraction=0.4,
        local_search_iters=30,
        use_rg_guidance=True, use_rg_construction=False,
        use_lns=True, use_local_search=True,
        rg_weight_a1=0.15, rg_weight_a2=0.40, rg_weight_a3=0.35, rg_weight_a4=0.10, rg_weight_a5=0.0,
        max_total_repairs=10, max_no_improve=3,
        seed=seed,
    )


def run_rg_rho_lns_fast_v11(
    horizon: int = 300, lns_iterations: int = 40, seed: int = 42,
) -> RGRHOLNSFast:
    """RG-RHO-LNS-Fast v1.1: multi-construction + SPT/RG signal + tabu + higher budget."""
    return RGRHOLNSFast(
        horizon=horizon, lns_iterations=lns_iterations, destroy_fraction=0.4,
        local_search_iters=40,
        use_rg_guidance=True, use_rg_construction=False,
        use_lns=True, use_local_search=True,
        rg_weight_a1=0.40, rg_weight_a2=0.15, rg_weight_a3=0.10, rg_weight_a4=0.05,
        rg_weight_a5=0.10, rg_weight_a6=0.50, rg_weight_a7=0.20,
        max_total_repairs=60, max_no_improve=15,
        use_multi_construction=True, use_tabu_memory=True, tabu_tenure=5,
        z_tolerance=0.01,
        seed=seed,
    )


def run_adaptive_rg_rho_lns_fast(
    horizon: int = 300, lns_iterations: int = 40, seed: int = 42,
) -> RGRHOLNSFast:
    """Adaptive-RG-RHO-LNS v1.2: RHO-LNS default, RG only in fragile-recoverable states."""
    return RGRHOLNSFast(
        horizon=horizon, lns_iterations=lns_iterations, destroy_fraction=0.4,
        local_search_iters=40,
        use_rg_guidance=False, use_rg_construction=False,
        use_lns=True, use_local_search=True,
        rg_weight_a1=0.40, rg_weight_a2=0.15, rg_weight_a3=0.10, rg_weight_a4=0.05,
        rg_weight_a5=0.10, rg_weight_a6=0.50, rg_weight_a7=0.20,
        rg_repair_prob=0.40, rg_destroy_prob=0.25,
        max_total_repairs=60, max_no_improve=15,
        use_multi_construction=True, use_tabu_memory=True, tabu_tenure=5,
        z_tolerance=0.01,
        use_adaptive_rg=True,
        seed=seed,
    )


def run_rg_alns(
    horizon: int = 300,
    lns_iterations: int = 20,
    exact_local_job_limit: int = 8,
    exact_local_time_limit_s: float = 0.2,
    use_sequence_crossover: bool = True,
    sequence_crossover_trials: int = 4,
    dispatch_mode: str = "standard_projected",
    seed: int = 42,
) -> RGRHOLNSFast:
    """RG-ALNS: Recoverability-Guided Adaptive Large Neighborhood Search.

    The algorithm operates in an event-driven rolling-horizon manner. It uses
    multi-start projected schedule construction, recoverability-guided ALNS,
    tabu memory, local search, and bounded exact local repair. The paper main
    method dispatches by standard_projected extraction.
    """
    return RGRHOLNSFast(
        horizon=horizon, lns_iterations=lns_iterations, destroy_fraction=0.4,
        local_search_iters=40,
        use_rg_guidance=False, use_rg_construction=False,
        use_lns=True, use_local_search=True,
        rg_weight_a1=0.40, rg_weight_a2=0.15, rg_weight_a3=0.10, rg_weight_a4=0.05,
        rg_weight_a5=0.10, rg_weight_a6=0.50, rg_weight_a7=0.20,
        rg_repair_prob=0.40, rg_destroy_prob=0.25,
        max_total_repairs=60, max_no_improve=15,
        use_multi_construction=False,
        use_tabu_memory=True, tabu_tenure=5,
        z_tolerance=0.01,
        use_adaptive_rg=True,
        use_multi_start_init=True,
        use_operator_adaptation=True,
        use_sequence_crossover=use_sequence_crossover,
        sequence_crossover_trials=sequence_crossover_trials,
        prefer_sequence_crossover_dispatch=False,
        dispatch_mode=dispatch_mode,
        use_exact_local_repair=True,
        exact_local_job_limit=exact_local_job_limit,
        exact_local_time_limit_s=exact_local_time_limit_s,
        use_exact_small_portfolio=False,
        exact_small_job_limit=12,
        exact_small_time_limit_s=60.0,
        seed=seed,
    )


def run_nr_rg_rho_lns(
    horizon: int = 300,
    lns_iterations: int = 20,
    exact_local_job_limit: int = 8,
    exact_local_time_limit_s: float = 0.2,
    use_sequence_crossover: bool = True,
    sequence_crossover_trials: int = 4,
    dispatch_mode: str = "standard_projected",
    seed: int = 42,
) -> RGRHOLNSFast:
    """Backward-compatible legacy wrapper for the paper method now named RG-ALNS."""
    return run_rg_alns(
        horizon=horizon,
        lns_iterations=lns_iterations,
        exact_local_job_limit=exact_local_job_limit,
        exact_local_time_limit_s=exact_local_time_limit_s,
        use_sequence_crossover=use_sequence_crossover,
        sequence_crossover_trials=sequence_crossover_trials,
        dispatch_mode=dispatch_mode,
        seed=seed,
    )


def run_rg_alns_small_oracle(
    horizon: int = 300,
    lns_iterations: int = 20,
    exact_local_job_limit: int = 8,
    exact_local_time_limit_s: float = 0.2,
    use_sequence_crossover: bool = True,
    sequence_crossover_trials: int = 4,
    dispatch_mode: str = "standard_projected",
    seed: int = 42,
) -> RGRHOLNSFast:
    """Diagnostic small-instance oracle portfolio, not the paper main method."""
    algo = run_rg_alns(
        horizon=horizon,
        lns_iterations=lns_iterations,
        exact_local_job_limit=exact_local_job_limit,
        exact_local_time_limit_s=exact_local_time_limit_s,
        use_sequence_crossover=use_sequence_crossover,
        sequence_crossover_trials=sequence_crossover_trials,
        dispatch_mode=dispatch_mode,
        seed=seed,
    )
    algo.use_exact_local_repair = False
    algo.use_exact_small_portfolio = True
    return algo


def run_nr_rg_rho_lns_small_oracle(
    horizon: int = 300,
    lns_iterations: int = 20,
    exact_local_job_limit: int = 8,
    exact_local_time_limit_s: float = 0.2,
    use_sequence_crossover: bool = True,
    sequence_crossover_trials: int = 4,
    dispatch_mode: str = "standard_projected",
    seed: int = 42,
) -> RGRHOLNSFast:
    """Backward-compatible legacy wrapper for the RG-ALNS diagnostic oracle."""
    return run_rg_alns_small_oracle(
        horizon=horizon,
        lns_iterations=lns_iterations,
        exact_local_job_limit=exact_local_job_limit,
        exact_local_time_limit_s=exact_local_time_limit_s,
        use_sequence_crossover=use_sequence_crossover,
        sequence_crossover_trials=sequence_crossover_trials,
        dispatch_mode=dispatch_mode,
        seed=seed,
    )


