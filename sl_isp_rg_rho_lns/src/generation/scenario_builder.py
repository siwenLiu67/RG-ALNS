"""Dynamic scenario builder for SL-ISP instances.

Applies arrival intensity patterns to a base static instance by modifying
job release times.
"""

import random
from dataclasses import dataclass, field

from ..core.dataclasses import Job, SLISPInstance
from ..utils.random_seed import create_rng


@dataclass
class ScenarioConfig:
    """Configuration for a dynamic scenario."""

    arrival_intensity: str  # "static", "low", "medium", "high"
    seed: int = 0


def build_dynamic_scenario(
    base_instance: SLISPInstance,
    arrival_intensity: str = "static",
    seed: int = 0,
) -> SLISPInstance:
    """Apply a dynamic arrival pattern to a base instance.

    Returns a new SLISPInstance with updated job release times.
    All other data (operations, entities, machines) is shared (not deep-copied).
    """
    if arrival_intensity == "static":
        return base_instance

    rng = create_rng(seed)

    # Estimate a time horizon for spreading arrivals
    ref_makespan = base_instance.metadata.get("ref_makespan", 100)
    horizon = max(ref_makespan, 50)

    new_jobs = []
    for job in base_instance.jobs:
        new_release = _sample_release_time(
            job.job_id,
            base_instance.num_jobs,
            arrival_intensity,
            horizon,
            rng,
        )
        # Create a new Job with the modified release time.
        # Operations are shared (frozen dataclasses, safe to share).
        new_jobs.append(
            Job(
                job_id=job.job_id,
                entity_id=job.entity_id,
                release_time=new_release,
                quantity=job.quantity,
                operations=job.operations,
            )
        )

    return SLISPInstance(
        jobs=new_jobs,
        entities=base_instance.entities,
        machines=base_instance.machines,
        alpha=base_instance.alpha,
        beta=base_instance.beta,
        metadata={
            **base_instance.metadata,
            "arrival_intensity": arrival_intensity,
            "scenario_seed": seed,
        },
    )


def build_multi_intensity_scenarios(
    base_instance: SLISPInstance,
    intensities: list[str],
    base_seed: int = 0,
) -> dict[str, SLISPInstance]:
    """Build instances for multiple arrival intensities from one base instance.

    Returns a dict mapping intensity name -> SLISPInstance.
    """
    results: dict[str, SLISPInstance] = {}
    for i, intensity in enumerate(intensities):
        inst = build_dynamic_scenario(
            base_instance,
            arrival_intensity=intensity,
            seed=base_seed + i * 10007,
        )
        results[intensity] = inst
    return results


def _sample_release_time(
    job_id: int,
    total_jobs: int,
    intensity: str,
    horizon: int,
    rng: random.Random,
) -> int:
    """Sample a release time for a job based on arrival intensity pattern.

    The job_id and total_jobs determine the job's position in the arrival
    sequence for deterministic wave-based patterns.
    """
    if intensity == "static":
        return 0

    # Normalize job position to [0, 1)
    frac = job_id / max(total_jobs, 1)

    if intensity == "low":
        # 70% at time 0, 20% in first half, 10% in second half
        r = rng.random()
        if r < 0.70:
            return 0
        elif r < 0.90:
            return rng.randint(0, horizon // 2)
        else:
            return rng.randint(horizon // 2, horizon)

    elif intensity == "medium":
        # 50% at time 0, 25% in first third, 25% in remaining
        r = rng.random()
        if r < 0.50:
            return 0
        elif r < 0.75:
            return rng.randint(0, horizon // 3)
        else:
            return rng.randint(horizon // 3, horizon)

    elif intensity == "high":
        # 30% at time 0, 35% spread, 35% in second half
        r = rng.random()
        if r < 0.30:
            return 0
        elif r < 0.65:
            return rng.randint(0, horizon // 2)
        else:
            return rng.randint(horizon // 2, horizon)

    else:
        raise ValueError(f"Unknown arrival intensity: {intensity}")
