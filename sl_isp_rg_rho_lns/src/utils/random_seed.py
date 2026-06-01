"""Reproducible random seed management."""

import random
import time
from typing import Any


def create_rng(seed: int | None = None) -> random.Random:
    """Create a seeded random.Random instance.

    If seed is None, uses current timestamp for a non-reproducible seed.
    """
    if seed is None:
        seed = int(time.time_ns() % (2**31))
    rng = random.Random(seed)
    rng.seed(seed)  # ensure full seeding
    return rng


def seed_from_hash(*args: Any) -> int:
    """Derive a deterministic seed from arbitrary arguments."""
    h = hash(args)
    return h & 0x7FFFFFFF
