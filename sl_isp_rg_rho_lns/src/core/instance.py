"""Instance serialization and validation utilities."""

import json
from pathlib import Path

from .dataclasses import (
    Job,
    Machine,
    Operation,
    OperationAlternative,
    ServiceEntity,
    SLISPInstance,
)


def instance_to_dict(instance: SLISPInstance) -> dict:
    """Serialize an SLISPInstance to a plain dict (JSON-compatible)."""
    jobs_data = []
    for job in instance.jobs:
        ops_data = []
        for op in job.operations:
            alts_data = [
                {"machine_id": alt.machine_id, "processing_time": alt.processing_time}
                for alt in op.alternatives
            ]
            ops_data.append(
                {
                    "op_id": op.op_id,
                    "job_id": op.job_id,
                    "sequence_index": op.sequence_index,
                    "alternatives": alts_data,
                }
            )
        jobs_data.append(
            {
                "job_id": job.job_id,
                "entity_id": job.entity_id,
                "release_time": job.release_time,
                "quantity": job.quantity,
                "operations": ops_data,
            }
        )

    entities_data = [
        {
            "entity_id": e.entity_id,
            "deadline": e.deadline,
            "rho": e.rho,
            "weight": e.weight,
            "total_quantity": e.total_quantity,
            "transport_delay": e.transport_delay,
        }
        for e in instance.entities
    ]

    machines_data = [{"machine_id": m.machine_id} for m in instance.machines]

    return {
        "jobs": jobs_data,
        "entities": entities_data,
        "machines": machines_data,
        "alpha": instance.alpha,
        "beta": instance.beta,
        "metadata": instance.metadata,
    }


def instance_from_dict(data: dict) -> SLISPInstance:
    """Deserialize a plain dict into an SLISPInstance."""
    jobs = []
    for jd in data["jobs"]:
        ops = []
        for od in jd["operations"]:
            alts = [
                OperationAlternative(
                    machine_id=ad["machine_id"],
                    processing_time=ad["processing_time"],
                )
                for ad in od["alternatives"]
            ]
            ops.append(
                Operation(
                    op_id=od["op_id"],
                    job_id=od["job_id"],
                    sequence_index=od["sequence_index"],
                    alternatives=alts,
                )
            )
        jobs.append(
            Job(
                job_id=jd["job_id"],
                entity_id=jd["entity_id"],
                release_time=jd["release_time"],
                quantity=jd["quantity"],
                operations=ops,
            )
        )

    entities = [
        ServiceEntity(
            entity_id=ed["entity_id"],
            deadline=ed["deadline"],
            rho=ed["rho"],
            weight=ed["weight"],
            total_quantity=ed["total_quantity"],
            transport_delay=ed["transport_delay"],
        )
        for ed in data["entities"]
    ]

    machines = [Machine(machine_id=md["machine_id"]) for md in data["machines"]]

    return SLISPInstance(
        jobs=jobs,
        entities=entities,
        machines=machines,
        alpha=data["alpha"],
        beta=data["beta"],
        metadata=data.get("metadata", {}),
    )


def save_instance_json(instance: SLISPInstance, path: Path) -> None:
    """Save an instance to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(instance_to_dict(instance), f, indent=2)


def load_instance_json(path: Path) -> SLISPInstance:
    """Load an instance from a JSON file."""
    with open(path) as f:
        data = json.load(f)
    return instance_from_dict(data)
