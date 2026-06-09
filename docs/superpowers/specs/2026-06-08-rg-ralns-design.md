# Recoverability-Guided Reactive ALNS Design Spec

**Paper A main algorithm name:** Recoverability-Guided Reactive ALNS (RG-RALNS)

**Purpose:** Define the main online scheduling algorithm for Paper A. RG-RALNS is a reactive online local rescheduling algorithm for service-level flexible job shop scheduling with dynamic job arrivals.

**Core principle:** The algorithm uses detailed information only for jobs that have arrived. Future work is represented only by entity-level aggregate quantity needed for service fulfillment; future job release times, operation routes, processing times, and machine eligibility are not observable before arrival.

---

## 1. Online Information Model

At decision time `t`, the simulator has the complete experimental ground truth, but the algorithm receives only the online information view:

- `J_vis(t)`: jobs that have arrived by time `t`.
- `J_done(t)`: jobs completed by time `t`.
- `O_done(t)`: operations completed by time `t`.
- `O_run(t)`: operations currently in process and therefore frozen.
- `M_idle(t)`: machines idle at time `t`.
- `state(t)`: current machine availability, completed operations, ongoing operations, and completed jobs.
- Entity service parameters: deadline `d_r`, transport delay `tau_r`, service ratio `rho_r`, total entity quantity `Q_r`, minimum fulfillment `Q_min,r = max(1, rho_r Q_r)`, and entity weight `w_r`.
- `Q_future,r(t)`: aggregate quantity of entity `r` that has not yet arrived.

The algorithm must not use detailed information about jobs outside `J_vis(t)`. In particular, for any future job `j notin J_vis(t)`, its release time, operations, processing times, and eligible machines are hidden.

When a job `j` of entity `r` arrives, it is added to `J_vis(t)` and its quantity is subtracted from `Q_future,r(t)`.

---

## 2. Recoverability Diagnosis

At every event time, RG-RALNS computes entity-level recoverability diagnostics using only the online information view.

### Secured Quantity

`Q_sec,r(t)` is the quantity of jobs of entity `r` that have completed production and can be delivered on time:

```text
Q_sec,r(t) = sum_{j in J_done(t), g(j)=r, C_j + tau_r <= d_r} q_j
```

### Remaining Service Requirement

`Q_rem,r(t)` is the remaining quantity required to satisfy the minimum fulfillment level:

```text
Q_rem,r(t) = max(0, Q_min,r - Q_sec,r(t))
```

### Visible Recoverable Quantity

For an arrived but incomplete job `j`, define an optimistic delivery lower bound:

```text
D_lb,j(t) = max(t, r_j) + remaining_min_processing_time_j(t) + tau_{g(j)}
```

A visible job is recoverable for entity `r` if `g(j)=r` and `D_lb,j(t) <= d_r`.

```text
Q_rec,r(t) = sum_{j in J_vis(t) \ J_done(t), g(j)=r, D_lb,j(t) <= d_r} q_j
```

### Current-Information Shortfall Risk

Because the future detailed jobs are unknown, future quantity can only be used as an aggregate service buffer:

```text
U_info,r(t) = max(0, Q_rem,r(t) - Q_rec,r(t) - Q_future,r(t))
```

`U_info,r(t)` is a lower-bound risk signal under current information. It does not assume future jobs are schedulable before their arrival.

### Mandatory Rescue Jobs

A visible recoverable job `j` of entity `r` is a mandatory rescue job if removing its quantity from the visible recoverable pool creates current-information shortfall risk:

```text
j is mandatory for r if
  g(j)=r,
  D_lb,j(t) <= d_r,
  max(0, Q_rem,r(t) - (Q_rec,r(t) - q_j) - Q_future,r(t)) > 0
```

This definition is computable from visible jobs and aggregate future quantity only.

### Heuristic Service Cover

The service cover is a heuristic set, not an exact minimum cover optimization. Because aggregate future quantity can buffer part of the remaining requirement, the visible cover target is:

```text
Q_cover,r(t) = max(0, Q_rem,r(t) - Q_future,r(t))
```

For each entity with `Q_cover,r(t) > 0`, construct a ranked list of visible recoverable jobs by:

```text
cover_key(j) =
  mandatory_flag first,
  larger marginal quantity min(q_j, remaining uncovered Q_cover,r(t)) first,
  earlier effective production deadline d_r - tau_r first,
  smaller remaining processing work first,
  smaller job_id first
```

Select jobs in this order until the cumulative selected quantity reaches `Q_cover,r(t)` or no visible recoverable jobs remain. The selected jobs form `Cover_r(t)`.

### Recoverability Class

Entities are classified for triggering and affected-set construction:

- `secured`: `Q_rem,r(t) = 0`.
- `at_risk`: `U_info,r(t) > 0`.
- `arrival_dependent`: `U_info,r(t) = 0`, `Q_rec,r(t) < Q_rem,r(t)`, and `Q_future,r(t) > 0`.
- `fragile`: `U_info,r(t) = 0`, `Q_rec,r(t) >= Q_cover,r(t)`, and either mandatory rescue jobs exist or visible recoverable surplus is smaller than the smallest visible recoverable job quantity for the entity.
- `stable`: none of the above and visible recoverable quantity has at least one-job surplus over `Q_cover,r(t)`.

---

## 3. Reactive Trigger Mechanism

The simulator invokes the algorithm after processing all events at the same timestamp. RG-RALNS first performs diagnostics, then decides whether to run local ALNS.

In this spec, a high-risk entity means an entity classified as `at_risk`, `arrival_dependent`, or `fragile`.

Events are:

- `JOB_ARRIVAL`: one or more jobs arrive and become visible.
- `OP_COMPLETION`: one or more operations complete and machines or successor operations may become available.

### Trigger ALNS

Run local RG-ALNS if at least one of the following deterministic conditions holds:

1. Some entity has `U_info,r(t) > 0`.
2. The mandatory rescue set is non-empty and at least one mandatory job has a ready next operation.
3. A newly arrived job belongs to an `at_risk`, `arrival_dependent`, or `fragile` entity.
4. A ready operation from a high-risk entity competes for the same idle machine as an operation from a low-risk entity.
5. The current lightweight dispatch candidate would omit all ready jobs from `Cover_r(t)` for a non-secured entity.

If none of these conditions holds, use lightweight RG dispatch.

### Lightweight RG Dispatch

Lightweight RG dispatch directly selects current ready operations for idle machines with no ALNS. Its lexicographic priority for a candidate `(j, o, m)` is:

```text
dispatch_key(j,o,m) =
  lower service_rank first,
  earlier effective production deadline first,
  smaller processing time on machine m first,
  larger marginal service quantity first,
  smaller remaining job work first,
  smaller job_id first,
  smaller op_id first
```

`service_rank` is:

- `0` for mandatory rescue jobs.
- `1` for heuristic service-cover jobs of non-secured entities.
- `2` for jobs of `at_risk`, `arrival_dependent`, or `fragile` entities.
- `3` otherwise.

---

## 4. Affected-Set Construction

If ALNS is triggered, RG-RALNS constructs an affected set `A(t)` from visible incomplete jobs only:

```text
A(t) subseteq J_vis(t) \ J_done(t)
```

Future jobs outside `J_vis(t)` are not eligible for `A(t)`.

### Candidate Sources

A job can enter `A(t)` if it belongs to at least one source:

1. Newly arrived jobs at time `t`.
2. Mandatory rescue jobs.
3. Jobs in `Cover_r(t)` for non-secured entities.
4. Jobs of entities classified as `at_risk`, `arrival_dependent`, or `fragile`.
5. Jobs whose next operation is ready at time `t`.
6. Jobs that compete for the same eligible idle machines as mandatory or cover jobs.
7. Jobs whose next operations can block bottleneck machines needed by high-risk entities.

A bottleneck machine at time `t` is an idle machine that is eligible for at least one ready operation from a mandatory, cover, or high-risk entity job and at least one ready operation from another visible job. This definition is local to the current event time and does not require future job information.

### Freezing Rules

The following are frozen and cannot be changed by the local ALNS:

- Completed jobs and operations.
- Ongoing operations.
- Any operation already started.
- Jobs outside `A(t)`.
- Low-risk jobs that do not compete for machines with any mandatory or cover job.

### Size Limit

The affected set is capped:

```text
|A(t)| <= H_A
```

The default implementation should expose `H_A` as a single algorithm parameter. When candidates exceed `H_A`, select by this priority:

```text
mandatory first,
cover jobs second,
new high-risk arrivals third,
ready jobs of high-risk entities fourth,
bottleneck competitors fifth,
earlier effective deadline sixth,
smaller remaining work seventh
```

This cap prevents the method from degenerating into global backlog regeneration.

---

## 5. Local RG-ALNS

Local RG-ALNS searches only within `A(t)`. It treats frozen operations and jobs outside `A(t)` as fixed context.

### Initial Local Solution

Construct an initial local sequence for `A(t)` using a deterministic hybrid priority:

```text
initial_key(j) =
  service_rank(j),
  effective production deadline,
  remaining processing work,
  -marginal service quantity,
  job_id
```

Decode this sequence into a local schedule over available machines while respecting:

- current time `t`;
- operation precedence;
- machine eligibility;
- frozen ongoing operations;
- current machine availability.

### Destroy Operators

Each destroy operator removes a subset of jobs from the current local solution:

1. `destroy_blocking_mandatory`: remove jobs occupying machines needed by mandatory jobs.
2. `destroy_low_service_contribution`: remove jobs with low marginal service contribution and high processing burden.
3. `destroy_over_secured`: remove jobs from entities classified as secured or stable when they compete with high-risk work.
4. `destroy_bottleneck_blockers`: remove jobs that consume bottleneck machines used by high-risk entities.
5. `destroy_high_tardiness_low_service`: remove jobs with high visible tardiness contribution but low service contribution.

### Repair Operators

Each repair operator reinserts removed jobs:

1. `repair_mandatory_first`: insert mandatory rescue jobs before other removed jobs.
2. `repair_service_cover`: restore heuristic service-cover jobs until the cover is preserved.
3. `repair_recoverability_gain`: prioritize jobs with largest reduction in `U_info,r(t)` or service shortfall risk.
4. `repair_rg_regret_k`: use regret insertion where insertion cost includes service-rank deterioration before original objective change.
5. `repair_edd_spt`: fallback insertion by effective deadline and machine-specific processing time.

### Candidate Evaluation

Candidate local solutions are compared using the original objective components computed on the visible local context:

```text
Z = alpha * TT + beta * WSF
```

`WSF` denotes weighted service shortfall and is minimized.

### Local Proxy Evaluation versus Final Global Evaluation

Because RG-RALNS is an online local rescheduling algorithm, the candidate evaluation inside local ALNS is not the final global objective over all jobs in the experimental instance. At event time `t`, future unreleased jobs are not visible and jobs outside `A(t)` are frozen for the current local search. Therefore, local ALNS compares candidates using a current-information local proxy:

```text
Z_loc,t(S') = alpha * TT_loc,t(S') + beta * WSF_loc,t(S')
```

where `TT_loc,t` and `WSF_loc,t` are computed from the fixed completed-job context, the currently visible information, and the candidate local schedule over `A(t)`. Future unreleased jobs do not enter `Z_loc,t` through concrete release times, processing times, routes, or machine eligibility. They can only affect the recoverability diagnosis through the aggregate quantity buffer `Q_future,r(t)`.

The final reported benchmark objective remains the global objective:

```text
Z_global = alpha * TT_global + beta * WSF_global
```

computed after the simulation finishes and all jobs have arrived and completed. Thus, local ALNS uses `Z_loc,t` only to compare alternative local rescheduling decisions under the current online information view; it does not claim to optimize the full future schedule at each event time.

The recoverability diagnostics are not converted into a multi-parameter penalty objective. They guide trigger, affected-set construction, neighborhoods, and acceptance.

### Hierarchical Acceptance

Accept candidate solution `S'` over incumbent `S` using this hierarchy:

1. Reject `S'` if it increases current-information shortfall risk for any entity.
2. Accept `S'` if it lowers weighted service shortfall `WSF`.
3. If `WSF` is unchanged, accept `S'` if it lowers `Z`.
4. If `WSF` and `Z` are unchanged within numerical tolerance, accept `S'` if it changes fewer frozen-adjacent decisions or preserves more current local order.

This keeps service feasibility lexicographically dominant without introducing additional tuning weights.

---

## 6. Execution Policy

The ALNS result is not treated as a commitment to future execution. It is a local decision structure used to choose current feasible actions.

At time `t`, RG-RALNS submits only operations satisfying:

- job has arrived and is visible;
- operation is the next operation of the job;
- operation is not completed and not ongoing;
- machine is idle at time `t`;
- machine is eligible for the operation;
- start time equals `t`.

All unexecuted local-solution decisions are discarded after the algorithm call. The next event triggers a fresh diagnosis and possibly a new local ALNS.

---

## 7. Pseudocode

```text
Algorithm RG-RALNS at event time t

Input:
  online view I(t), schedule state S(t), previous diagnostics D(t-)

1. Build visible ready set R(t)
2. Compute recoverability diagnostics:
     Q_sec,r(t), Q_rem,r(t), Q_rec,r(t), Q_future,r(t), Q_cover,r(t)
     U_info,r(t), mandatory rescue jobs, Cover_r(t), class_r(t)
3. Determine whether ALNS is triggered

4. If ALNS is not triggered:
     decisions <- LightweightRGDispatch(R(t), diagnostics)
     return feasible decisions at time t

5. Construct affected set A(t):
     collect candidate jobs from arrivals, mandatory jobs, cover jobs,
     high-risk entities, ready jobs, and bottleneck competitors
     remove frozen jobs and operations
     truncate to H_A by deterministic priority

6. Build initial local solution over A(t)

7. For iter = 1,...,N_A:
     choose destroy operator using adaptive weights
     remove selected jobs from local solution
     choose repair operator using adaptive weights
     reinsert removed jobs
     evaluate candidate with WSF and Z
     accept by hierarchical acceptance rule
     update adaptive operator weights

8. Extract current feasible operations from accepted local solution
9. If extraction returns no feasible operation:
     decisions <- LightweightRGDispatch(R(t), diagnostics)
10. Return decisions
```

---

## 8. Implementation Boundaries

RG-RALNS should be implemented as a new algorithm module rather than by mutating the legacy rolling-horizon implementation in place.

Recommended module:

```text
sl_isp_rg_rho_lns/src/algorithms/rg_ralns.py
```

Legacy `rg_rho_lns_fast.py` remains available for ablation and historical comparison. Paper A's main algorithm should refer to RG-RALNS once implemented and validated.

---

## 9. Validation Expectations

The implementation must include tests proving:

1. Future job details are invisible to RG-RALNS before arrival.
2. `Q_future,r(t)` changes only when jobs arrive.
3. Mandatory rescue jobs are computed from visible recoverable jobs and aggregate future quantity.
4. Heuristic service cover is deterministic and does not require solving an exact set-cover problem.
5. ALNS trigger conditions are deterministic.
6. `A(t)` excludes future jobs and respects `H_A`.
7. Completed and ongoing operations are frozen.
8. Lightweight RG dispatch runs when no trigger condition holds.
9. Local ALNS runs only on `A(t)`.
10. The execution policy returns only operations feasible at current time `t`.

Benchmark reporting should compare at least:

- EDD baseline.
- Lightweight RG dispatch ablation.
- Legacy rolling-horizon RG-ALNS, if retained as an ablation.
- RG-RALNS main method.

Metrics:

- `Z`.
- `TT`.
- `WSF`, defined as weighted service shortfall.
- zero-shortfall entity rate.
- runtime.
- number of ALNS trigger events.
- average affected-set size.
