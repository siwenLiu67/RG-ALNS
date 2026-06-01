"""Core data classes for the SL-ISP problem."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class OperationAlternative:
    """An eligible machine with its processing time for a specific operation."""

    machine_id: int
    processing_time: int

    def __post_init__(self):
        if self.processing_time <= 0:
            raise ValueError(
                f"processing_time must be positive, got {self.processing_time}"
            )


@dataclass(frozen=True)
class Operation:
    """A single operation within a job's processing sequence."""

    op_id: int
    job_id: int
    sequence_index: int
    alternatives: list[OperationAlternative]

    def __post_init__(self):
        if not self.alternatives:
            raise ValueError(
                f"Operation {self.op_id} (job {self.job_id}) has no eligible machines"
            )
        machine_ids = {alt.machine_id for alt in self.alternatives}
        if len(machine_ids) != len(self.alternatives):
            raise ValueError(
                f"Operation {self.op_id} has duplicate machine alternatives"
            )

    @property
    def eligible_machines(self) -> list[int]:
        return [alt.machine_id for alt in self.alternatives]

    def processing_time_on(self, machine_id: int) -> int:
        for alt in self.alternatives:
            if alt.machine_id == machine_id:
                return alt.processing_time
        raise KeyError(
            f"Machine {machine_id} not eligible for operation {self.op_id}"
        )

    @property
    def min_processing_time(self) -> int:
        return min(alt.processing_time for alt in self.alternatives)


@dataclass(frozen=True)
class Job:
    """A job consisting of sequentially ordered operations."""

    job_id: int
    entity_id: int
    release_time: int
    quantity: int
    operations: list[Operation]

    def __post_init__(self):
        if self.quantity <= 0:
            raise ValueError(f"Job {self.job_id} quantity must be positive")
        if not self.operations:
            raise ValueError(f"Job {self.job_id} must have at least one operation")
        for i, op in enumerate(self.operations):
            if op.sequence_index != i:
                raise ValueError(
                    f"Job {self.job_id}: operation sequence indices must be "
                    f"0, 1, 2, ... but found {op.sequence_index} at position {i}"
                )
            if op.job_id != self.job_id:
                raise ValueError(
                    f"Job {self.job_id}: operation {op.op_id} has inconsistent job_id {op.job_id}"
                )

    @property
    def num_operations(self) -> int:
        return len(self.operations)

    def operation_at(self, sequence_index: int) -> Operation:
        return self.operations[sequence_index]


@dataclass(frozen=True)
class ServiceEntity:
    """A service entity with delivery deadline and fulfillment requirements."""

    entity_id: int
    deadline: int
    rho: float
    weight: float
    total_quantity: int
    transport_delay: int

    def __post_init__(self):
        if not (0.0 < self.rho <= 1.0):
            raise ValueError(f"Entity {self.entity_id}: rho must be in (0, 1]")
        if self.weight <= 0:
            raise ValueError(f"Entity {self.entity_id}: weight must be positive")
        if self.total_quantity <= 0:
            raise ValueError(f"Entity {self.entity_id}: total_quantity must be positive")
        if self.transport_delay < 0:
            raise ValueError(f"Entity {self.entity_id}: transport_delay must be non-negative")

    @property
    def min_fulfillment(self) -> float:
        """Minimum on-time quantity threshold from the paper model."""
        return max(1.0, self.rho * self.total_quantity)


@dataclass(frozen=True)
class Machine:
    """A machine resource in the shop floor."""

    machine_id: int


@dataclass
class SLISPInstance:
    """Complete problem instance with all data."""

    jobs: list[Job]
    entities: list[ServiceEntity]
    machines: list[Machine]
    alpha: float
    beta: float
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        job_ids = {j.job_id for j in self.jobs}
        entity_ids = {e.entity_id for e in self.entities}
        machine_ids = {m.machine_id for m in self.machines}

        for job in self.jobs:
            if job.entity_id not in entity_ids:
                raise ValueError(
                    f"Job {job.job_id} references unknown entity {job.entity_id}"
                )
            for op in job.operations:
                for alt in op.alternatives:
                    if alt.machine_id not in machine_ids:
                        raise ValueError(
                            f"Op {op.op_id} references unknown machine {alt.machine_id}"
                        )

        if len(job_ids) != len(self.jobs):
            raise ValueError("Duplicate job IDs detected")
        if len(entity_ids) != len(self.entities):
            raise ValueError("Duplicate entity IDs detected")
        if len(machine_ids) != len(self.machines):
            raise ValueError("Duplicate machine IDs detected")
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
        for j in self.jobs:
            if j.job_id == job_id:
                return j
        raise KeyError(f"Job {job_id} not found")

    def get_entity(self, entity_id: int) -> ServiceEntity:
        for e in self.entities:
            if e.entity_id == entity_id:
                return e
        raise KeyError(f"Entity {entity_id} not found")

    def jobs_of_entity(self, entity_id: int) -> list[Job]:
        return [j for j in self.jobs if j.entity_id == entity_id]


@dataclass(frozen=True)
class ScheduledOperation:
    """A concrete assignment of an operation to a machine with start/end times."""

    job_id: int
    op_id: int
    machine_id: int
    start_time: int
    end_time: int

    def __post_init__(self):
        if self.start_time < 0:
            raise ValueError("start_time must be non-negative")
        if self.end_time <= self.start_time:
            raise ValueError(
                f"end_time ({self.end_time}) must be > start_time ({self.start_time})"
            )
