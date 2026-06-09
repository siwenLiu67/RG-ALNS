"""Small sanity benchmark for Paper A RG-RALNS.

Usage:
    python3 -m src.experiments.run_rg_ralns_sanity --num-jobs 20 --seed 42
"""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

from src.algorithms.dispatching_rules import edd_rule
from src.algorithms.rg_ralns import run_lightweight_rg_dispatch, run_rg_ralns
from src.algorithms.rg_rho_lns_fast import run_rg_alns
from src.core.dataclasses import (
    Job,
    Machine,
    Operation,
    OperationAlternative,
    ServiceEntity,
    SLISPInstance,
)
from src.core.simulator import run_simulation


def _operation(job_id: int, seq: int, alternatives: list[tuple[int, int]]) -> Operation:
    return Operation(
        op_id=job_id * 10 + seq,
        job_id=job_id,
        sequence_index=seq,
        alternatives=[
            OperationAlternative(machine_id=machine_id, processing_time=pt)
            for machine_id, pt in alternatives
        ],
    )


def build_sanity_instance(num_jobs: int, seed: int) -> SLISPInstance:
    """Build a deterministic dynamic-arrival sanity instance."""

    del seed
    num_entities = 3
    num_machines = 4
    machines = [Machine(machine_id=i) for i in range(num_machines)]
    jobs: list[Job] = []
    total_by_entity = {entity_id: 0 for entity_id in range(num_entities)}

    for job_id in range(num_jobs):
        entity_id = job_id % num_entities
        quantity = 1 + (job_id % 3)
        total_by_entity[entity_id] += quantity
        release = (job_id * 3) % max(6, num_jobs)
        op0 = _operation(
            job_id,
            0,
            [
                (job_id % num_machines, 2 + (job_id % 5)),
                ((job_id + 1) % num_machines, 3 + (job_id % 4)),
            ],
        )
        op1 = _operation(
            job_id,
            1,
            [
                ((job_id + 2) % num_machines, 2 + ((job_id + 1) % 5)),
                ((job_id + 3) % num_machines, 4 + (job_id % 3)),
            ],
        )
        jobs.append(
            Job(
                job_id=job_id,
                entity_id=entity_id,
                release_time=release,
                quantity=quantity,
                operations=[op0, op1],
            )
        )

    entities = [
        ServiceEntity(
            entity_id=0,
            deadline=38,
            rho=0.65,
            weight=2.0,
            total_quantity=total_by_entity[0],
            transport_delay=1,
        ),
        ServiceEntity(
            entity_id=1,
            deadline=44,
            rho=0.65,
            weight=1.5,
            total_quantity=total_by_entity[1],
            transport_delay=2,
        ),
        ServiceEntity(
            entity_id=2,
            deadline=50,
            rho=0.65,
            weight=1.0,
            total_quantity=total_by_entity[2],
            transport_delay=3,
        ),
    ]
    return SLISPInstance(
        jobs=jobs,
        entities=entities,
        machines=machines,
        alpha=1.0,
        beta=1.0,
        metadata={"scenario": "rg_ralns_sanity", "num_jobs": num_jobs},
    )


def _rg_stats(algo) -> dict:
    if not hasattr(algo, "trigger_count"):
        return {
            "trigger_count": 0,
            "trigger_reason_counts": {},
            "avg_A_size": 0.0,
            "max_A_size": 0,
            "alns_runtime_total": 0.0,
            "dispatch_fallback_count": 0,
        }
    return {
        "trigger_count": algo.trigger_count,
        "trigger_reason_counts": dict(algo.trigger_reason_counts),
        "avg_A_size": round(algo.avg_A_size, 4),
        "max_A_size": algo.max_A_size,
        "alns_runtime_total": round(algo.alns_runtime_total, 6),
        "dispatch_fallback_count": algo.dispatch_fallback_count,
    }


def run_sanity(num_jobs: int, seed: int) -> list[dict]:
    instance = build_sanity_instance(num_jobs, seed)
    algorithms = [
        ("edd", "EDD baseline", edd_rule, True),
        (
            "lightweight_rg_dispatch",
            "Lightweight RG dispatch",
            run_lightweight_rg_dispatch(H_A=8, N_A=0, random_seed=seed),
            True,
        ),
        (
            "legacy_rg_alns",
            "Legacy rolling-horizon RG-ALNS",
            run_rg_alns(horizon=120, lns_iterations=5, seed=seed),
            False,
        ),
        (
            "rg_ralns",
            "RG-RALNS main",
            run_rg_ralns(H_A=8, N_A=8, random_seed=seed),
            True,
        ),
    ]

    rows: list[dict] = []
    for key, label, algo, online_visibility in algorithms:
        start = time.perf_counter()
        try:
            _state, obj = run_simulation(
                instance,
                algo,
                online_visibility=online_visibility,
            )
            row = {
                "algorithm": key,
                "algorithm_label": label,
                "status": "OK",
                "online_visibility": online_visibility,
                "Z": obj.Z,
                "TT": obj.total_tardiness,
                "WSF": obj.weighted_service_shortfall,
                "zero_shortfall_entity_rate": obj.zero_shortfall_entity_rate,
                "runtime": round(time.perf_counter() - start, 6),
            }
            row.update(_rg_stats(algo))
        except Exception as exc:
            row = {
                "algorithm": key,
                "algorithm_label": label,
                "status": "FAILED",
                "online_visibility": online_visibility,
                "Z": None,
                "TT": None,
                "WSF": None,
                "zero_shortfall_entity_rate": None,
                "runtime": round(time.perf_counter() - start, 6),
                "error_type": exc.__class__.__name__,
                "error_message": str(exc),
            }
            row.update(_rg_stats(algo))
        rows.append(row)
    return rows


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fieldnames.append(key)
                seen.add(key)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--num-jobs", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/rg_ralns_sanity/rg_ralns_sanity.csv"),
    )
    args = parser.parse_args()

    rows = run_sanity(args.num_jobs, args.seed)
    _write_csv(args.output, rows)
    for row in rows:
        print(row)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
