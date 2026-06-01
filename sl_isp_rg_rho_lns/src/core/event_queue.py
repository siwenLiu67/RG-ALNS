"""Event queue for the event-driven scheduling simulator."""

import heapq
from dataclasses import dataclass, field
from enum import IntEnum


class EventType(IntEnum):
    OP_COMPLETION = 1
    JOB_ARRIVAL = 2


@dataclass(order=True)
class Event:
    """An event in the simulation, ordered by time then type."""

    time: int
    event_type: EventType = field(compare=True)
    job_id: int = field(compare=False)
    op_id: int = field(compare=False, default=-1)
    machine_id: int = field(compare=False, default=-1)

    def __repr__(self) -> str:
        if self.event_type == EventType.JOB_ARRIVAL:
            return f"Event(t={self.time}, JOB_ARRIVAL, job={self.job_id})"
        return (
            f"Event(t={self.time}, OP_COMPLETION, "
            f"job={self.job_id}, op={self.op_id}, machine={self.machine_id})"
        )


class EventQueue:
    """Priority-queue-based event queue for the discrete-event simulator."""

    def __init__(self) -> None:
        self._heap: list[Event] = []
        self._counter: int = 0

    def push(self, event: Event) -> None:
        """Push an event onto the queue."""
        heapq.heappush(self._heap, event)

    def push_all(self, events: list[Event]) -> None:
        """Push multiple events onto the queue."""
        for event in events:
            self.push(event)

    def pop(self) -> Event:
        """Pop the next event (earliest time)."""
        if not self._heap:
            raise IndexError("pop from empty EventQueue")
        return heapq.heappop(self._heap)

    def peek(self) -> Event | None:
        """Return the next event without removing it, or None if empty."""
        if self._heap:
            return self._heap[0]
        return None

    @property
    def is_empty(self) -> bool:
        return len(self._heap) == 0

    def __len__(self) -> int:
        return len(self._heap)

    def __bool__(self) -> bool:
        return not self.is_empty
