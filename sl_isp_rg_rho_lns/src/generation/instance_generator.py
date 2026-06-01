"""Instance generator for SL-ISP benchmark instances.

Supports Group S (small validation), Group M (main benchmark), Group D (dynamic),
and larger stress-test instances.
"""

import random
from dataclasses import dataclass, field

from ..core.dataclasses import (
    Job,
    Machine,
    Operation,
    OperationAlternative,
    ServiceEntity,
    SLISPInstance,
)
from ..utils.random_seed import create_rng


@dataclass
class InstanceConfig:
    """Configuration for generating a single group of instances."""

    group_name: str
    num_instances: int
    num_jobs: int | tuple[int, int]
    num_machines: int
    num_entities: int
    ops_per_job: tuple[int, int]  # (min, max)
    rho_range: tuple[float, float]
    deadline_tightness: float  # kappa
    weight_pattern: str  # "uniform", "mild", "strong"
    quantity_range: tuple[int, int] = (1, 10)
    proc_time_range: tuple[int, int] = (1, 100)
    transport_delay_range: tuple[int, int] = (0, 50)
    eligible_machines_range: tuple[int, int] = (2, 4)
    alpha: float = 1.0
    beta: float = 1.0
    effective_due_spread: float = 0.0
    effective_due_multipliers: tuple[float, ...] | None = None
    release_time_mode: str = "static"  # "static" or "dynamic_basic"

    # Dynamic arrival parameters (used by scenario_builder)
    arrival_intensity: str = "static"  # "static", "low", "medium", "high"


# Pre-defined benchmark configurations per the spec
BENCHMARK_CONFIGS: dict[str, InstanceConfig] = {
    "S_10_5_3": InstanceConfig(
        group_name="S",
        num_instances=10,
        num_jobs=10,
        num_machines=5,
        num_entities=3,
        ops_per_job=(2, 4),
        rho_range=(0.70, 0.80),
        deadline_tightness=1.0,
        weight_pattern="mild",
    ),
    "S_15_5_3": InstanceConfig(
        group_name="S",
        num_instances=10,
        num_jobs=15,
        num_machines=5,
        num_entities=3,
        ops_per_job=(2, 4),
        rho_range=(0.70, 0.80),
        deadline_tightness=1.0,
        weight_pattern="mild",
    ),
    "S_20_5_3": InstanceConfig(
        group_name="S",
        num_instances=10,
        num_jobs=20,
        num_machines=5,
        num_entities=3,
        ops_per_job=(2, 4),
        rho_range=(0.70, 0.80),
        deadline_tightness=1.0,
        weight_pattern="mild",
    ),
    "M_30_8_3": InstanceConfig(
        group_name="M",
        num_instances=15,
        num_jobs=30,
        num_machines=8,
        num_entities=3,
        ops_per_job=(3, 6),
        rho_range=(0.70, 0.80),
        deadline_tightness=1.0,
        weight_pattern="mild",
    ),
    "M_45_10_5": InstanceConfig(
        group_name="M",
        num_instances=15,
        num_jobs=45,
        num_machines=10,
        num_entities=5,
        ops_per_job=(3, 6),
        rho_range=(0.70, 0.80),
        deadline_tightness=1.0,
        weight_pattern="mild",
    ),
    "M_60_12_5": InstanceConfig(
        group_name="M",
        num_instances=15,
        num_jobs=60,
        num_machines=12,
        num_entities=5,
        ops_per_job=(3, 6),
        rho_range=(0.70, 0.80),
        deadline_tightness=1.0,
        weight_pattern="mild",
    ),
    "D_60_10_5": InstanceConfig(
        group_name="D",
        num_instances=10,
        num_jobs=60,
        num_machines=10,
        num_entities=5,
        ops_per_job=(3, 6),
        rho_range=(0.70, 0.80),
        deadline_tightness=1.0,
        weight_pattern="mild",
        release_time_mode="dynamic_basic",
    ),
    "D_80_12_5": InstanceConfig(
        group_name="D",
        num_instances=10,
        num_jobs=80,
        num_machines=12,
        num_entities=5,
        ops_per_job=(3, 6),
        rho_range=(0.70, 0.80),
        deadline_tightness=1.0,
        weight_pattern="mild",
        release_time_mode="dynamic_basic",
    ),
    "D_100_15_5": InstanceConfig(
        group_name="D",
        num_instances=10,
        num_jobs=100,
        num_machines=15,
        num_entities=5,
        ops_per_job=(3, 6),
        rho_range=(0.70, 0.80),
        deadline_tightness=1.0,
        weight_pattern="mild",
        release_time_mode="dynamic_basic",
    ),
}


def generate_instance(config: InstanceConfig, seed: int, instance_index: int = 0) -> SLISPInstance:
    """Generate a single SL-ISP instance from a configuration."""
    rng = create_rng(seed + instance_index * 10007)

    num_jobs = _resolve_range(config.num_jobs, rng)

    # 1. Generate machines
    machines = [Machine(machine_id=i) for i in range(config.num_machines)]

    # 2. Generate entities (without total_quantity yet)
    entities_data: list[dict] = []
    for e_idx in range(config.num_entities):
        w = _weight_for_pattern(config.weight_pattern, e_idx, config.num_entities)
        rho = round(rng.uniform(*config.rho_range), 2)
        transport_delay = rng.randint(*config.transport_delay_range)
        entities_data.append(
            {
                "entity_id": e_idx,
                "rho": rho,
                "weight": w,
                "transport_delay": transport_delay,
                "deadline": 0,  # placeholder, computed later
                "total_quantity": 0,  # placeholder, computed later
            }
        )

    # 3. Generate jobs (without release times set yet)
    raw_jobs: list[dict] = []
    job_counter = 0
    for _ in range(num_jobs):
        entity_id = rng.randint(0, config.num_entities - 1)
        quantity = rng.randint(*config.quantity_range)
        num_ops = rng.randint(*config.ops_per_job)
        ops = []
        for seq_idx in range(num_ops):
            op_id = job_counter * 100 + seq_idx
            num_eligible = min(
                rng.randint(*config.eligible_machines_range), config.num_machines
            )
            eligible_machine_ids = rng.sample(
                [m.machine_id for m in machines], num_eligible
            )
            alts = [
                OperationAlternative(
                    machine_id=mid,
                    processing_time=rng.randint(*config.proc_time_range),
                )
                for mid in eligible_machine_ids
            ]
            ops.append(
                {
                    "op_id": op_id,
                    "job_id": job_counter,
                    "sequence_index": seq_idx,
                    "alternatives": alts,
                }
            )
        raw_jobs.append(
            {
                "job_id": job_counter,
                "entity_id": entity_id,
                "quantity": quantity,
                "operations": ops,
                "release_time": 0,  # default, scenario_builder may override
            }
        )
        job_counter += 1

    # 4. Compute entity total_quantity from assigned jobs
    for job_data in raw_jobs:
        eid = job_data["entity_id"]
        entities_data[eid]["total_quantity"] += job_data["quantity"]

    # 5. Estimate reference completion time for deadline computation
    # Lower bound: sum over all jobs of sum of min processing time per operation
    total_work_est = 0
    for job_data in raw_jobs:
        job_work = 0
        for op_data in job_data["operations"]:
            min_pt = min(alt.processing_time for alt in op_data["alternatives"])
            job_work += min_pt
        total_work_est += job_work

    # Rough estimate: divide by number of machines
    ref_makespan = max(1, total_work_est // config.num_machines)

    # 6. Set entity deadlines
    ref_completion = int(ref_makespan * config.deadline_tightness)
    effective_due_values = _effective_due_values(ref_completion, config)
    for ed in entities_data:
        tau = ed["transport_delay"]
        effective_due = effective_due_values[ed["entity_id"]]
        ed["deadline"] = max(1, effective_due + tau)

    # 7. Build final dataclass objects
    entities = [
        ServiceEntity(
            entity_id=ed["entity_id"],
            deadline=ed["deadline"],
            rho=ed["rho"],
            weight=ed["weight"],
            total_quantity=ed["total_quantity"],
            transport_delay=ed["transport_delay"],
        )
        for ed in entities_data
    ]

    jobs = [
        Job(
            job_id=jd["job_id"],
            entity_id=jd["entity_id"],
            release_time=jd["release_time"],
            quantity=jd["quantity"],
            operations=[
                Operation(
                    op_id=od["op_id"],
                    job_id=od["job_id"],
                    sequence_index=od["sequence_index"],
                    alternatives=od["alternatives"],
                )
                for od in jd["operations"]
            ],
        )
        for jd in raw_jobs
    ]

    return SLISPInstance(
        jobs=jobs,
        entities=entities,
        machines=machines,
        alpha=config.alpha,
        beta=config.beta,
        metadata={
            "config_group": config.group_name,
            "seed": seed,
            "instance_index": instance_index,
            "num_jobs": num_jobs,
            "num_machines": config.num_machines,
            "num_entities": config.num_entities,
            "rho_range": list(config.rho_range),
            "deadline_tightness": config.deadline_tightness,
            "effective_due_spread": config.effective_due_spread,
            "effective_due_multipliers": (
                list(config.effective_due_multipliers)
                if config.effective_due_multipliers is not None
                else None
            ),
            "effective_due_values": effective_due_values,
            "weight_pattern": config.weight_pattern,
            "ref_makespan": ref_makespan,
        },
    )


def generate_instance_group(
    config: InstanceConfig, base_seed: int
) -> list[SLISPInstance]:
    """Generate a group of instances sharing the same configuration."""
    instances = []
    for i in range(config.num_instances):
        inst = generate_instance(config, base_seed, instance_index=i)
        instances.append(inst)
    return instances


def _resolve_range(value: int | tuple[int, int], rng: random.Random) -> int:
    """Resolve a value that may be an integer or a (min, max) range."""
    if isinstance(value, int):
        return value
    return rng.randint(value[0], value[1])


def _effective_due_values(ref_completion: int, config: InstanceConfig) -> list[int]:
    """Build entity-level production-side cutoff times."""
    base = max(1, ref_completion)

    if config.effective_due_multipliers is not None:
        multipliers = tuple(config.effective_due_multipliers)
        if len(multipliers) != config.num_entities:
            raise ValueError(
                "effective_due_multipliers must have one value per entity"
            )
        if any(multiplier <= 0 for multiplier in multipliers):
            raise ValueError("effective_due_multipliers must be positive")
        return [max(1, int(round(base * multiplier))) for multiplier in multipliers]

    spread = config.effective_due_spread
    if spread < 0:
        raise ValueError("effective_due_spread must be non-negative")
    if config.num_entities <= 1 or spread == 0:
        return [base for _ in range(config.num_entities)]

    values: list[int] = []
    for entity_idx in range(config.num_entities):
        position = entity_idx / (config.num_entities - 1)
        multiplier = 1.0 + spread * (position - 0.5)
        values.append(max(1, int(round(base * multiplier))))
    return values


def _weight_for_pattern(pattern: str, entity_idx: int, num_entities: int) -> float:
    """Determine entity importance weight based on pattern."""
    if pattern == "uniform":
        return 1.0
    elif pattern == "mild":
        options = [1.0, 2.0, 3.0]
        return options[entity_idx % len(options)]
    elif pattern == "strong":
        options = [1.0, 3.0, 5.0]
        return options[entity_idx % len(options)]
    else:
        raise ValueError(f"Unknown weight pattern: {pattern}")
