"""Schedule state tracking for the event-driven simulator."""

from dataclasses import dataclass, field

from .dataclasses import ScheduledOperation
from .event_queue import EventQueue


@dataclass
class ScheduleState:
    """Complete state of the scheduling simulation at a point in time."""

    current_time: int = 0
    machine_available_times: dict[int, int] = field(default_factory=dict)
    completed_operations: set[tuple[int, int]] = field(default_factory=set)
    ongoing_operations: dict[tuple[int, int], ScheduledOperation] = field(
        default_factory=dict
    )
    scheduled_operations: list[ScheduledOperation] = field(default_factory=list)
    completed_jobs: dict[int, int] = field(default_factory=dict)
    delivered_on_time_jobs: set[int] = field(default_factory=set)
    event_queue: EventQueue = field(default_factory=EventQueue)

    # Per-job: sequence index of the last completed operation (-1 if none started)
    last_completed_op_index: dict[int, int] = field(default_factory=dict)

    def is_machine_idle(self, machine_id: int) -> bool:
        avail = self.machine_available_times.get(machine_id, 0)
        return self.current_time >= avail

    def is_job_completed(self, job_id: int) -> bool:
        return job_id in self.completed_jobs

    def is_operation_completed(self, job_id: int, op_id: int) -> bool:
        return (job_id, op_id) in self.completed_operations

    def is_operation_ongoing(self, job_id: int, op_id: int) -> bool:
        return (job_id, op_id) in self.ongoing_operations

    def next_op_index_for_job(self, job_id: int) -> int:
        return self.last_completed_op_index.get(job_id, -1) + 1

    def mark_operation_started(
        self, job_id: int, op_id: int, machine_id: int, start_time: int, end_time: int
    ) -> None:
        sop = ScheduledOperation(
            job_id=job_id,
            op_id=op_id,
            machine_id=machine_id,
            start_time=start_time,
            end_time=end_time,
        )
        self.ongoing_operations[(job_id, op_id)] = sop
        self.scheduled_operations.append(sop)
        self.machine_available_times[machine_id] = end_time

    def mark_operation_completed(self, job_id: int, op_id: int, seq_index: int) -> None:
        self.completed_operations.add((job_id, op_id))
        self.ongoing_operations.pop((job_id, op_id), None)
        self.last_completed_op_index[job_id] = seq_index

    def mark_job_completed(self, job_id: int, completion_time: int) -> None:
        self.completed_jobs[job_id] = completion_time

    def mark_delivered_on_time(self, job_id: int) -> None:
        self.delivered_on_time_jobs.add(job_id)
