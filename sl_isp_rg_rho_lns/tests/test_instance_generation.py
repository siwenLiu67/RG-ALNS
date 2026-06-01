"""Tests for instance generation and validation."""

import pytest
from src.core.dataclasses import (
    Job,
    Machine,
    Operation,
    OperationAlternative,
    ServiceEntity,
    SLISPInstance,
)
from src.core.instance import instance_from_dict, instance_to_dict
from src.generation.instance_generator import (
    BENCHMARK_CONFIGS,
    InstanceConfig,
    generate_instance,
    generate_instance_group,
)
from src.generation.scenario_builder import build_dynamic_scenario


class TestDataClasses:
    """Unit tests for core data classes."""

    def test_operation_alternative_valid(self):
        alt = OperationAlternative(machine_id=1, processing_time=10)
        assert alt.machine_id == 1
        assert alt.processing_time == 10

    def test_operation_alternative_rejects_non_positive_time(self):
        with pytest.raises(ValueError):
            OperationAlternative(machine_id=1, processing_time=0)
        with pytest.raises(ValueError):
            OperationAlternative(machine_id=1, processing_time=-5)

    def test_operation_requires_alternatives(self):
        with pytest.raises(ValueError):
            Operation(op_id=0, job_id=0, sequence_index=0, alternatives=[])

    def test_operation_duplicate_machines(self):
        with pytest.raises(ValueError):
            Operation(
                op_id=0,
                job_id=0,
                sequence_index=0,
                alternatives=[
                    OperationAlternative(machine_id=1, processing_time=10),
                    OperationAlternative(machine_id=1, processing_time=12),
                ],
            )

    def test_operation_eligible_machines(self):
        op = Operation(
            op_id=0,
            job_id=0,
            sequence_index=0,
            alternatives=[
                OperationAlternative(machine_id=1, processing_time=10),
                OperationAlternative(machine_id=3, processing_time=15),
            ],
        )
        assert op.eligible_machines == [1, 3]
        assert op.processing_time_on(1) == 10
        assert op.min_processing_time == 10

    def test_operation_processing_time_unknown_machine(self):
        op = Operation(
            op_id=0,
            job_id=0,
            sequence_index=0,
            alternatives=[OperationAlternative(machine_id=1, processing_time=10)],
        )
        with pytest.raises(KeyError):
            op.processing_time_on(99)

    def test_job_requires_operations(self):
        with pytest.raises(ValueError):
            Job(job_id=0, entity_id=0, release_time=0, quantity=5, operations=[])

    def test_job_quantity_must_be_positive(self):
        op = Operation(
            op_id=0,
            job_id=0,
            sequence_index=0,
            alternatives=[OperationAlternative(machine_id=0, processing_time=10)],
        )
        with pytest.raises(ValueError):
            Job(job_id=0, entity_id=0, release_time=0, quantity=0, operations=[op])

    def test_job_sequence_index_mismatch(self):
        op = Operation(
            op_id=0,
            job_id=0,
            sequence_index=1,  # should be 0
            alternatives=[OperationAlternative(machine_id=0, processing_time=10)],
        )
        with pytest.raises(ValueError):
            Job(job_id=0, entity_id=0, release_time=0, quantity=5, operations=[op])

    def test_service_entity_min_fulfillment(self):
        entity = ServiceEntity(
            entity_id=0,
            deadline=100,
            rho=0.8,
            weight=2.0,
            total_quantity=50,
            transport_delay=10,
        )
        assert entity.min_fulfillment == 40

    def test_service_entity_rho_range(self):
        with pytest.raises(ValueError):
            ServiceEntity(
                entity_id=0,
                deadline=100,
                rho=0.0,
                weight=1.0,
                total_quantity=50,
                transport_delay=0,
            )
        with pytest.raises(ValueError):
            ServiceEntity(
                entity_id=0,
                deadline=100,
                rho=1.5,
                weight=1.0,
                total_quantity=50,
                transport_delay=0,
            )

    def test_instance_rejects_unknown_entity(self):
        op = Operation(
            op_id=0,
            job_id=0,
            sequence_index=0,
            alternatives=[OperationAlternative(machine_id=0, processing_time=10)],
        )
        job = Job(job_id=0, entity_id=99, release_time=0, quantity=5, operations=[op])
        entity = ServiceEntity(
            entity_id=0, deadline=100, rho=0.8, weight=1.0,
            total_quantity=5, transport_delay=0,
        )
        with pytest.raises(ValueError):
            SLISPInstance(
                jobs=[job],
                entities=[entity],
                machines=[Machine(machine_id=0)],
                alpha=1.0,
                beta=1.0,
            )


class TestInstanceGenerator:
    """Tests for the instance generator."""

    def test_generate_small_instance(self):
        config = InstanceConfig(
            group_name="test",
            num_instances=1,
            num_jobs=10,
            num_machines=5,
            num_entities=3,
            ops_per_job=(2, 4),
            rho_range=(0.7, 0.8),
            deadline_tightness=1.0,
            weight_pattern="uniform",
        )
        inst = generate_instance(config, seed=42)
        assert inst.num_jobs == 10
        assert inst.num_machines == 5
        assert inst.num_entities == 3

    def test_generate_instance_consistency(self):
        """Each entity's total_quantity must equal the sum of its jobs' quantities."""
        config = InstanceConfig(
            group_name="test",
            num_instances=1,
            num_jobs=15,
            num_machines=5,
            num_entities=3,
            ops_per_job=(2, 4),
            rho_range=(0.5, 0.9),
            deadline_tightness=1.0,
            weight_pattern="mild",
        )
        inst = generate_instance(config, seed=123)

        for entity in inst.entities:
            jobs = inst.jobs_of_entity(entity.entity_id)
            total_q = sum(j.quantity for j in jobs)
            assert entity.total_quantity == total_q, (
                f"Entity {entity.entity_id}: total_quantity={entity.total_quantity} "
                f"but sum of job quantities={total_q}"
            )

    def test_default_deadline_generation_keeps_common_effective_due_date(self):
        config = InstanceConfig(
            group_name="test",
            num_instances=1,
            num_jobs=20,
            num_machines=5,
            num_entities=4,
            ops_per_job=(2, 3),
            rho_range=(0.7, 0.8),
            deadline_tightness=1.0,
            weight_pattern="uniform",
            transport_delay_range=(10, 40),
        )
        inst = generate_instance(config, seed=20260526)

        effective_due_dates = {
            entity.deadline - entity.transport_delay for entity in inst.entities
        }
        assert len(effective_due_dates) == 1

    def test_effective_due_spread_generates_heterogeneous_cutoffs(self):
        config = InstanceConfig(
            group_name="test",
            num_instances=1,
            num_jobs=20,
            num_machines=5,
            num_entities=4,
            ops_per_job=(2, 3),
            rho_range=(0.7, 0.8),
            deadline_tightness=1.0,
            weight_pattern="uniform",
            transport_delay_range=(10, 40),
            effective_due_spread=0.6,
        )
        inst = generate_instance(config, seed=20260526)

        effective_due_dates = [
            entity.deadline - entity.transport_delay for entity in inst.entities
        ]
        assert len(set(effective_due_dates)) > 1
        assert effective_due_dates == sorted(effective_due_dates)
        assert inst.metadata["effective_due_values"] == effective_due_dates

    def test_effective_due_multipliers_override_spread(self):
        config = InstanceConfig(
            group_name="test",
            num_instances=1,
            num_jobs=10,
            num_machines=4,
            num_entities=3,
            ops_per_job=(2, 3),
            rho_range=(0.7, 0.8),
            deadline_tightness=1.0,
            weight_pattern="uniform",
            transport_delay_range=(10, 40),
            effective_due_spread=0.8,
            effective_due_multipliers=(0.7, 1.0, 1.3),
        )
        inst = generate_instance(config, seed=20260526)

        effective_due_dates = [
            entity.deadline - entity.transport_delay for entity in inst.entities
        ]
        ref_completion = int(
            inst.metadata["ref_makespan"] * config.deadline_tightness
        )
        assert effective_due_dates == [
            max(1, int(round(ref_completion * multiplier)))
            for multiplier in config.effective_due_multipliers
        ]

    def test_pilot_config_passes_effective_due_spread(self):
        from src.experiments.run_pilot_benchmark import _build_instance_config

        pressure_cfg = {
            "num_jobs": 20,
            "num_machines": 5,
            "num_entities": 4,
            "ops_per_job": [2, 3],
            "rho_range": [0.7, 0.8],
            "deadline_tightness": 0.8,
            "weight_pattern": "mild",
            "transport_delay_range": [10, 40],
            "effective_due_spread": 0.6,
        }

        config = _build_instance_config(pressure_cfg, seed=42, idx=0)

        assert config.effective_due_spread == 0.6

    def test_pilot_combination_overrides_entity_count_and_due_spread(self):
        from src.experiments.run_pilot_benchmark import _merge_combination_config

        pressure_cfg = {
            "num_jobs": 20,
            "num_machines": 5,
            "num_entities": 3,
            "effective_due_spread": 0.3,
        }
        combo = {
            "num_jobs": 80,
            "num_machines": 10,
            "num_entities": 5,
            "effective_due_spread": 0.7,
        }

        merged = _merge_combination_config(pressure_cfg, combo)

        assert merged["num_jobs"] == 80
        assert merged["num_machines"] == 10
        assert merged["num_entities"] == 5
        assert merged["effective_due_spread"] == 0.7

    def test_every_operation_has_eligible_machines(self):
        config = InstanceConfig(
            group_name="test",
            num_instances=1,
            num_jobs=20,
            num_machines=8,
            num_entities=4,
            ops_per_job=(2, 4),
            rho_range=(0.7, 0.8),
            deadline_tightness=1.0,
            weight_pattern="uniform",
        )
        inst = generate_instance(config, seed=99)

        for job in inst.jobs:
            for op in job.operations:
                assert len(op.alternatives) > 0, (
                    f"Op {op.op_id} in job {job.job_id} has no alternatives"
                )
                # Each alternative references a valid machine
                for alt in op.alternatives:
                    assert any(
                        m.machine_id == alt.machine_id for m in inst.machines
                    ), f"Unknown machine {alt.machine_id}"

    def test_generation_is_reproducible(self):
        config = InstanceConfig(
            group_name="test",
            num_instances=1,
            num_jobs=10,
            num_machines=5,
            num_entities=3,
            ops_per_job=(2, 3),
            rho_range=(0.7, 0.8),
            deadline_tightness=1.0,
            weight_pattern="uniform",
        )
        inst1 = generate_instance(config, seed=42)
        inst2 = generate_instance(config, seed=42)
        d1 = instance_to_dict(inst1)
        d2 = instance_to_dict(inst2)
        assert d1 == d2

    def test_generation_different_seeds_differ(self):
        config = InstanceConfig(
            group_name="test",
            num_instances=1,
            num_jobs=10,
            num_machines=5,
            num_entities=3,
            ops_per_job=(2, 3),
            rho_range=(0.7, 0.8),
            deadline_tightness=1.0,
            weight_pattern="uniform",
        )
        inst1 = generate_instance(config, seed=42)
        inst2 = generate_instance(config, seed=99)
        d1 = instance_to_dict(inst1)
        d2 = instance_to_dict(inst2)
        assert d1 != d2

    def test_generate_instance_group(self):
        config = InstanceConfig(
            group_name="test",
            num_instances=5,
            num_jobs=10,
            num_machines=5,
            num_entities=3,
            ops_per_job=(2, 3),
            rho_range=(0.7, 0.8),
            deadline_tightness=1.0,
            weight_pattern="uniform",
        )
        instances = generate_instance_group(config, base_seed=1)
        assert len(instances) == 5
        for inst in instances:
            assert inst.num_jobs == 10

    def test_benchmark_configs_exist(self):
        required = ["S_10_5_3", "S_15_5_3", "S_20_5_3",
                     "M_30_8_3", "M_45_10_5", "M_60_12_5",
                     "D_60_10_5", "D_80_12_5", "D_100_15_5"]
        for key in required:
            assert key in BENCHMARK_CONFIGS, f"Missing config: {key}"

    def test_serialization_roundtrip(self):
        config = InstanceConfig(
            group_name="test",
            num_instances=1,
            num_jobs=10,
            num_machines=5,
            num_entities=3,
            ops_per_job=(2, 3),
            rho_range=(0.7, 0.8),
            deadline_tightness=1.0,
            weight_pattern="mild",
        )
        inst = generate_instance(config, seed=42)
        d = instance_to_dict(inst)
        inst2 = instance_from_dict(d)
        assert inst2.num_jobs == inst.num_jobs
        assert inst2.num_machines == inst.num_machines
        assert inst2.num_entities == inst.num_entities
        assert inst2.alpha == inst.alpha
        assert inst2.beta == inst.beta


class TestScenarioBuilder:
    """Tests for the dynamic scenario builder."""

    def test_static_scenario_unchanged(self):
        config = InstanceConfig(
            group_name="test",
            num_instances=1,
            num_jobs=10,
            num_machines=5,
            num_entities=3,
            ops_per_job=(2, 3),
            rho_range=(0.7, 0.8),
            deadline_tightness=1.0,
            weight_pattern="uniform",
            release_time_mode="static",
        )
        inst = generate_instance(config, seed=42)
        dyn = build_dynamic_scenario(inst, arrival_intensity="static", seed=0)
        assert dyn is inst  # same object returned for static

    def test_dynamic_scenario_modifies_release_times(self):
        config = InstanceConfig(
            group_name="test",
            num_instances=1,
            num_jobs=20,
            num_machines=8,
            num_entities=4,
            ops_per_job=(2, 3),
            rho_range=(0.7, 0.8),
            deadline_tightness=1.0,
            weight_pattern="uniform",
        )
        inst = generate_instance(config, seed=42)
        dyn = build_dynamic_scenario(inst, arrival_intensity="medium", seed=0)

        # Some release times should be non-zero for medium intensity
        non_zero = sum(1 for j in dyn.jobs if j.release_time > 0)
        assert non_zero > 0, "Expected some jobs to have non-zero release times"

    def test_dynamic_low_intensity(self):
        config = InstanceConfig(
            group_name="test",
            num_instances=1,
            num_jobs=50,
            num_machines=10,
            num_entities=5,
            ops_per_job=(2, 3),
            rho_range=(0.7, 0.8),
            deadline_tightness=1.0,
            weight_pattern="uniform",
        )
        inst = generate_instance(config, seed=42)
        dyn_low = build_dynamic_scenario(inst, arrival_intensity="low", seed=0)
        dyn_high = build_dynamic_scenario(inst, arrival_intensity="high", seed=0)

        # Low intensity should have more early (time=0) arrivals than high
        low_zero = sum(1 for j in dyn_low.jobs if j.release_time == 0)
        high_zero = sum(1 for j in dyn_high.jobs if j.release_time == 0)
        assert low_zero >= high_zero, (
            f"Low intensity should have >= zero-time jobs than high: "
            f"{low_zero} vs {high_zero}"
        )
