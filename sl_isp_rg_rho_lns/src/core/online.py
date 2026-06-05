"""Online problem views for algorithm-facing information control."""

from dataclasses import dataclass, field

from .dataclasses import Job, Machine, ServiceEntity


@dataclass
class OnlineProblemView:
    """Algorithm-facing view that hides unreleased jobs.

    `total_quantity` on each service entity remains the known committed entity
    quantity. The `jobs` list contains only jobs revealed to the scheduler.
    """

    jobs: list[Job]
    entities: list[ServiceEntity]
    machines: list[Machine]
    alpha: float
    beta: float
    entity_future_quantity: dict[int, int] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.entity_future_quantity = dict(self.entity_future_quantity)

        job_ids = {job.job_id for job in self.jobs}
        entity_ids = {entity.entity_id for entity in self.entities}
        machine_ids = {machine.machine_id for machine in self.machines}

        if len(job_ids) != len(self.jobs):
            raise ValueError("Duplicate visible job IDs detected")
        if len(entity_ids) != len(self.entities):
            raise ValueError("Duplicate entity IDs detected")
        if len(machine_ids) != len(self.machines):
            raise ValueError("Duplicate machine IDs detected")

        for job in self.jobs:
            if job.entity_id not in entity_ids:
                raise ValueError(
                    f"Visible job {job.job_id} references unknown entity {job.entity_id}"
                )
            for op in job.operations:
                for alt in op.alternatives:
                    if alt.machine_id not in machine_ids:
                        raise ValueError(
                            f"Visible op {op.op_id} references unknown machine {alt.machine_id}"
                        )

        if self.alpha < 0 or self.beta < 0:
            raise ValueError("alpha and beta must be non-negative")

    @property
    def num_jobs(self) -> int:
        return len(self.jobs)

    @property
    def num_machines(self) -> int:
        return len(self.machines)

    @property
    def num_entities(self) -> int:
        return len(self.entities)

    def get_job(self, job_id: int) -> Job:
        for job in self.jobs:
            if job.job_id == job_id:
                return job
        raise KeyError(f"Visible job {job_id} not found")

    def get_entity(self, entity_id: int) -> ServiceEntity:
        for entity in self.entities:
            if entity.entity_id == entity_id:
                return entity
        raise KeyError(f"Entity {entity_id} not found")

    def jobs_of_entity(self, entity_id: int) -> list[Job]:
        return [job for job in self.jobs if job.entity_id == entity_id]
