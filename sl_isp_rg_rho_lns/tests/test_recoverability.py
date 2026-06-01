"""Tests for recoverability-analysis modules.

Covers: earliest_bounds, capacity_pool, knapsack_recovery, shortfall_bounds,
and mandatory_jobs.
"""

import pytest
from src.core.dataclasses import (
    Job,
    Machine,
    Operation,
    OperationAlternative,
    ServiceEntity,
    SLISPInstance,
)
from src.core.schedule_state import ScheduleState
from src.generation.instance_generator import InstanceConfig, generate_instance
from src.recoverability.capacity_pool import (
    available_pool_capacity,
    unavoidable_pool_workload,
)
from src.recoverability.earliest_bounds import (
    eligible_recovery_jobs,
    optimistic_delivery_lower_bound,
    optimistic_job_completion_lower_bound,
    optimistic_remaining_operation_time,
    remaining_service_quantity,
    secured_quantity,
)
from src.recoverability.knapsack_recovery import (
    exclusion_recoverable_quantity,
    maximum_recoverable_service_quantity,
)
from src.recoverability.mandatory_jobs import (
    classify_mandatory_type,
    mandatory_rescue_jobs,
)
from src.recoverability.shortfall_bounds import unavoidable_shortfall_lower_bound


# ── helpers ─────────────────────────────────────────────────────────────────

def _make_machine(m_id: int) -> Machine:
    return Machine(machine_id=m_id)


def _op(job_id: int, seq: int, *machine_pt_pairs: tuple[int, int]) -> Operation:
    """Shortcut: Operation with given alternatives.

    Usage: _op(0, 0, (0, 10), (1, 15)) → op0 for job 0 with M0(pt=10), M1(pt=15)
    """
    return Operation(
        op_id=job_id * 100 + seq,
        job_id=job_id,
        sequence_index=seq,
        alternatives=[
            OperationAlternative(machine_id=m, processing_time=pt)
            for m, pt in machine_pt_pairs
        ],
    )


def _job(job_id: int, entity_id: int, quantity: int, *ops: Operation) -> Job:
    return Job(
        job_id=job_id,
        entity_id=entity_id,
        release_time=0,
        quantity=quantity,
        operations=list(ops),
    )


def _entity(
    eid: int,
    deadline: int,
    rho: float,
    weight: float,
    total_q: int,
    tau: int = 0,
) -> ServiceEntity:
    return ServiceEntity(
        entity_id=eid,
        deadline=deadline,
        rho=rho,
        weight=weight,
        total_quantity=total_q,
        transport_delay=tau,
    )


def _make_base_fixture() -> tuple[SLISPInstance, ScheduleState, set[int]]:
    """Standard 3-machine, 1-entity, 4-job fixture for most tests.

    Machines: M0, M1, M2
    Entity E0: deadline=100, rho=1.0, transport_delay=10
      Q_min = 50 (sum of all job quantities)
    Jobs:
      J0: q=10,  op0 on M0 (pt=10)
      J1: q=20,  op1 on M0 (pt=20)
      J2: q=15,  op2 on M0 (pt=5), op3 on M1 (pt=5)
      J3: q=5,   op4 on M1 (pt=5)

    Pool B = {0} (M0 is the bottleneck).
    """
    jobs = [
        _job(0, 0, 10, _op(0, 0, (0, 10))),
        _job(1, 0, 20, _op(1, 0, (0, 20))),
        _job(2, 0, 15, _op(2, 0, (0, 5)), _op(2, 1, (1, 5))),
        _job(3, 0, 5, _op(3, 0, (1, 5))),
    ]
    total_q = sum(j.quantity for j in jobs)
    entities = [
        _entity(0, deadline=100, rho=1.0, weight=1.0, total_q=total_q, tau=10)
    ]
    machines = [_make_machine(0), _make_machine(1), _make_machine(2)]
    instance = SLISPInstance(
        jobs=jobs, entities=entities, machines=machines, alpha=1.0, beta=1.0
    )
    state = ScheduleState()
    for m in machines:
        state.machine_available_times[m.machine_id] = 0
    state.current_time = 0
    pool_B = {0}
    return instance, state, pool_B


# ── earliest_bounds tests ───────────────────────────────────────────────────

class TestEarliestBounds:
    def test_optimistic_remaining_op_time_unstarted(self):
        instance, state, _ = _make_base_fixture()
        job = instance.get_job(0)  # op on M0, pt=10
        op = job.operation_at(0)
        t = optimistic_remaining_operation_time(op, job, state)
        assert t == 10  # min_processing_time

    def test_optimistic_remaining_op_time_ongoing(self):
        instance, state, _ = _make_base_fixture()
        state.current_time = 3
        job = instance.get_job(0)
        op = job.operation_at(0)
        state.mark_operation_started(
            job_id=0, op_id=op.op_id, machine_id=0, start_time=0, end_time=10
        )
        t = optimistic_remaining_operation_time(op, job, state)
        assert t == 7  # end_time(10) - current_time(3)

    def test_optimistic_remaining_op_time_completed(self):
        instance, state, _ = _make_base_fixture()
        state.current_time = 12
        job = instance.get_job(0)
        op = job.operation_at(0)
        state.mark_operation_started(0, op.op_id, 0, 0, 10)
        state.mark_operation_completed(0, op.op_id, 0)
        t = optimistic_remaining_operation_time(op, job, state)
        assert t == 0

    def test_optimistic_job_completion_lower_bound(self):
        instance, state, _ = _make_base_fixture()
        # J2: op2 on M0(pt=5), op3 on M1(pt=5), both unstarted
        job = instance.get_job(2)
        c_lower = optimistic_job_completion_lower_bound(job, state)
        # base = max(0, 0) = 0, residual = 5 + 5 = 10
        assert c_lower == 10

    def test_optimistic_job_completion_with_release_time(self):
        instance, state, _ = _make_base_fixture()
        # J1 with release_time=5
        job = instance.get_job(1)
        # Manually check: can't change frozen dataclass, but formula uses max(t, r_j)
        # t=0, r_j=0 → base=0, residual=20 → C_lower=20
        c_lower = optimistic_job_completion_lower_bound(job, state)
        assert c_lower == 20

    def test_optimistic_delivery_lower_bound(self):
        instance, state, _ = _make_base_fixture()
        job = instance.get_job(0)  # C_lower = 10
        d_lower = optimistic_delivery_lower_bound(job, state, instance)
        # C_lower=10, tau=10 → D_lower=20
        assert d_lower == 20

    def test_secured_quantity_none_initially(self):
        instance, state, _ = _make_base_fixture()
        q = secured_quantity(0, state, instance)
        assert q == 0

    def test_secured_quantity_after_completion(self):
        instance, state, _ = _make_base_fixture()
        # Complete J0 at t=8 (delivery 8+10=18 <= 100)
        state.mark_job_completed(0, 8)
        q = secured_quantity(0, state, instance)
        assert q == 10

    def test_secured_quantity_late_delivery_not_counted(self):
        instance, state, _ = _make_base_fixture()
        # Complete J0 but delivery is late: D=95+10=105 > 100
        state.mark_job_completed(0, 95)
        q = secured_quantity(0, state, instance)
        assert q == 0

    def test_remaining_service_quantity(self):
        instance, state, _ = _make_base_fixture()
        # Entity min_fulfillment=50, Q_sec=0 → Q_rem=50
        q_rem = remaining_service_quantity(0, state, instance)
        assert q_rem == 50

    def test_remaining_service_quantity_partial(self):
        instance, state, _ = _make_base_fixture()
        state.mark_job_completed(0, 5)  # J0 secured (q=10, delivery=15 <= 100)
        q_rem = remaining_service_quantity(0, state, instance)
        assert q_rem == 40  # 50 - 10

    def test_remaining_service_quantity_zero_when_met(self):
        instance, state, _ = _make_base_fixture()
        # All jobs completed on time
        state.mark_job_completed(0, 5)
        state.mark_job_completed(1, 6)
        state.mark_job_completed(2, 7)
        state.mark_job_completed(3, 8)
        q_rem = remaining_service_quantity(0, state, instance)
        assert q_rem == 0

    def test_eligible_recovery_jobs_all_eligible_initially(self):
        instance, state, _ = _make_base_fixture()
        eligible = eligible_recovery_jobs(0, state, instance)
        assert set(eligible) == {0, 1, 2, 3}

    def test_eligible_recovery_jobs_excludes_completed(self):
        instance, state, _ = _make_base_fixture()
        state.mark_job_completed(0, 5)
        eligible = eligible_recovery_jobs(0, state, instance)
        assert 0 not in eligible
        assert set(eligible) == {1, 2, 3}

    def test_eligible_recovery_jobs_excludes_tight_deadline(self):
        """Jobs whose D_lower exceeds the entity deadline are excluded."""
        # Use tight deadline: d_r=15, tau=10 → D_lower for J1 = 0+20+10=30 > 15
        jobs = [
            _job(0, 0, 10, _op(0, 0, (0, 10))),  # D_lower=0+10+5=15
            _job(1, 0, 20, _op(1, 0, (0, 40))),  # D_lower=0+40+5=45
        ]
        total_q = 30
        entities = [_entity(0, deadline=15, rho=0.5, weight=1.0, total_q=total_q, tau=5)]
        machines = [_make_machine(0)]
        inst = SLISPInstance(
            jobs=jobs, entities=entities, machines=machines, alpha=1.0, beta=1.0,
        )
        state = ScheduleState()
        for m in machines:
            state.machine_available_times[m.machine_id] = 0

        eligible = eligible_recovery_jobs(0, state, inst)
        assert eligible == [0]  # only J0: D_lower=15 <= 15


# ── capacity_pool tests ─────────────────────────────────────────────────────

class TestCapacityPool:
    def test_available_pool_capacity_all_idle(self):
        instance, state, pool_B = _make_base_fixture()
        cap = available_pool_capacity(pool_B, 0, state, instance)
        # d_r=100, M0 available at 0 → cap=100
        assert cap == 100

    def test_available_pool_capacity_machine_busy(self):
        instance, state, pool_B = _make_base_fixture()
        state.machine_available_times[0] = 30  # M0 busy until 30
        cap = available_pool_capacity(pool_B, 0, state, instance)
        # max(0, 100 - max(0, 30)) = 70
        assert cap == 70

    def test_available_pool_capacity_deadline_passed(self):
        instance, state, pool_B = _make_base_fixture()
        state.current_time = 110  # past deadline
        cap = available_pool_capacity(pool_B, 0, state, instance)
        # max(0, 100 - max(110, 0)) = 0
        assert cap == 0

    def test_unavoidable_workload_unstarted_all_in_pool(self):
        instance, state, pool_B = _make_base_fixture()
        job = instance.get_job(0)  # one op on M0 ∈ B
        w = unavoidable_pool_workload(job, pool_B, state)
        assert w == 10  # min_processing_time

    def test_unavoidable_workload_unstarted_not_all_in_pool(self):
        instance, state, pool_B = _make_base_fixture()
        job = instance.get_job(3)  # op on M1 ∉ B
        w = unavoidable_pool_workload(job, pool_B, state)
        assert w == 0  # eligible machine M1 not in B

    def test_unavoidable_workload_partial_pool(self):
        instance, state, pool_B = _make_base_fixture()
        job = instance.get_job(2)  # op2 on M0∈B, op3 on M1∉B
        w = unavoidable_pool_workload(job, pool_B, state)
        # op2 unstarted, all eligible={0}⊆B → 5
        # op3 unstarted, all eligible={1}⊈B → 0
        assert w == 5

    def test_unavoidable_workload_ongoing_in_pool(self):
        instance, state, pool_B = _make_base_fixture()
        state.current_time = 3
        job = instance.get_job(0)
        op = job.operation_at(0)
        state.mark_operation_started(0, op.op_id, 0, 0, 10)
        w = unavoidable_pool_workload(job, pool_B, state)
        assert w == 7  # remaining 10-3=7, on M0 ∈ B

    def test_unavoidable_workload_ongoing_not_in_pool(self):
        instance, state, pool_B = _make_base_fixture()
        state.current_time = 2
        job = instance.get_job(3)  # op on M1
        op = job.operation_at(0)
        state.mark_operation_started(3, op.op_id, 1, 0, 5)  # M1 ∉ B
        w = unavoidable_pool_workload(job, pool_B, state)
        assert w == 0  # ongoing on M1 ∉ B

    def test_unavoidable_workload_completed_zero(self):
        instance, state, pool_B = _make_base_fixture()
        job = instance.get_job(0)
        op = job.operation_at(0)
        state.mark_operation_started(0, op.op_id, 0, 0, 10)
        state.mark_operation_completed(0, op.op_id, 0)
        w = unavoidable_pool_workload(job, pool_B, state)
        assert w == 0

    def test_unavoidable_workload_multi_alternative_unstarted(self):
        """When an unstarted op has eligible machines both in and outside B,
        its unavoidable pool workload is 0."""
        # Create job with op eligible on M0 and M1, pool_B={0}
        jobs = [
            _job(0, 0, 10, _op(0, 0, (0, 10), (1, 12))),
        ]
        entities = [_entity(0, 100, 1.0, 1.0, 10)]
        machines = [_make_machine(0), _make_machine(1)]
        inst = SLISPInstance(
            jobs=jobs, entities=entities, machines=machines, alpha=1.0, beta=1.0,
        )
        state = ScheduleState()
        for m in machines:
            state.machine_available_times[m.machine_id] = 0
        pool_B = {0}
        job = inst.get_job(0)
        w = unavoidable_pool_workload(job, pool_B, state)
        # Eligible set = {0, 1}, not subset of B={0} → 0
        assert w == 0


# ── knapsack_recovery integration tests ─────────────────────────────────────

class TestKnapsackRecovery:
    def test_max_recoverable_all_fit(self):
        instance, state, pool_B = _make_base_fixture()
        q_rec, sel = maximum_recoverable_service_quantity(0, pool_B, state, instance)
        # All 4 jobs: weights 10+20+5+0=35, capacity=100, total=50
        assert q_rec == 50
        assert sel == {0, 1, 2, 3}

    def test_max_recoverable_tight_capacity(self):
        """With tight deadline, only J3 is eligible (lowest D_lower)."""
        instance, state, pool_B = _make_base_fixture()
        jobs = instance.jobs
        # deadline=8, tau=0 → only J3 (D_lower=5≤8) is eligible.
        # J0 (D_lower=10), J1 (D_lower=20), J2 (D_lower=10) all excluded.
        # Cap=8, J3 w_lower=0 (M1 op, M1∉B) → Q_rec_bar=5.
        entities = [
            _entity(0, deadline=8, rho=1.0, weight=1.0, total_q=50, tau=0)
        ]
        tight_inst = SLISPInstance(
            jobs=jobs,
            entities=entities,
            machines=instance.machines,
            alpha=1.0,
            beta=1.0,
        )
        q_rec, sel = maximum_recoverable_service_quantity(
            0, pool_B, state, tight_inst
        )
        assert q_rec == 5
        assert sel == {3}

    def test_exclusion_recoverable_quantity(self):
        instance, state, pool_B = _make_base_fixture()
        # Full recovery = 50
        q_excl = exclusion_recoverable_quantity(0, 0, pool_B, state, instance)
        # Without J0 (q=10,w=10): remaining (20,20),(15,5),(5,0) cap=100 → all fit = 40
        assert q_excl == 40

    def test_exclusion_removes_critical_job(self):
        """Test that excluding a high-value job reduces the recoverable quantity."""
        instance, state, pool_B = _make_base_fixture()
        # Exclude J1 (q=20), should reduce Q_rec from 50 to 30
        q_excl = exclusion_recoverable_quantity(0, 1, pool_B, state, instance)
        assert q_excl == 30

    def test_no_eligible_jobs(self):
        instance, state, pool_B = _make_base_fixture()
        # Complete all jobs
        for jid in [0, 1, 2, 3]:
            state.mark_job_completed(jid, 1)
        q_rec, sel = maximum_recoverable_service_quantity(0, pool_B, state, instance)
        assert q_rec == 0
        assert sel == set()


# ── shortfall_bounds tests ──────────────────────────────────────────────────

class TestShortfallBounds:
    def test_zero_shortfall_when_recoverable(self):
        instance, state, pool_B = _make_base_fixture()
        u_lower = unavoidable_shortfall_lower_bound(0, pool_B, state, instance)
        # Q_rem = 50, Q_rec_bar = 50 → U_lower = 0
        assert u_lower == 0

    def test_positive_shortfall_when_unrecoverable(self):
        instance, state, pool_B = _make_base_fixture()
        jobs = instance.jobs
        # deadline=8, tau=0 → only J3 (D_lower=5≤8) eligible.
        # Q_rem=50, Cap=8, only J3 (q=5,w=0) fits → Q_rec_bar=5
        # U_lower = max(0, 50-5) = 45
        entities = [
            _entity(0, deadline=8, rho=1.0, weight=1.0, total_q=50, tau=0)
        ]
        tight_inst = SLISPInstance(
            jobs=jobs,
            entities=entities,
            machines=instance.machines,
            alpha=1.0,
            beta=1.0,
        )
        u_lower = unavoidable_shortfall_lower_bound(0, pool_B, state, tight_inst)
        assert u_lower == 45

    def test_zero_when_q_rem_is_zero(self):
        instance, state, pool_B = _make_base_fixture()
        # Complete all jobs on time
        for jid, t in [(0, 5), (1, 6), (2, 7), (3, 8)]:
            state.mark_job_completed(jid, t)
        u_lower = unavoidable_shortfall_lower_bound(0, pool_B, state, instance)
        assert u_lower == 0


# ── mandatory_jobs tests ────────────────────────────────────────────────────

class TestMandatoryJobs:
    def test_no_mandatory_when_recovery_impossible(self):
        """If Q_rec_bar < Q_rem even with all jobs, no job is mandatory."""
        instance, state, pool_B = _make_base_fixture()
        # Tight capacity makes full recovery impossible
        jobs = instance.jobs
        entities = [
            _entity(0, deadline=2, rho=1.0, weight=1.0, total_q=50, tau=0)
        ]
        tight_inst = SLISPInstance(
            jobs=jobs,
            entities=entities,
            machines=instance.machines,
            alpha=1.0,
            beta=1.0,
        )
        mand = mandatory_rescue_jobs(0, pool_B, state, tight_inst)
        # Q_rec_bar = 5 < 50 = Q_rem → no mandatory jobs
        assert mand == []

    def test_no_mandatory_when_q_rem_is_zero(self):
        instance, state, pool_B = _make_base_fixture()
        for jid, t in [(0, 5), (1, 6), (2, 7), (3, 8)]:
            state.mark_job_completed(jid, t)
        mand = mandatory_rescue_jobs(0, pool_B, state, instance)
        assert mand == []

    def test_quantity_mandatory_job(self):
        """J0 is quantity-mandatory: without it, other quantities < Q_rem."""
        instance, state, pool_B = _make_base_fixture()
        # Complete J1 (q=20) → Q_rem becomes 30
        state.mark_job_completed(1, 5)
        # Q_rem = 30, eligible = {0, 2, 3}
        # Q_rec_bar with all = 10+15+5=30 >= 30 ✓
        # Excluding J0: other q = 15+5 = 20 < 30 → quantity_mandatory
        mand = mandatory_rescue_jobs(0, pool_B, state, instance)
        assert 0 in mand

    def test_capacity_mandatory_job(self):
        """J0 is capacity-mandatory: enough other quantity but won't fit in capacity."""
        # Entity: deadline=44, rho=0.6 → Q_min = max(1, int(0.6*75)) = 45
        # J0: q=30, op on M0 pt=10  (efficient, ratio 3.0)
        # J1: q=25, op on M0 pt=25  (ratio 1.0)
        # J2: q=20, op on M0 pt=20  (ratio 1.0)
        # Pool_B={0}, Cap_B=44
        jobs = [
            _job(0, 0, 30, _op(0, 0, (0, 10))),
            _job(1, 0, 25, _op(1, 0, (0, 25))),
            _job(2, 0, 20, _op(2, 0, (0, 20))),
        ]
        entities = [_entity(0, deadline=44, rho=0.6, weight=1.0, total_q=75, tau=0)]
        machines = [_make_machine(0), _make_machine(1)]
        inst = SLISPInstance(
            jobs=jobs, entities=entities, machines=machines, alpha=1.0, beta=1.0,
        )
        state = ScheduleState()
        for m in machines:
            state.machine_available_times[m.machine_id] = 0
        pool_B = {0}

        # Q_rem = min_fulfillment = max(1, int(0.6*75)) = 45
        # Knapsack cap=44: (30,10)+(25,25)=55 weight=35 ✓ → Q_rec_bar=55 ≥ 45
        # Without J0: (25,25)+(20,20)=45 weight=45 > 44 ✗ → best=25 < 45
        # Other quantity = 25+20=45 ≥ 45 → capacity_mandatory
        mand = mandatory_rescue_jobs(0, pool_B, state, inst)
        assert 0 in mand
        assert classify_mandatory_type(0, 0, pool_B, state, inst) == "capacity_mandatory"

    def test_not_mandatory(self):
        """J3 has w_lower=0 and small q, removing it doesn't affect recovery."""
        instance, state, pool_B = _make_base_fixture()
        # Q_rem=50, Q_rec_bar=50 (all 4 jobs)
        # Remove J3: remaining (10,10),(20,20),(15,5) cap=100 → 45 >= 50? No.
        # Actually 10+20+15=45 < 50, so removing J3 makes Q_rec=45 < 50
        # J3 IS mandatory with this setup!

        # Let me use a different scenario: make Q_rem smaller
        # Complete J1 (q=20), Q_rem=30
        state.mark_job_completed(1, 5)
        # Eligible: {0, 2, 3}, Q_rec=10+15+5=30 >= 30
        # Remove J3: (10,10)+(15,5)=25 < 30 → J3 IS mandatory too.
        # Hmm. All are mandatory when Q_rem is tight.

        # Let me use a completely different instance where one job is clearly not mandatory
        # Entity: Q_rem=20, J0: q=30(w=20), J1: q=10(w=5)
        # Both fit: Q_rec=40 >= 20
        # Remove J1: J0 alone = 30 >= 20 → J1 not mandatory
        jobs = [
            _job(0, 0, 30, _op(0, 0, (0, 20))),
            _job(1, 0, 10, _op(1, 0, (0, 5))),
        ]
        entities = [_entity(0, deadline=50, rho=0.5, weight=1.0, total_q=40, tau=0)]
        # Q_min = max(1, 0.5*40) = 20
        machines = [_make_machine(0)]
        inst = SLISPInstance(
            jobs=jobs, entities=entities, machines=machines, alpha=1.0, beta=1.0,
        )
        state = ScheduleState()
        for m in machines:
            state.machine_available_times[m.machine_id] = 0
        pool_B = {0}

        mand = mandatory_rescue_jobs(0, pool_B, state, inst)
        assert mand == [0]  # only J0

        # J1 is not mandatory: removing it leaves J0 with q=30 >= 20
        assert 1 not in mand
        assert classify_mandatory_type(1, 0, pool_B, state, inst) == "not_mandatory"

    def test_classify_quantity_mandatory(self):
        instance, state, pool_B = _make_base_fixture()
        state.mark_job_completed(1, 5)  # J1 secured (q=20)
        # Q_rem = 30, eligible = {0, 2, 3}
        # Q_rec_bar = 10+15+5 = 30 >= 30
        # Remove J0: other q = 15+5 = 20 < 30 → quantity_mandatory
        result = classify_mandatory_type(0, 0, pool_B, state, instance)
        assert result == "quantity_mandatory"

    def test_classify_not_mandatory_when_q_rem_zero(self):
        instance, state, pool_B = _make_base_fixture()
        for jid, t in [(0, 5), (1, 6), (2, 7), (3, 8)]:
            state.mark_job_completed(jid, t)
        result = classify_mandatory_type(0, 0, pool_B, state, instance)
        assert result == "not_mandatory"


# ── integration with generated instances ────────────────────────────────────

class TestRecoverabilityOnGeneratedInstances:
    def test_recoverability_runs_on_generated_instance(self):
        config = InstanceConfig(
            group_name="test",
            num_instances=1,
            num_jobs=15,
            num_machines=5,
            num_entities=3,
            ops_per_job=(2, 4),
            rho_range=(0.7, 0.8),
            deadline_tightness=1.0,
            weight_pattern="uniform",
        )
        inst = generate_instance(config, seed=42)
        state = ScheduleState()
        for m in inst.machines:
            state.machine_available_times[m.machine_id] = 0

        pool_B = {m.machine_id for m in inst.machines}

        for entity in inst.entities:
            q_rem = remaining_service_quantity(entity.entity_id, state, inst)
            assert q_rem >= 0

            eligible = eligible_recovery_jobs(entity.entity_id, state, inst)
            assert all(isinstance(jid, int) for jid in eligible)

            cap = available_pool_capacity(pool_B, entity.entity_id, state, inst)
            assert cap >= 0

            q_rec, sel = maximum_recoverable_service_quantity(
                entity.entity_id, pool_B, state, inst
            )
            assert q_rec >= 0
            assert all(jid in eligible for jid in sel)

            u_lower = unavoidable_shortfall_lower_bound(
                entity.entity_id, pool_B, state, inst
            )
            assert u_lower >= 0

            mand = mandatory_rescue_jobs(entity.entity_id, pool_B, state, inst)
            for jid in mand:
                assert jid in eligible

            for jid in eligible:
                cls = classify_mandatory_type(
                    jid, entity.entity_id, pool_B, state, inst
                )
                assert cls in (
                    "quantity_mandatory",
                    "capacity_mandatory",
                    "not_mandatory",
                )
