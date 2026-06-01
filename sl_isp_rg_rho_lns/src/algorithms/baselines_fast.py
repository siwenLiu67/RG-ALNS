"""Additional SOTA baselines for SL-ISP solver-free framework.

Rule-based: SPT, WSPT, ATC
Metaheuristic: ILS-Fast, VNS-Fast, TS-Fast

All implement SchedulingAlgorithm: (instance, state) -> list[(job_id, op_id, machine_id, start_time)]
"""

import logging
import math
import time
from ..core.dataclasses import SLISPInstance, Job, Operation
from ..core.schedule_state import ScheduleState
from ..utils.random_seed import create_rng

# Reuse FastSchedule infrastructure
from .rg_rho_lns_fast import (
    FastSchedule, _fast_eval_Z, _greedy_construct, _insert_job_greedy,
    _destroy_random_jobs, _destroy_worst_tardiness_jobs,
    _repair_random_order, _repair_by_edf, _repair_regret_k,
    _extract_immediate_decisions,
    _effective_deadline, EPS,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Rule-based dispatching baselines
# ═══════════════════════════════════════════════════════════════════════════════

def _dispatch_on_idle_machines(
    instance: SLISPInstance,
    state: ScheduleState,
    sort_key_fn,
) -> list[tuple[int, int, int, int]]:
    """Generic dispatching: for each idle machine, assign best ready operation."""
    decisions: list[tuple[int, int, int, int]] = []

    ready_ops: list[tuple[Job, Operation]] = []
    for job in instance.jobs:
        if state.is_job_completed(job.job_id):
            continue
        if job.release_time > state.current_time:
            continue
        next_idx = state.next_op_index_for_job(job.job_id)
        if next_idx >= job.num_operations:
            continue
        op = job.operation_at(next_idx)
        if state.is_operation_completed(job.job_id, op.op_id):
            continue
        if state.is_operation_ongoing(job.job_id, op.op_id):
            continue
        ready_ops.append((job, op))

    if not ready_ops:
        return decisions

    idle_machines = [
        m.machine_id for m in instance.machines
        if state.is_machine_idle(m.machine_id)
    ]
    assigned_ops: set[tuple[int, int]] = set()

    for m_id in idle_machines:
        avail = state.machine_available_times.get(m_id, 0)
        start_lower = max(state.current_time, avail)

        candidates: list[tuple[Job, Operation, int]] = []
        for job, op in ready_ops:
            if (job.job_id, op.op_id) in assigned_ops:
                continue
            try:
                pt = op.processing_time_on(m_id)
            except KeyError:
                continue
            candidates.append((job, op, pt))

        if not candidates:
            continue

        candidates.sort(key=sort_key_fn)
        job, op, pt = candidates[0]
        decisions.append((job.job_id, op.op_id, m_id, start_lower))
        assigned_ops.add((job.job_id, op.op_id))

    return decisions


def spt_rule(instance: SLISPInstance, state: ScheduleState) -> list[tuple[int, int, int, int]]:
    """Shortest Processing Time first."""
    return _dispatch_on_idle_machines(
        instance, state,
        lambda item: (item[2],)  # (job, op, pt) -> sort by processing time
    )


def wspt_rule(instance: SLISPInstance, state: ScheduleState) -> list[tuple[int, int, int, int]]:
    """Weighted Shortest Processing Time: pt / entity_weight."""
    def key(item):
        job, _op, pt = item
        entity = instance.get_entity(job.entity_id)
        w = entity.weight if entity.weight > 0 else 1.0
        return (pt / w,)
    return _dispatch_on_idle_machines(instance, state, key)


def atc_rule(instance: SLISPInstance, state: ScheduleState) -> list[tuple[int, int, int, int]]:
    """Apparent Tardiness Cost rule adapted for SL-ISP.

    ATC index: I_j(t) = (w_j / p_j) * exp(-max(0, d_j - p_j - t) / (K * p_bar))
    where w_j = entity weight, d_j = entity deadline - transport_delay,
    p_j = operation processing time, K = look-ahead parameter, p_bar = avg processing time.
    """
    decisions: list[tuple[int, int, int, int]] = []

    ready_ops: list[tuple[Job, Operation]] = []
    for job in instance.jobs:
        if state.is_job_completed(job.job_id):
            continue
        if job.release_time > state.current_time:
            continue
        next_idx = state.next_op_index_for_job(job.job_id)
        if next_idx >= job.num_operations:
            continue
        op = job.operation_at(next_idx)
        if state.is_operation_completed(job.job_id, op.op_id):
            continue
        if state.is_operation_ongoing(job.job_id, op.op_id):
            continue
        ready_ops.append((job, op))

    if not ready_ops:
        return decisions

    idle_machines = [
        m.machine_id for m in instance.machines
        if state.is_machine_idle(m.machine_id)
    ]
    assigned_ops: set[tuple[int, int]] = set()

    # Compute average processing time across all alternatives for look-ahead
    all_pts = []
    for _, op in ready_ops:
        for alt in op.alternatives:
            all_pts.append(alt.processing_time)
    p_bar = sum(all_pts) / max(1, len(all_pts))
    K = 2.0  # look-ahead parameter

    for m_id in idle_machines:
        avail = state.machine_available_times.get(m_id, 0)
        t = max(state.current_time, avail)

        candidates: list[tuple[float, Job, Operation, int]] = []
        for job, op in ready_ops:
            if (job.job_id, op.op_id) in assigned_ops:
                continue
            try:
                pt = op.processing_time_on(m_id)
            except KeyError:
                continue
            entity = instance.get_entity(job.entity_id)
            w = entity.weight if entity.weight > 0 else 1.0
            d_effective = entity.deadline - entity.transport_delay
            slack = max(0, d_effective - pt - t)
            I_j = (w / pt) * (2.71828 ** (-slack / max(1, K * p_bar)))
            candidates.append((-I_j, job, op, pt))  # negative for descending sort

        if not candidates:
            continue

        candidates.sort(key=lambda x: x[0])
        _, job, op, pt = candidates[0]
        decisions.append((job.job_id, op.op_id, m_id, t))
        assigned_ops.add((job.job_id, op.op_id))

    return decisions


# ═══════════════════════════════════════════════════════════════════════════════
# Base class for rolling-horizon metaheuristics
# ═══════════════════════════════════════════════════════════════════════════════

class _RollingHorizonMetaheuristic:
    """Base: build initial schedule via greedy, improve via metaheuristic, dispatch."""

    def __init__(self, horizon: int = 300, max_iter: int = 100, seed: int = 42):
        self.horizon = horizon
        self.max_iter = max_iter
        self.rng = create_rng(seed)
        self._last_event_time: int = -1
        self._event_logs: list[dict] = []
        # Convergence logging
        self._convergence_log: list[dict] = []

    def _initial_schedule(self, instance, state, candidates, sorted_candidates):
        """Build initial greedy schedule (EDF order)."""
        scores = {}
        return _greedy_construct(instance, state, sorted_candidates, scores, self.rng)

    def _improve(self, instance, state, sched, candidates) -> tuple[FastSchedule, float, list[dict]]:
        """Override in subclass. Returns (improved_schedule, best_Z, conv_entries)."""
        raise NotImplementedError

    def _extract_decisions(
        self,
        sched: FastSchedule,
        instance: SLISPInstance,
        state: ScheduleState,
    ) -> list[tuple[int, int, int, int]]:
        """Extract simulator-valid decisions from the projected schedule."""
        return _extract_immediate_decisions(sched, instance, state)

    def __call__(self, instance: SLISPInstance, state: ScheduleState
                 ) -> list[tuple[int, int, int, int]]:
        if state.current_time == self._last_event_time:
            return []
        self._last_event_time = state.current_time

        candidates = [
            j.job_id for j in instance.jobs
            if not state.is_job_completed(j.job_id)
            and j.release_time <= state.current_time + self.horizon
        ]
        if not candidates:
            return []

        t_now = state.current_time
        sorted_candidates = sorted(
            candidates,
            key=lambda jid: _effective_deadline(instance, instance.get_job(jid)),
        )

        t0 = time.perf_counter()
        sched = self._initial_schedule(instance, state, candidates, sorted_candidates)
        best_Z = _fast_eval_Z(sched, instance, state)

        conv_entries = [{"iteration": 0, "current_Z": best_Z, "best_so_far_Z": best_Z,
                         "runtime_elapsed": 0.0}]

        sched, best_Z, extra_entries = self._improve(instance, state, sched, candidates)
        conv_entries.extend(extra_entries)

        # Record convergence log
        for entry in conv_entries:
            entry["algorithm"] = self.__class__.__name__
        self._convergence_log.extend(conv_entries)

        immediate = self._extract_decisions(sched, instance, state)

        self._event_logs.append({
            "time": t_now, "candidates": len(candidates),
            "best_Z": best_Z, "immediate_ops": len(immediate),
            "runtime_ms": (time.perf_counter() - t0) * 1000,
        })
        return immediate


# ═══════════════════════════════════════════════════════════════════════════════
# ILS-Fast: Iterated Local Search
# ═══════════════════════════════════════════════════════════════════════════════

class ILSFast(_RollingHorizonMetaheuristic):
    """Iterated Local Search: EDF construction + perturbation + local search."""

    def __init__(self, horizon: int = 300, max_iter: int = 100,
                 perturb_fraction: float = 0.3, ls_iters: int = 5, seed: int = 42):
        super().__init__(horizon=horizon, max_iter=max_iter, seed=seed)
        self.perturb_fraction = perturb_fraction
        self.ls_iters = ls_iters

    def _improve(self, instance, state, sched, candidates) -> tuple[FastSchedule, float, list[dict]]:
        current_Z = _fast_eval_Z(sched, instance, state)
        best_sched = sched.clone()
        best_Z = current_Z
        entries = []
        t_start = time.perf_counter()

        job_ids = [jid for jid in sched.assignments if sched.assignments[jid]]

        for it in range(self.max_iter):
            # Perturbation: destroy and randomly reinsert some jobs
            k = max(1, int(len(job_ids) * self.perturb_fraction))
            destroyed = _destroy_random_jobs(sched, k, self.rng)
            if not destroyed:
                continue

            for jid in destroyed:
                sched.remove_job(jid)
            _repair_random_order(instance, sched, state, destroyed, self.rng)
            current_Z = _fast_eval_Z(sched, instance, state)

            # Local search
            for _ls in range(self.ls_iters):
                if len(job_ids) < 2:
                    break
                j1 = self.rng.choice(job_ids)
                j2 = self.rng.choice(job_ids)
                if j1 == j2 or j1 not in sched.assignments or j2 not in sched.assignments:
                    continue
                copy = sched.clone()
                copy.remove_job(j1)
                copy.remove_job(j2)
                _insert_job_greedy(instance, instance.get_job(j2), copy, state)
                _insert_job_greedy(instance, instance.get_job(j1), copy, state)
                new_Z = _fast_eval_Z(copy, instance, state)
                if new_Z < current_Z - EPS:
                    sched = copy
                    current_Z = new_Z

            if current_Z < best_Z - EPS:
                best_Z = current_Z
                best_sched = sched.clone()

            entries.append({
                "iteration": it + 1,
                "current_Z": current_Z,
                "best_so_far_Z": best_Z,
                "runtime_elapsed": time.perf_counter() - t_start,
            })

        return best_sched, best_Z, entries


# ═══════════════════════════════════════════════════════════════════════════════
# VNS-Fast: Variable Neighborhood Search
# ═══════════════════════════════════════════════════════════════════════════════

class VNSFast(_RollingHorizonMetaheuristic):
    """Variable Neighborhood Search with multiple neighborhood structures."""

    def __init__(self, horizon: int = 300, max_iter: int = 100, seed: int = 42):
        super().__init__(horizon=horizon, max_iter=max_iter, seed=seed)

    def _shake(self, sched: FastSchedule, instance, state, k: int):
        """Perturbation of increasing strength."""
        job_ids = [jid for jid in sched.assignments if sched.assignments[jid]]
        if not job_ids:
            return
        n_destroy = min(k + 1, len(job_ids))
        destroyed = _destroy_random_jobs(sched, n_destroy, self.rng)
        for jid in destroyed:
            sched.remove_job(jid)
        _repair_random_order(instance, sched, state, destroyed, self.rng)

    def _vnd(self, sched: FastSchedule, instance, state
             ) -> tuple[FastSchedule, float]:
        """Variable Neighborhood Descent: try neighborhoods until no improvement."""
        current_Z = _fast_eval_Z(sched, instance, state)
        improved = True
        while improved:
            improved = False
            job_ids = [jid for jid in sched.assignments if len(sched.assignments[jid]) >= 1]

            # N1: pairwise job swap
            for _ in range(min(5, len(job_ids) // 2)):
                if len(job_ids) < 2:
                    break
                j1 = self.rng.choice(job_ids)
                j2 = self.rng.choice(job_ids)
                if j1 == j2:
                    continue
                copy = sched.clone()
                copy.remove_job(j1)
                copy.remove_job(j2)
                _insert_job_greedy(instance, instance.get_job(j2), copy, state)
                _insert_job_greedy(instance, instance.get_job(j1), copy, state)
                new_Z = _fast_eval_Z(copy, instance, state)
                if new_Z < current_Z - EPS:
                    sched = copy
                    current_Z = new_Z
                    improved = True

            # N2: single job reinsertion (different machine)
            for _ in range(min(3, len(job_ids))):
                jid = self.rng.choice(job_ids)
                copy = sched.clone()
                copy.remove_job(jid)
                _insert_job_greedy(instance, instance.get_job(jid), copy, state)
                new_Z = _fast_eval_Z(copy, instance, state)
                if new_Z < current_Z - EPS:
                    sched = copy
                    current_Z = new_Z
                    improved = True

        return sched, current_Z

    def _improve(self, instance, state, sched, candidates) -> tuple[FastSchedule, float, list[dict]]:
        sched, current_Z = self._vnd(sched, instance, state)
        best_sched = sched.clone()
        best_Z = current_Z
        entries = []
        t_start = time.perf_counter()

        for it in range(self.max_iter):
            k_max = 3
            for k in range(1, k_max + 1):
                copy = sched.clone()
                self._shake(copy, instance, state, k)
                improved, improved_Z = self._vnd(copy, instance, state)
                if improved_Z < best_Z - EPS:
                    best_Z = improved_Z
                    best_sched = improved.clone()
                    sched = improved
                    current_Z = improved_Z
                    break  # back to k=1
            else:
                pass  # no improvement for any k

            entries.append({
                "iteration": it + 1,
                "current_Z": current_Z,
                "best_so_far_Z": best_Z,
                "runtime_elapsed": time.perf_counter() - t_start,
            })

        return best_sched, best_Z, entries


# ═══════════════════════════════════════════════════════════════════════════════
# TS-Fast: Tabu Search
# ═══════════════════════════════════════════════════════════════════════════════

class TSFast(_RollingHorizonMetaheuristic):
    """Tabu Search with swap/relocate neighborhoods and short tabu tenure."""

    def __init__(self, horizon: int = 300, max_iter: int = 100,
                 tabu_tenure: int = 7, seed: int = 42):
        super().__init__(horizon=horizon, max_iter=max_iter, seed=seed)
        self.tabu_tenure = tabu_tenure

    def _improve(self, instance, state, sched, candidates) -> tuple[FastSchedule, float, list[dict]]:
        current_sched = sched.clone()
        current_Z = _fast_eval_Z(current_sched, instance, state)
        best_sched = current_sched.clone()
        best_Z = current_Z
        tabu_list: dict[tuple, int] = {}  # (j1, j2) -> expiration_iter
        entries = []
        t_start = time.perf_counter()

        job_ids = [jid for jid in current_sched.assignments if current_sched.assignments[jid]]

        for it in range(self.max_iter):
            if len(job_ids) < 2:
                break

            best_move = None
            best_move_Z = float('inf')

            # Try up to 10 candidate moves per iteration
            for _ in range(min(10, len(job_ids) * 2)):
                j1 = self.rng.choice(job_ids)
                j2 = self.rng.choice(job_ids)
                if j1 == j2:
                    continue

                move_key = (min(j1, j2), max(j1, j2))
                if tabu_list.get(move_key, 0) > it:
                    # Aspiration: accept if better than global best
                    pass  # still evaluate below
                elif tabu_list.get(move_key, 0) > it:
                    continue

                copy = current_sched.clone()
                # Remove both jobs, reinsert in reversed order
                if j1 in copy.assignments and j2 in copy.assignments:
                    copy.remove_job(j1)
                    copy.remove_job(j2)
                    _insert_job_greedy(instance, instance.get_job(j2), copy, state)
                    _insert_job_greedy(instance, instance.get_job(j1), copy, state)
                    new_Z = _fast_eval_Z(copy, instance, state)
                    is_tabu = tabu_list.get(move_key, 0) > it
                    if new_Z < best_move_Z and (new_Z < best_Z - EPS or not is_tabu):
                        best_move_Z = new_Z
                        best_move = (copy, j1, j2, move_key)

            if best_move is None:
                continue

            copy, j1, j2, move_key = best_move
            is_improving = best_move_Z < best_Z - EPS

            current_sched = copy
            current_Z = best_move_Z

            # Update tabu list
            tabu_list[move_key] = it + self.tabu_tenure
            # Clean expired entries
            tabu_list = {k: v for k, v in tabu_list.items() if v > it}

            if best_move_Z < best_Z - EPS:
                best_Z = best_move_Z
                best_sched = current_sched.clone()

            entries.append({
                "iteration": it + 1,
                "current_Z": current_Z,
                "best_so_far_Z": best_Z,
                "runtime_elapsed": time.perf_counter() - t_start,
            })

        return best_sched, best_Z, entries


# ═══════════════════════════════════════════════════════════════════════════════
# SA-Fast: Simulated Annealing
# ═══════════════════════════════════════════════════════════════════════════════

class SAFast(_RollingHorizonMetaheuristic):
    """Simulated Annealing over job-order neighborhoods.

    The projected schedule is still decoded by the same FastSchedule machinery
    used by the other baselines.  SA only controls which job-level neighborhood
    to sample and whether a non-improving move is accepted.
    """

    def __init__(
        self,
        horizon: int = 300,
        max_iter: int = 100,
        initial_temperature_ratio: float = 0.10,
        cooling_rate: float = 0.95,
        seed: int = 42,
    ):
        super().__init__(horizon=horizon, max_iter=max_iter, seed=seed)
        self.initial_temperature_ratio = initial_temperature_ratio
        self.cooling_rate = cooling_rate

    def _neighbor(self, instance, state, sched: FastSchedule) -> FastSchedule:
        """Sample one job-level neighbor by swap, relocate, or small destroy-repair."""
        job_ids = [jid for jid in sched.assignments if sched.assignments[jid]]
        if not job_ids:
            return sched.clone()

        copy = sched.clone()
        move_roll = self.rng.random()

        if move_roll < 0.45 and len(job_ids) >= 2:
            j1, j2 = self.rng.sample(job_ids, 2)
            copy.remove_job(j1)
            copy.remove_job(j2)
            _insert_job_greedy(instance, instance.get_job(j2), copy, state)
            _insert_job_greedy(instance, instance.get_job(j1), copy, state)
            return copy

        if move_roll < 0.75:
            jid = self.rng.choice(job_ids)
            copy.remove_job(jid)
            _insert_job_greedy(instance, instance.get_job(jid), copy, state)
            return copy

        k = min(len(job_ids), max(1, int(round(len(job_ids) * 0.20))))
        destroyed = _destroy_random_jobs(copy, k, self.rng)
        for jid in destroyed:
            copy.remove_job(jid)
        if self.rng.random() < 0.5:
            _repair_random_order(instance, copy, state, destroyed, self.rng)
        else:
            _repair_regret_k(instance, copy, state, destroyed, self.rng)
        return copy

    def _improve(self, instance, state, sched, candidates) -> tuple[FastSchedule, float, list[dict]]:
        current_sched = sched.clone()
        current_Z = _fast_eval_Z(current_sched, instance, state)
        best_sched = current_sched.clone()
        best_Z = current_Z
        temperature = max(1.0, abs(current_Z) * self.initial_temperature_ratio)
        entries = []
        t_start = time.perf_counter()

        for it in range(self.max_iter):
            candidate_sched = self._neighbor(instance, state, current_sched)
            candidate_Z = _fast_eval_Z(candidate_sched, instance, state)
            delta = candidate_Z - current_Z

            accept = delta < -EPS
            if not accept and temperature > EPS:
                accept = self.rng.random() < math.exp(-delta / temperature)

            if accept:
                current_sched = candidate_sched
                current_Z = candidate_Z

            if current_Z < best_Z - EPS:
                best_Z = current_Z
                best_sched = current_sched.clone()

            entries.append({
                "iteration": it + 1,
                "current_Z": current_Z,
                "best_so_far_Z": best_Z,
                "temperature": temperature,
                "runtime_elapsed": time.perf_counter() - t_start,
            })
            temperature = max(1e-6, temperature * self.cooling_rate)

        return best_sched, best_Z, entries

    def _extract_decisions(
        self,
        sched: FastSchedule,
        instance: SLISPInstance,
        state: ScheduleState,
    ) -> list[tuple[int, int, int, int]]:
        return _extract_immediate_decisions(sched, instance, state, dispatch_mode="standard_projected")


# ═══════════════════════════════════════════════════════════════════════════════
# GA-Fast: Genetic Algorithm
# ═══════════════════════════════════════════════════════════════════════════════

class GAFast(_RollingHorizonMetaheuristic):
    """Genetic Algorithm using job permutations as chromosomes."""

    def __init__(
        self,
        horizon: int = 300,
        max_iter: int = 60,
        population_size: int = 16,
        crossover_rate: float = 0.85,
        mutation_rate: float = 0.20,
        elite_size: int = 2,
        seed: int = 42,
    ):
        super().__init__(horizon=horizon, max_iter=max_iter, seed=seed)
        self.population_size = max(4, population_size)
        self.crossover_rate = crossover_rate
        self.mutation_rate = mutation_rate
        self.elite_size = max(1, min(elite_size, self.population_size - 1))

    def _decode(self, instance, state, chromosome: list[int]) -> FastSchedule:
        return _greedy_construct(instance, state, chromosome, {}, self.rng)

    def _job_work(self, instance, jid: int) -> int:
        job = instance.get_job(jid)
        return sum(op.min_processing_time for op in job.operations)

    def _initial_population(self, instance, state, candidates: list[int]) -> list[list[int]]:
        edf_order = sorted(
            candidates,
            key=lambda jid: _effective_deadline(instance, instance.get_job(jid)),
        )
        spt_order = sorted(candidates, key=lambda jid: self._job_work(instance, jid))
        wspt_order = sorted(
            candidates,
            key=lambda jid: (
                self._job_work(instance, jid)
                / max(1e-9, instance.get_entity(instance.get_job(jid).entity_id).weight)
            ),
        )
        population = [edf_order, spt_order, wspt_order]
        while len(population) < self.population_size:
            chrom = list(candidates)
            self.rng.shuffle(chrom)
            population.append(chrom)
        return population[:self.population_size]

    def _evaluate_population(self, instance, state, population: list[list[int]]):
        evaluated = []
        for chrom in population:
            sched = self._decode(instance, state, chrom)
            z_value = _fast_eval_Z(sched, instance, state)
            evaluated.append((z_value, chrom, sched))
        evaluated.sort(key=lambda item: item[0])
        return evaluated

    def _tournament(self, evaluated, tournament_size: int = 3) -> list[int]:
        sample_size = min(tournament_size, len(evaluated))
        competitors = self.rng.sample(evaluated, sample_size)
        competitors.sort(key=lambda item: item[0])
        return list(competitors[0][1])

    def _order_crossover(self, parent_a: list[int], parent_b: list[int]) -> list[int]:
        n = len(parent_a)
        if n <= 2 or self.rng.random() > self.crossover_rate:
            return list(parent_a)

        left, right = sorted(self.rng.sample(range(n), 2))
        child: list[int | None] = [None] * n
        child[left:right + 1] = parent_a[left:right + 1]
        used = {gene for gene in child if gene is not None}
        fill = [gene for gene in parent_b if gene not in used]
        fill_idx = 0
        for idx in list(range(0, left)) + list(range(right + 1, n)):
            child[idx] = fill[fill_idx]
            fill_idx += 1
        return [int(gene) for gene in child if gene is not None]

    def _mutate(self, chromosome: list[int]) -> list[int]:
        chrom = list(chromosome)
        if len(chrom) < 2 or self.rng.random() > self.mutation_rate:
            return chrom
        if self.rng.random() < 0.5:
            i, j = self.rng.sample(range(len(chrom)), 2)
            chrom[i], chrom[j] = chrom[j], chrom[i]
        else:
            i, j = sorted(self.rng.sample(range(len(chrom)), 2))
            chrom[i:j + 1] = reversed(chrom[i:j + 1])
        return chrom

    def _improve(self, instance, state, sched, candidates) -> tuple[FastSchedule, float, list[dict]]:
        if not candidates:
            return sched, _fast_eval_Z(sched, instance, state), []

        population = self._initial_population(instance, state, candidates)
        evaluated = self._evaluate_population(instance, state, population)
        best_Z, best_chrom, best_sched = evaluated[0]
        best_sched = best_sched.clone()
        entries = []
        t_start = time.perf_counter()

        for it in range(self.max_iter):
            next_population = [list(chrom) for _z, chrom, _sched in evaluated[:self.elite_size]]
            while len(next_population) < self.population_size:
                parent_a = self._tournament(evaluated)
                parent_b = self._tournament(evaluated)
                child = self._order_crossover(parent_a, parent_b)
                child = self._mutate(child)
                next_population.append(child)

            evaluated = self._evaluate_population(instance, state, next_population)
            generation_best_Z, generation_best_chrom, generation_best_sched = evaluated[0]
            if generation_best_Z < best_Z - EPS:
                best_Z = generation_best_Z
                best_chrom = list(generation_best_chrom)
                best_sched = generation_best_sched.clone()

            entries.append({
                "iteration": it + 1,
                "current_Z": generation_best_Z,
                "best_so_far_Z": best_Z,
                "runtime_elapsed": time.perf_counter() - t_start,
            })

        _ = best_chrom  # retained for debugging symmetry with convergence data
        return best_sched, best_Z, entries

    def _extract_decisions(
        self,
        sched: FastSchedule,
        instance: SLISPInstance,
        state: ScheduleState,
    ) -> list[tuple[int, int, int, int]]:
        return _extract_immediate_decisions(sched, instance, state, dispatch_mode="standard_projected")


# ═══════════════════════════════════════════════════════════════════════════════
# Factory functions
# ═══════════════════════════════════════════════════════════════════════════════

def run_ils_fast(horizon: int = 300, max_iter: int = 100, seed: int = 42) -> ILSFast:
    return ILSFast(horizon=horizon, max_iter=max_iter, seed=seed)


def run_vns_fast(horizon: int = 300, max_iter: int = 100, seed: int = 42) -> VNSFast:
    return VNSFast(horizon=horizon, max_iter=max_iter, seed=seed)


def run_ts_fast(horizon: int = 300, max_iter: int = 100, tabu_tenure: int = 7,
                seed: int = 42) -> TSFast:
    return TSFast(horizon=horizon, max_iter=max_iter, tabu_tenure=tabu_tenure, seed=seed)


def run_sa_fast(
    horizon: int = 300,
    max_iter: int = 100,
    initial_temperature_ratio: float = 0.10,
    cooling_rate: float = 0.95,
    seed: int = 42,
) -> SAFast:
    return SAFast(
        horizon=horizon,
        max_iter=max_iter,
        initial_temperature_ratio=initial_temperature_ratio,
        cooling_rate=cooling_rate,
        seed=seed,
    )


def run_ga_fast(
    horizon: int = 300,
    max_iter: int = 60,
    population_size: int = 16,
    crossover_rate: float = 0.85,
    mutation_rate: float = 0.20,
    elite_size: int = 2,
    seed: int = 42,
) -> GAFast:
    return GAFast(
        horizon=horizon,
        max_iter=max_iter,
        population_size=population_size,
        crossover_rate=crossover_rate,
        mutation_rate=mutation_rate,
        elite_size=elite_size,
        seed=seed,
    )
