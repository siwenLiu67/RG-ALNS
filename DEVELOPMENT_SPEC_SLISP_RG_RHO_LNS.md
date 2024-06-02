# DEVELOPMENT_SPEC.md

# SL-ISP Research Codebase Development Specification

## 1. Project Goal

This project implements the complete research codebase for a paper on:

> **Service-Level-Aware Flexible Job-Shop Scheduling with Recoverability-Guided Rolling-Horizon Optimization**

The scheduling problem is referred to as:

> **SL-ISP: Service-Level-Aware Integrated Scheduling Problem**

The proposed solution framework is:

> **RG-RHO-LNS: Recoverability-Guided Rolling-Horizon Optimization with Adaptive Large-Neighborhood Search**

This development specification covers:

1. Problem definition and objective.
2. Core data model.
3. Instance generation and dynamic scenarios.
4. Recoverability-theory metrics.
5. Exact validation model.
6. Baseline algorithms.
7. Proposed RG-RHO-LNS algorithm.
8. Experiment pipeline.
9. Result logging.
10. Automatic generation of 6 paper tables and 7 paper figures.
11. Recommended development phases and acceptance criteria.

---

# 2. Research Problem Definition

## 2.1 Jobs

Each job \(j\in\mathcal J\):

- belongs to a service entity \(r=g(j)\);
- has a release time \(r_j\);
- has a contribution quantity \(q_j\);
- contains a sequence of ordered operations:
  \[
  \mathcal O*j = \{O*{j1}, O*{j2}, \ldots, O*{j|\mathcal O_j|}\};
  \]
- each operation \(O*{jo}\) can be processed by one of several eligible machines:
  \[
  \mathcal M*{jo}\subseteq \mathcal M;
  \]
- processing time depends on the selected machine:
  \[
  p*{joh}, \qquad h\in\mathcal M*{jo}.
  \]

The production completion time of job \(j\) is denoted by \(C_j\).

---

## 2.2 Service Entities

Each service entity \(r\in\mathcal R\):

- has a deadline \(d_r\);
- has a transport delay \(\tau_r\);
- has a total assigned quantity:
  \[
  Q*r=\sum*{j:g(j)=r} q_j;
  \]
- has a required minimum on-time fulfillment ratio:
  \[
  \rho_r\in(0,1];
  \]
- therefore has minimum service requirement:
  \[
  Q_r^{\min}=\rho_rQ_r;
  \]
- has an importance weight \(w_r\).

The delivery time of job \(j\) is:

\[
D*j=C_j+\tau*{g(j)}.
\]

---

## 2.3 Objective Function

The model jointly optimizes:

1. job-level delivery tardiness;
2. entity-level service shortfall.

### Job tardiness

\[
T*j=\max\{0,D_j-d*{g(j)}\}.
\]

### Service shortfall

Let the on-time fulfilled quantity for entity \(r\) be:

\[
Q*r^{\mathrm{on-time}}
=
\sum*{j:g(j)=r,\ D_j\le d_r} q_j.
\]

Then the entity-level shortfall is:

\[
U_r=
\max\left\{
0,
Q_r^{\min}-Q_r^{\mathrm{on-time}}
\right\}.
\]

### Weighted objective

\[
Z=
\alpha\sum\_{j\in\mathcal J}T_j

- \beta\sum\_{r\in\mathcal R}w_rU_r.
  \]

  ***

# 3. Target Algorithm

## 3.1 Main Algorithm

The target solution method is:

> **RG-RHO-LNS: Recoverability-Guided Rolling-Horizon Optimization with Adaptive Large-Neighborhood Search**

It contains five major modules:

1. Event-triggered scheduling updates.
2. Recoverability diagnosis.
3. Recoverability-guided active set construction.
4. Restricted rolling-horizon exact local optimization.
5. Bandit-controlled recovery-oriented LNS refinement.

The overall algorithmic pipeline is:

\[
\text{Event Trigger}
\rightarrow
\text{Recoverability Diagnosis}
\rightarrow
\text{Active Set Construction}
\rightarrow
\text{Restricted Rolling-Horizon Optimization}
\rightarrow
\text{Adaptive Recovery-Oriented LNS Repair}.
\]

---

# 4. Development Technology Stack

## 4.1 Required Language and Libraries

Use:

- Python 3.11+
- numpy
- pandas
- scipy
- matplotlib
- ortools
- tqdm
- pyyaml
- dataclasses or pydantic
- pathlib
- typing

## 4.2 Solver Use

### OR-Tools CP-SAT

Use OR-Tools CP-SAT for:

1. exact small-instance validation;
2. rolling-horizon subproblem optimization;
3. local exact repair in LNS neighborhoods.

All variables must be integer-valued.

### Knapsack Subproblems

For the recoverability calculations:

- use dynamic programming by default;
- the implementation must support integer capacities and quantities;
- design the API so that a MILP/CP-SAT fallback can be added later if needed.

---

# 5. Project Directory Structure

```text
sl_isp_rg_rho_lns/
│
├── configs/
│   ├── default.yaml
│   ├── instance_groups.yaml
│   ├── algorithms.yaml
│   └── experiments.yaml
│
├── data/
│   ├── raw_instances/
│   ├── generated_instances/
│   └── experiment_logs/
│
├── outputs/
│   ├── tables/
│   ├── figures/
│   ├── raw_results/
│   └── summaries/
│
├── src/
│   ├── core/
│   │   ├── dataclasses.py
│   │   ├── instance.py
│   │   ├── schedule_state.py
│   │   ├── simulator.py
│   │   ├── event_queue.py
│   │   └── objective.py
│   │
│   ├── generation/
│   │   ├── instance_generator.py
│   │   └── scenario_builder.py
│   │
│   ├── recoverability/
│   │   ├── earliest_bounds.py
│   │   ├── capacity_pool.py
│   │   ├── knapsack_recovery.py
│   │   ├── shortfall_bounds.py
│   │   └── mandatory_jobs.py
│   │
│   ├── solvers/
│   │   ├── exact_small_cp_sat.py
│   │   ├── rolling_horizon_cp_sat.py
│   │   └── local_repair_cp_sat.py
│   │
│   ├── algorithms/
│   │   ├── dispatching_rules.py
│   │   ├── plain_rho.py
│   │   ├── rho_lns.py
│   │   ├── rg_rho_lns.py
│   │   ├── neighborhoods.py
│   │   └── bandit_controller.py
│   │
│   ├── experiments/
│   │   ├── run_small_validation.py
│   │   ├── run_main_benchmark.py
│   │   ├── run_dynamic_benchmark.py
│   │   ├── run_ablation.py
│   │   ├── run_sensitivity.py
│   │   └── experiment_registry.py
│   │
│   ├── analysis/
│   │   ├── aggregate_results.py
│   │   ├── statistical_tests.py
│   │   ├── build_tables.py
│   │   └── plot_figures.py
│   │
│   └── utils/
│       ├── io.py
│       ├── random_seed.py
│       ├── logging_utils.py
│       └── validation.py
│
├── tests/
│   ├── test_instance_generation.py
│   ├── test_recoverability.py
│   ├── test_knapsack.py
│   ├── test_simulator.py
│   ├── test_baselines.py
│   └── test_rg_rho_lns.py
│
├── main.py
├── requirements.txt
└── README.md
```

---

# 6. Core Data Model

## 6.1 Required Dataclasses

Implement the following data classes.

### OperationAlternative

```python
OperationAlternative(
    machine_id: int,
    processing_time: int
)
```

### Operation

```python
Operation(
    op_id: int,
    job_id: int,
    sequence_index: int,
    alternatives: list[OperationAlternative]
)
```

### Job

```python
Job(
    job_id: int,
    entity_id: int,
    release_time: int,
    quantity: int,
    operations: list[Operation]
)
```

### ServiceEntity

```python
ServiceEntity(
    entity_id: int,
    deadline: int,
    rho: float,
    weight: float,
    total_quantity: int,
    transport_delay: int
)
```

### Machine

```python
Machine(
    machine_id: int
)
```

### SLISPInstance

```python
SLISPInstance(
    jobs: list[Job],
    entities: list[ServiceEntity],
    machines: list[Machine],
    alpha: float,
    beta: float,
    metadata: dict
)
```

### ScheduledOperation

```python
ScheduledOperation(
    job_id: int,
    op_id: int,
    machine_id: int,
    start_time: int,
    end_time: int
)
```

### ScheduleState

Required fields:

```python
ScheduleState(
    current_time: int,
    machine_available_times: dict[int, int],
    completed_operations: set[tuple[int, int]],
    ongoing_operations: dict[tuple[int, int], ScheduledOperation],
    scheduled_operations: list[ScheduledOperation],
    completed_jobs: dict[int, int],
    delivered_on_time_jobs: set[int],
    event_queue: EventQueue
)
```

---

# 7. Dynamic Instance Generation

## 7.1 Benchmark Groups

The code must support at least the following benchmark groups.

### Group S: Small exact-validation instances

Purpose:

- exact CP-SAT validation;
- gap calculation.

Suggested ranges:

| Factor           | Range                    |
| ---------------- | ------------------------ |
| Jobs             | 10, 15, 20               |
| Machines         | 5                        |
| Entities         | 3                        |
| Operations/job   | 2–4                      |
| Arrival pattern  | static or weakly dynamic |
| Service pressure | medium                   |
| Instances/config | 10                       |

---

### Group M: Main benchmark instances

Purpose:

- main performance comparison.

Suggested ranges:

| Factor            | Range             |
| ----------------- | ----------------- |
| Jobs              | 30, 45, 60        |
| Machines          | 8, 10, 12         |
| Entities          | 3, 5              |
| Operations/job    | 3–6               |
| Service pressure  | low, medium, high |
| Deadline pressure | moderate, tight   |
| Instances/config  | 10–20             |

---

### Group D: Dynamic benchmark instances

Purpose:

- dynamic arrival performance;
- event-driven scheduling evaluation.

Suggested ranges:

| Factor            | Range             |
| ----------------- | ----------------- |
| Jobs              | 60–100            |
| Machines          | 10–15             |
| Entities          | 5                 |
| Operations/job    | 3–6               |
| Arrival intensity | low, medium, high |
| Service pressure  | medium, high      |
| Instances/config  | 10                |

---

### Larger stress-test instances

Purpose:

- optional runtime/scalability support;
- not necessarily a standalone core experiment.

Suggested ranges:

| Factor            | Range       |
| ----------------- | ----------- |
| Jobs              | 120, 150    |
| Machines          | 15–20       |
| Entities          | 5, 8        |
| Arrival intensity | medium      |
| Service pressure  | medium/high |

---

## 7.2 Service Pressure Settings

Use:

| Level  | \(\rho_r\) range |
| ------ | ---------------- |
| Low    | 0.50–0.60        |
| Medium | 0.70–0.80        |
| High   | 0.85–0.95        |

---

## 7.3 Deadline Tightness

Generate deadlines using a configurable tightness factor:

\[
d_r=
\kappa\cdot \widehat C_r^{\mathrm{ref}}+\tau_r.
\]

Suggested settings:

| Level    | \(\kappa\) |
| -------- | ---------- |
| Loose    | 1.2        |
| Moderate | 1.0        |
| Tight    | 0.8        |

---

## 7.4 Entity Weight Patterns

Support:

| Pattern              | Weights             |
| -------------------- | ------------------- |
| Uniform              | \(w_r=1\)           |
| Mild heterogeneity   | \(w_r\in\{1,2,3\}\) |
| Strong heterogeneity | \(w_r\in\{1,3,5\}\) |

---

## 7.5 Dynamic Arrival Scenarios

Implement:

### Low intensity

- most jobs arrive early;
- few later jobs.

### Medium intensity

- jobs arrive in multiple waves.

### High intensity

- jobs arrive continuously;
- larger share of late arrivals;
- more pressure on rescheduling.

---

# 8. Event-Driven Scheduling Simulator

The simulator must process:

1. job arrival events;
2. operation completion events;
3. machine release events;
4. rescheduling triggers.

At every scheduling event:

- update machine status;
- update ready operations;
- update job completion and delivery status;
- call scheduling algorithm;
- log event-level state.

---

# 9. Objective and Output Metrics

## 9.1 Final Metrics

Every algorithm run must output:

1. weighted objective:
   \[
   Z
   \]
2. total tardiness:
   \[
   TT=\sum_jT_j
   \]
3. weighted service shortfall:
   \[
   WSF=\sum_rw_rU_r
   \]
4. zero-shortfall entity rate:
   \[
   ZSR=\frac{|\{r:U_r=0\}|}{|\mathcal R|}
   \]
5. total runtime;
6. number of rescheduling events;
7. average time per event.

---

# 10. Recoverability-Theory Metrics

This section defines the core computations required by the theoretical design.

## 10.1 Secured Quantity

For entity \(r\), define:

\[
Q*r^{\mathrm{sec}}(t)
=
\sum*{j\in\mathcal J_r^{\mathrm{sec}}(t)}q_j
\]

where:

\[
\mathcal J_r^{\mathrm{sec}}(t)
=
\{j:
C_j\le t,\;
C_j+\tau_r\le d_r
\}.
\]

---

## 10.2 Remaining Service Requirement

\[
Q_r^{\mathrm{rem}}(t)
=
\max\{0,Q_r^{\min}-Q_r^{\mathrm{sec}}(t)\}.
\]

---

## 10.3 Optimistic Earliest Delivery Lower Bound

For a job \(j\):

- completed operation: residual time \(0\);
- ongoing operation: committed end minus current time;
- unstarted operation: minimum processing time among eligible machines.

Then:

\[
\underline C_j(t)
=
\max\{t,r_j\}

- \sum*{o\in\mathcal O_j}
  \underline p*{jo}(t)
  \]

and

\[
\underline D*j(t)
=
\underline C_j(t)+\tau*{g(j)}.
\]

---

## 10.4 Eligible Recovery Set

\[
\mathcal E_r(t)
=
\{
j\in\mathcal J_r^{\mathrm{open}}(t):
\underline D_j(t)\le d_r
\}.
\]

---

## 10.5 Resource Pool Capacity

Let \(\mathcal B\subseteq\mathcal M\) denote an unavoidable resource pool.

For machine \(h\in\mathcal B\):

\[
a_h(t)
=
\begin{cases}
t, & h \text{ idle at } t\\
f_h(t), & h \text{ currently processing a non-preemptive operation}
\end{cases}
\]

Then:

\[
\operatorname{Cap}_{\mathcal B}(t,d_r)
=
\sum_{h\in\mathcal B}
[d_r-a_h(t)]\_+.
\]

---

## 10.6 Unavoidable Resource-Pool Workload

For job \(j\), define:

\[
\underline w*{j,\mathcal B}(t)
=
\sum*{o\in\mathcal O*j}
\underline p*{jo}^{\mathcal B}(t).
\]

Rules:

- completed operation: \(0\);
- ongoing operation on \(h\in\mathcal B\): remaining processing time;
- ongoing operation on \(h\notin\mathcal B\): \(0\);
- unstarted operation whose entire eligible machine set is contained in \(\mathcal B\): minimum processing time;
- otherwise \(0\).

---

## 10.7 Maximum Recoverable Service Quantity

Solve:

\[
\overline Q*{r,\mathcal B}^{\mathrm{rec}}(t)
=
\max
\sum*{j\in\mathcal E_r(t)}q_jz_j
\]

subject to:

\[
\sum*{j\in\mathcal E_r(t)}
\underline w*{j,\mathcal B}(t)z*j
\le
\operatorname{Cap}*{\mathcal B}(t,d_r)
\]

\[
z_j\in\{0,1\}.
\]

Implementation:

- exact DP by default;
- return objective and selected job set.

---

## 10.8 Unavoidable Shortfall Lower Bound

\[
\underline U\_{r,\mathcal B}(t)
=
\max\{
0,
Q_r^{\mathrm{rem}}(t)

- \overline Q\_{r,\mathcal B}^{\mathrm{rec}}(t)
  \}.
  \]

  ***

## 10.9 Mandatory Rescue Jobs

For each \(j\in\mathcal E_r(t)\), solve exclusion recoverability:

\[
\overline Q\_{r,\mathcal B}^{\mathrm{rec},-j}(t).
\]

Then job \(j\) is mandatory if:

\[
\overline Q\_{r,\mathcal B}^{\mathrm{rec}}(t)
\ge
Q_r^{\mathrm{rem}}(t)
\]

and

\[
\overline Q\_{r,\mathcal B}^{\mathrm{rec},-j}(t)
<
Q_r^{\mathrm{rem}}(t).
\]

---

## 10.10 Mandatory Job Classification

Classify:

### Quantity-mandatory

\[
\sum\_{i\in\mathcal E_r(t)\setminus\{j\}}q_i
<
Q_r^{\mathrm{rem}}(t).
\]

### Capacity-mandatory

\[
\sum\_{i\in\mathcal E_r(t)\setminus\{j\}}q_i
\ge
Q_r^{\mathrm{rem}}(t)
\]

but

\[
\overline Q\_{r,\mathcal B}^{\mathrm{rec},-j}(t)
<
Q_r^{\mathrm{rem}}(t).
\]

---

# 11. Algorithms to Implement

## 11.1 Dispatching Rule Baselines

Implement:

1. EDD-like rule.
2. Service-weighted deadline rule.
3. Shortfall-greedy rule.

---

## 11.2 Plain RHO Baseline

Rolling-horizon optimization:

- fixed horizon \(H\);
- active jobs selected only by temporal proximity and deadline risk;
- no recoverability guidance;
- no LNS.

---

## 11.3 RHO-LNS Baseline

Rolling horizon + generic LNS:

- random operation-block neighborhood;
- tardiness block neighborhood;
- congestion block neighborhood;
- fixed cyclic neighborhood selection;
- no recoverability guidance.

---

## 11.4 Exact Small-Scale CP-SAT

For small instances:

- optional interval variables for machine assignment;
- precedence constraints;
- no-overlap constraints;
- job completion times;
- delivery times;
- on-time indicators;
- tardiness variables;
- service shortfall variables;
- full objective.

Used only for small-scale validation.

---

# 12. Proposed RG-RHO-LNS Algorithm

## 12.1 Event Trigger

Trigger scheduling at:

1. job arrivals;
2. operation completions;
3. machine releases;
4. service-recovery risk transitions if implemented.

---

## 12.2 Entity Classification

At each event time \(t\), classify each entity:

### SECURED

\[
Q_r^{\mathrm{rem}}(t)=0.
\]

### STABLE_RECOVERABLE

\[
\underline U\_{r,\mathcal B}(t)=0
\]
and surplus is above threshold.

### FRAGILE_RECOVERABLE

\[
\underline U\_{r,\mathcal B}(t)=0
\]
and surplus is small.

### PARTIALLY_UNRECOVERABLE

\[
\underline U\_{r,\mathcal B}(t)>0.
\]

---

## 12.3 Active Job Set

Construct:

\[
\mathcal J^{\mathrm{act}}(t)
=
\mathcal J^{\mathrm{man}}(t)
\cup
\mathcal J^{\mathrm{frag}}(t)
\cup
\mathcal J^{\mathrm{loss}}(t)
\cup
\mathcal J^{\mathrm{tar}}(t)
\cup
\mathcal J^{\mathrm{conf}}(t).
\]

### Mandatory jobs

\[
\mathcal J^{\mathrm{man}}(t)
=
\bigcup_r\mathcal M_r(t).
\]

### Fragile-entity jobs

Score:

\[
\phi*j^{\mathrm{frag}}(t)
=
\frac{q_j}
{\underline w*{j,\mathcal B}(t)+\varepsilon}
\cdot
\frac{1}
{S\_{r,\mathcal B}^{\mathrm{rec}}(t)+\varepsilon}.
\]

### Loss-reduction jobs

Score:

\[
\phi*j^{\mathrm{loss}}(t)
=
\frac{w_rq_j}
{\underline w*{j,\mathcal B}(t)+\varepsilon}.
\]

### Tardiness-risk jobs

Score:

\[
\phi_j^{\mathrm{tar}}(t)
=
\frac{1}
{\max\{\varepsilon,d_r-\underline D_j(t)\}}.
\]

### Conflict jobs

Include jobs that:

- share candidate machines with mandatory or fragile jobs;
- occupy local critical capacity windows;
- create direct machine competition.

---

## 12.4 Restricted Rolling-Horizon Optimization

Use CP-SAT to optimize a restricted local subproblem.

### Freeze

- completed operations;
- ongoing operations;
- selected non-active committed operations.

### Reoptimize

- active jobs;
- selected conflicting operations.

### Local objective

\[
\alpha\sum\_{j\in\mathcal J^{\mathrm{act}}} \widehat T_j

- \beta\sum\_{r\in\mathcal R^{\mathrm{act}}}w_r\widehat U_r
- \lambda\cdot \mathrm{Disrupt}(t).
  \]

  ***

## 12.5 Recovery-Oriented Neighborhoods

Implement four neighborhoods.

### \(N_1\): Mandatory Rescue Neighborhood

Destroy/unfreeze:

- operations of mandatory jobs;
- their local machine conflicts.

### \(N_2\): Capacity Relief Neighborhood

Destroy/unfreeze:

- operations occupying critical resource-pool windows;
- operations that can be migrated away from \(\mathcal B\);
- operations conflicting with capacity-mandatory jobs.

### \(N_3\): Shortfall Reduction Neighborhood

Destroy/unfreeze:

- jobs from partially unrecoverable entities with high recovery potential;
- local conflicting operations.

### \(N_4\): Tardiness Rebalancing Neighborhood

Destroy/unfreeze:

- jobs with high tardiness risk;
- local critical operations causing tardiness propagation.

---

## 12.6 Bandit-Based Neighborhood Selection

Use UCB1 by default.

Each neighborhood is an arm.

Reward:

\[
R*k
=
\omega_1\Delta Z*{\mathrm{norm}}

- \omega*2\Delta\left(\sum_r \underline U*{r,\mathcal B}\right)\_{\mathrm{norm}}
- \omega*3\Delta\left(\sum_r|\mathcal M_r|\right)*{\mathrm{norm}}.
  \]

  ***

## 12.7 Acceptance Rule

Default implementation:

Accept a candidate schedule if:

1. the objective improves, or
2. the weighted service shortfall improves materially without unacceptable worsening of total objective.

This acceptance rule must be configurable.

---

# 13. Experiment Design

The paper experiments are organized around a balanced 6-table and 7-figure structure.

---

# 14. Paper Tables

## Table 1. Benchmark Configuration

Columns:

- Group
- Jobs
- Machines
- Entities
- Operations per job
- Arrival pattern
- \(\rho_r\) range
- deadline tightness
- weight pattern
- number of instances

---

## Table 2. Small-Scale Validation Against Exact CP-SAT

Columns:

- InstanceGroup
- Exact_Z
- RG_RHO_LNS_Z
- Gap_percent
- Exact_TT
- RG_TT
- Exact_WSF
- RG_WSF
- Exact_runtime
- RG_runtime

---

## Table 3. Overall Performance on Benchmark Instances

Rows:

- InstanceGroup × Method

Columns:

- Z_mean
- Z_std
- TT_mean
- TT_std
- WSF_mean
- WSF_std
- ZSR_mean
- Runtime_mean
- Improvement_vs_best_baseline_percent

---

## Table 4. Dynamic Benchmark Performance

Rows:

- ArrivalIntensity × Method

Columns:

- Z_mean
- TT_mean
- WSF_mean
- ZSR_mean
- Events_mean
- Avg_rescheduling_time
- Runtime_total

---

## Table 5. Ablation of Recoverability-Guided Mechanisms

Rows:

- Full RG-RHO-LNS
- w/o recoverability-guided active set
- w/o mandatory rescue prioritization
- w/o recovery-oriented neighborhoods
- RHO only

Columns:

- Z_mean
- TT_mean
- WSF_mean
- ZSR_mean
- Relative_Z_deterioration_percent
- Relative_WSF_deterioration_percent

---

## Table 6. Bandit Control and Computational Behavior

### Panel A

Rows:

- Full bandit
- Random neighborhood selection
- Fixed cyclic neighborhood selection

Columns:

- Z
- WSF
- ZSR
- Runtime

### Panel B

Rows:

- Scenario group

Columns:

- AvgActiveJobs
- AvgRepairOps
- AvgLNSIterations
- AvgTimePerEvent

---

# 15. Paper Figures

## Figure 1. Service-Pressure Sensitivity

X-axis:

- \(\rho_r\) level or numerical \(\rho_r\)

Y-axis:

- Panel A: WSF
- Panel B: Z

Lines:

- RG-RHO-LNS
- RHO-LNS
- Plain RHO
- Best rule baseline

---

## Figure 2. Dynamic-Intensity Sensitivity

X-axis:

- low / medium / high dynamic arrival intensity

Y-axis:

- Panel A: Z
- Panel B: ZSR

Lines:

- RG-RHO-LNS
- RHO-LNS
- Plain RHO
- Best rule baseline

---

## Figure 3. Unavoidable Shortfall Lower Bound vs. Realized Shortfall

X-axis:

- \(\underline U\_{r,\mathcal B}(t)\)

Y-axis:

- final realized \(U_r\)

Plot:

- scatter plot or binned box plot

Additional output:

- Pearson and Spearman correlation.

---

## Figure 4. Recoverability Evolution on a Representative Dynamic Instance

X-axis:

- decision event index or time

Panels:

1. \( \overline Q\_{r,\mathcal B}^{\mathrm{rec}}(t) \) and \( Q_r^{\mathrm{rem}}(t) \)
2. \( \underline U\_{r,\mathcal B}(t) \)
3. \( |\mathcal M_r(t)| \)

---

## Figure 5. Mandatory Rescue Protection Behavior

X-axis:

- methods or algorithm variants

Y-axis:

- Mandatory Rescue On-Time Ratio:
  \[
  \mathrm{MOR}
  =
  \frac{
  \text{on-time mandatory rescue jobs}
  }{
  \text{identified mandatory rescue jobs}
  }.
  \]

Optional second panel:

- zero-shortfall success rate among entities containing mandatory jobs.

---

## Figure 6. Neighborhood Operator Usage Under Bandit Control

X-axis:

- \(N_1, N_2, N_3, N_4\)

Y-axis:

- selection frequency

Optional second panel:

- average reward per neighborhood.

---

## Figure 7. Sensitivity to \(\gamma=\beta/\alpha\)

X-axis:

- \(\gamma\) levels

Y-axis:

- Panel A: TT
- Panel B: WSF

Lines:

- RG-RHO-LNS
- selected baselines.

---

# 16. Result Logging

## 16.1 Run-Level Results

Each algorithm run must output one row with:

- instance_id
- scenario_group
- algorithm
- seed
- Z
- TT
- WF
- ZSR
- runtime_total
- events_count
- avg_time_per_event
- mandatory_jobs_identified_total
- mandatory_jobs_on_time_total
- shortfall_lower_bound_final_sum
- config_hash
- timestamp

---

## 16.2 Event-Level Logs

Each event log row must contain:

- instance_id
- algorithm
- seed
- event_index
- time
- entity_id
- Q_rem
- Q_rec_bar
- U_lower
- S_rec
- mandatory_count
- entity_class
- active_set_size
- selected_neighborhood
- neighborhood_reward
- accepted
- local_repair_runtime
- current_partial_Z
- current_partial_TT
- current_partial_WSF

These logs will support Figures 3–6.

---

# 17. Experiment Scripts

Implement:

1. `run_small_validation.py`
2. `run_main_benchmark.py`
3. `run_dynamic_benchmark.py`
4. `run_ablation.py`
5. `run_sensitivity.py`

All must:

- read YAML configs;
- write raw outputs;
- support reproducible seeds;
- support resume if partial results exist;
- record config hashes;
- avoid overwriting raw logs unintentionally.

---

# 18. Aggregation and Statistical Analysis

Implement:

## aggregate_results.py

- group results by instance group and method;
- compute mean, std, relative improvement;
- export CSV/Excel/LaTeX-ready tables.

## statistical_tests.py

Provide:

- Wilcoxon signed-rank test;
- optional paired effect size;
- summary tables for key comparisons.

---

# 19. Development Phases

## Phase 1. Foundation

Deliver:

- data classes;
- instance generator;
- simulator;
- objective computation.

Acceptance:

- instances generated correctly;
- trivial rule schedules feasible solutions;
- objective calculation matches hand-built examples.

---

## Phase 2. Recoverability Metrics

Deliver:

- \(Q_r^{sec}\);
- \(Q_r^{rem}\);
- \(\underline D_j(t)\);
- \(\mathcal E_r(t)\);
- \(\operatorname{Cap}\_{\mathcal B}(t,d_r)\);
- \(\underline w\_{j,\mathcal B}(t)\);
- \(\overline Q\_{r,\mathcal B}^{rec}(t)\);
- \(\underline U\_{r,\mathcal B}(t)\);
- mandatory rescue jobs.

Acceptance:

- manually constructed toy examples match analytical calculations;
- quantity-mandatory and capacity-mandatory cases tested.

---

## Phase 3. Baselines and Exact Solver

Deliver:

- three dispatching rules;
- plain RHO;
- RHO-LNS;
- exact small-scale CP-SAT.

Acceptance:

- all methods produce feasible schedules;
- exact solver solves tiny instances;
- initial comparisons generate meaningful result differences.

---

## Phase 4. RG-RHO-LNS

Deliver:

- event loop;
- recoverability diagnosis;
- entity classification;
- active set;
- rolling repair;
- four neighborhoods;
- bandit controller.

Acceptance:

- proposed algorithm runs end-to-end;
- logs all required event-level fields;
- mandatory jobs enter active set;
- neighborhood rewards update correctly.

---

## Phase 5. Experiment Pipeline

Deliver:

- all experiment scripts;
- result aggregation;
- Tables 1–6 generation;
- Figures 1–7 generation.

Acceptance:

- one command runs each experiment group;
- all raw logs are saved;
- all tables and figures are reproducibly generated from saved raw results.

---

# 20. Recommended Development Order for AI Coding Agents

Do not attempt to implement the full system in one pass.

Recommended order:

1. Implement Phase 1.
2. Run unit tests and produce a minimal feasible schedule.
3. Implement Phase 2.
4. Validate recoverability metrics on hand-built tiny examples.
5. Implement Phase 3.
6. Confirm exact solver and baselines work.
7. Implement Phase 4.
8. Confirm RG-RHO-LNS runs end-to-end.
9. Implement Phase 5.
10. Run preliminary experiments before full-scale computational study.

---

# 21. Coding Quality Requirements

- Use modular functions and classes.
- Avoid monolithic scripts.
- Add type hints.
- Use dataclasses or pydantic models for structured state.
- Every public method should have a docstring.
- All random generation must be seed-controlled.
- No silent exception swallowing.
- Log warnings and failures clearly.
- Unit tests must cover core recoverability logic.
- Raw experiment logs must be immutable once generated.

---

# 22. Immediate Next Task

The next coding step should be:

> **Phase 1: Implement foundational data structures, dynamic instance generation, scheduling state, event-driven simulation, and objective calculation.**

Do not begin the RG-RHO-LNS algorithm before Phase 1 and Phase 2 have passed their tests.
