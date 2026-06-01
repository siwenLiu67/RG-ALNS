# RG-ALNS Main Algorithm Record

Last updated: 2026-06-01

This document fixes the manuscript-level definition of the proposed main
algorithm after the naming and design discussion on 2026-06-01.

## 1. Final Algorithm Name

The proposed method should be named:

```text
RG-ALNS
```

Full name:

```text
Recoverability-Guided Adaptive Large Neighborhood Search
```

Chinese name:

```text
可恢复性引导自适应大邻域搜索算法
```

Use `RG-ALNS` in the manuscript, tables, figures, captions, and final
experiment labels.

The current code still contains legacy names such as `NR-RG-RHO-LNS`,
`SRG-RHO-LNS`, and `RG-RHO-LNS-Fast`. These are implementation-history names,
not the final manuscript name.

## 2. Method Positioning

RG-ALNS is not a generic ALNS applied directly to SL-ISP. Its intended
positioning is:

```text
an event-driven rolling-horizon ALNS framework guided by structural
service-recoverability indicators.
```

The core contribution is not merely the use of ALNS. The contribution is that
the recoverability theory is embedded into:

- projected schedule construction;
- job-level priority scoring;
- adaptive destroy and repair neighborhood probabilities;
- recoverability-guided destroy and repair operators;
- bounded local exact repair;
- objective-consistent incumbent acceptance.

The manuscript should introduce it as:

```text
We propose a Recoverability-Guided Adaptive Large Neighborhood Search
(RG-ALNS) algorithm for the SL-ISP.
```

Then explain that RG-ALNS operates in an event-driven rolling-horizon manner.
Rolling horizon is the operating mode; it does not need to appear in the
algorithm abbreviation.

## 3. Objective

All candidate schedules and accepted improvements are evaluated by the original
SL-ISP objective:

```text
Z = alpha * TT + beta * WSF
```

where:

- `TT` is total delivery tardiness;
- `WSF` is weighted service shortfall.

For the current final-validation configuration:

```text
alpha = 1.0
beta  = 1.0
```

Recoverability indicators guide the search, but the final selection criterion
remains the original objective `Z`.

## 4. Source Files in the Current Code

Current implementation source of truth:

- `sl_isp_rg_rho_lns/src/algorithms/rg_rho_lns_fast.py`
- `sl_isp_rg_rho_lns/src/experiments/run_pilot_benchmark.py`
- `sl_isp_rg_rho_lns/configs/final_v13_validation.yaml`

Main implementation entry points:

- factory path: `_create_algorithm(..., type="rg_alns", ...)`
- wrapper: `run_rg_alns(...)`
- class: `RGRHOLNSFast`

Legacy entries `_create_algorithm(..., type="nr_rg_rho_lns", ...)` and
`run_nr_rg_rho_lns(...)` are retained as backward-compatible aliases.

## 5. Main-Method Dispatch Policy

The manuscript main method uses:

```text
standard_projected dispatch
```

Meaning:

1. Recoverability, quota, tardiness, and ALNS mechanisms are used to construct
   and improve a projected schedule.
2. Immediate real-time dispatch then extracts currently feasible operations
   from the selected projected schedule.
3. The dispatch stage does not forcibly override the projected schedule merely
   because a job is marked as mandatory rescue.

Do not describe the main method as `service_aware dispatch`.

`service_aware dispatch` should be treated as an optional extension or ablation
variant. If it is later used as the main method, the config, tests, and
manuscript algorithm description must all be changed together.

## 6. Event-Driven Algorithm Flow

At each scheduling event time `t`, RG-ALNS performs the following steps.

### Step 1: Event Trigger

The simulator calls the algorithm when the current schedule state changes, for
example when machines become idle.

Input:

```text
SLISP instance
current schedule state
```

Output:

```text
current feasible dispatch decisions:
(job_id, operation_id, machine_id, start_time)
```

### Step 2: Candidate Set Construction

Build a rolling-horizon candidate set:

```text
C(t) = jobs not completed and released within current_time + horizon
```

The current main horizon is:

```text
horizon = 300
```

### Step 3: Recoverability Diagnosis

For each service entity, compute structural recoverability information derived
from the theory section:

- remaining service requirement;
- optimistic recoverable service quantity;
- unavoidable shortfall lower bound;
- recoverability surplus;
- mandatory rescue jobs;
- minimum-work service-cover set;
- quota pressure.

Important code-level quantities:

- `maximum_recoverable_service_quantity`
- `unavoidable_shortfall_lower_bound`
- `mandatory_rescue_jobs`
- `_minimum_work_service_cover`
- `_entity_quota_pressure`
- `_quota_marginal_service_quantity`

### Step 4: RG Priority Scoring

Compute a recoverability-guided priority score for each candidate job.

The current score combines:

- tardiness urgency;
- service pressure;
- mandatory rescue signal;
- quota-aware marginal service contribution;
- processing burden;
- SPT-like short-job efficiency;
- service-efficiency / WSPT-like quantity-per-work signal.

Current main-method weights:

```text
a1 = 0.40  tardiness urgency
a2 = 0.15  service pressure
a3 = 0.10  mandatory rescue
a4 = 0.05  marginal recoverability
a5 = 0.10  processing burden
a6 = 0.50  SPT efficiency
a7 = 0.20  service efficiency
```

The RG score is used both directly and indirectly:

- directly by RG and RG-SPT construction orders;
- indirectly during SGS decoding as a priority shift;
- later by RG-based destroy and repair neighborhoods.

### Step 5: Multi-Start Projected Schedule Construction

Generate multiple projected schedules from different construction orders:

```text
EDD
SPT
ATC
RG
Cover
RG-SPT
```

Interpretation:

- `EDD`: effective due date order, using deadline minus transport delay.
- `SPT`: short processing time order.
- `ATC`: due-date/workload ratio style order.
- `RG`: descending recoverability-guided priority score.
- `Cover`: minimum-work service-cover jobs are promoted first.
- `RG-SPT`: hybrid order combining SPT, due-date urgency, service efficiency,
  RG risk, and marginal recoverability.

Each order is decoded by a release-aware schedule generation scheme. The
decoder still uses RG scores as a soft priority shift among ready operations.

### Step 6: Initial Candidate Evaluation and Selection

Each initial projected schedule is:

1. evaluated by `Z`;
2. lightly polished;
3. evaluated again by `Z`.

The best projected schedule becomes the initial incumbent. A WSF-aware secondary
choice is allowed only within the objective-consistent selection rule.

The manuscript should describe this as objective-consistent multi-start
initialization, not as a complete baseline rollout portfolio.

### Step 7: Adaptive Recoverability Intensity

Classify service entities by recoverability status:

```text
secured
stable-recoverable
fragile-recoverable
partially unrecoverable
```

The classification uses:

- remaining required quantity;
- maximum recoverable quantity;
- unavoidable shortfall lower bound;
- recoverability surplus.

The maximum entity-level intensity controls how much RG-biased neighborhoods
are emphasized in the ALNS loop.

Current interpretation:

- stable entities need little RG intervention;
- fragile-recoverable entities receive stronger RG guidance;
- partially unrecoverable entities receive limited RG effort because zero
  shortfall may already be structurally impossible.

### Step 8: Adaptive Large Neighborhood Search

The ALNS loop repeats until one of the following stopping rules is met:

```text
lns_iterations
max_total_repairs
max_no_improve
```

Current main settings:

```text
lns_iterations    = 20
max_total_repairs = 60
max_no_improve    = 15
destroy_fraction  = 0.4
```

#### Destroy Operators

RG-ALNS currently uses five destroy operators:

```text
random
worst_tardiness
low_rg_score
entity_shortfall
time_window
```

Descriptions:

- `random`: removes randomly selected jobs to provide diversification.
- `worst_tardiness`: removes jobs with the largest projected tardiness.
- `low_rg_score`: removes low-RG-score jobs, preserving jobs with high
  recoverability value.
- `entity_shortfall`: removes jobs belonging to entities with high unavoidable
  weighted shortfall risk.
- `time_window`: removes jobs whose projected starts fall in a local time
  window.

Theory-guided destroy operators:

- `low_rg_score`;
- `entity_shortfall`.

#### Repair Operators

RG-ALNS currently uses five repair operators:

```text
regret_k
random_order
edf
rg_priority
sequence_crossover
```

Descriptions:

- `regret_k`: reinserts jobs by regret-style insertion.
- `random_order`: reinserts jobs in random order for diversification.
- `edf`: reinserts jobs by earliest effective deadline.
- `rg_priority`: reinserts jobs by descending RG priority score.
- `sequence_crossover`: applies GA-inspired order crossover using structural
  donor orders, then decodes the sequence into a projected schedule.

Theory-guided repair operators:

- `rg_priority`;
- `sequence_crossover`, through its RG, Cover, quota-pressure, and
  service-efficiency donor orders.

#### Number of Neighborhood Combinations

With sequence crossover enabled, the ALNS loop has:

```text
5 destroy operators x 5 repair operators = 25 adaptive neighborhood combinations
```

If sequence crossover is disabled, it has:

```text
5 destroy operators x 4 repair operators = 20 adaptive neighborhood combinations
```

The current main method enables sequence crossover:

```text
use_sequence_crossover = true
sequence_crossover_trials = 4
```

### Step 9: Operator Probability Adaptation

The method uses two layers of adaptation.

First, recoverability context sets event-level prior probabilities. If RG
intensity is high, RG-specific destroy and repair moves become more likely.

Second, ALNS-style learned operator weights are updated from observed
performance. A selected destroy-repair pair receives a reward based on:

- whether the candidate was accepted;
- whether it strictly improved `Z`;
- whether it was accepted within tolerance because it improved WSF.

The learned weights are updated by an exponential moving-average rule.

Current main settings:

```text
use_operator_adaptation = true
operator_reaction_factor = 0.20
operator_min_weight = 0.05
operator_max_weight = 8.0
```

### Step 10: Acceptance Rule

A candidate projected schedule is accepted if:

```text
new_Z < best_Z
```

Additionally, with tolerance enabled, a candidate may be accepted if:

```text
new_Z <= best_Z * (1 + z_tolerance)
and
new_WSF < current_WSF
```

Current main setting:

```text
z_tolerance = 0.01
```

This rule preserves the original objective as the primary selection criterion
while allowing small objective-neutral moves that improve service shortfall.

### Step 11: Local Search

After ALNS, a lightweight local search stage attempts local schedule
improvements, including swap and reinsertion-style moves.

Current main setting:

```text
use_local_search = true
local_search_iters = 40
```

### Step 12: Bounded Exact Local Repair

RG-ALNS optionally performs a bounded exact local repair on a small active set.

This is not a global exact fallback. It is a local polishing component.

The active set is selected using:

- mandatory rescue jobs;
- minimum-work service-cover jobs;
- quota pressure;
- projected lateness;
- local schedule blockers and conflict windows;
- RG scores.

The selected subproblem is repaired with a small CP-SAT call under a strict
budget.

Current main settings:

```text
use_exact_local_repair = true
exact_local_job_limit = 8
exact_local_time_limit_s = 0.2
```

### Step 13: Immediate Dispatch Extraction

Finally, the selected projected schedule is converted into actual dispatch
decisions for the current event time.

The main method uses:

```text
dispatch_mode = standard_projected
```

The extraction step enforces simulator feasibility:

- only next operations of jobs may be dispatched;
- completed or ongoing operations are ignored;
- unreleased jobs are ignored;
- machines must be idle;
- each operation and each machine can be assigned at most once in the same
  decision cycle;
- the selected machine must be eligible for the operation.

## 7. What Belongs to the Main Method

The manuscript main method includes:

- rolling-horizon candidate construction;
- recoverability diagnosis;
- RG priority scoring;
- multi-start projected schedule construction;
- adaptive RG intensity;
- ALNS destroy-repair search;
- sequence-crossover repair;
- ALNS-style operator-weight learning;
- WSF-aware tolerance acceptance;
- local search;
- bounded recoverability-guided exact local repair;
- standard projected dispatch extraction.

## 8. What Does Not Belong to the Main Method

The following mechanisms should not be described as part of the manuscript main
algorithm unless the code, config, tests, and experiments are deliberately
changed:

- `service_aware dispatch`;
- exact-small global oracle mode;
- complete-run rollout portfolio selection;
- complete-run baseline substitution by EDD, SPT, WSPT, or ATC;
- intensified sequence evolution;
- quota-rescue rollout;
- VNS-polish rollout.

These may be used only as diagnostics, ablations, or optional variants.

## 9. Theory-to-Algorithm Mapping

The recoverability theory maps into RG-ALNS as follows.

| Theory concept | Algorithm use |
|---|---|
| Optimistic recoverable quantity | Entity recoverability diagnosis and RG intensity |
| Unavoidable shortfall lower bound | `entity_shortfall` destroy and entity risk classification |
| Mandatory rescue jobs | RG score, exact local repair active-set selection |
| Minimum-work service cover | Cover construction, sequence-crossover donor order, exact repair selection |
| Quota-aware marginal service contribution | RG score, service-efficiency ordering |
| Recoverability surplus | Stable/fragile/unrecoverable entity classification |

This mapping is the main algorithmic novelty. The manuscript should emphasize
this mapping rather than presenting the method as a generic ALNS.

## 10. Suggested Manuscript Wording

Use this compact description in the algorithm section:

```text
RG-ALNS is a recoverability-guided adaptive large neighborhood search algorithm
operating in an event-driven rolling-horizon manner. At each decision epoch, it
diagnoses entity-level service recoverability, converts the resulting structural
indicators into job priorities and neighborhood-selection probabilities,
constructs multiple projected schedules, improves the selected incumbent with
adaptive destroy-repair neighborhoods, and dispatches currently feasible
operations according to the final projected schedule.
```

Chinese version:

```text
RG-ALNS 是一种以事件驱动滚动时域方式运行的可恢复性引导自适应大邻域搜索算法。
在每个决策时刻，算法诊断服务实体层面的可恢复性状态，将结构性指标转化为
工件优先级和邻域选择概率，构造多个投影排程，通过自适应破坏-修复邻域改进
当前最优投影排程，并最终按照被选中的投影排程提取当前可执行操作。
```

## 11. Naming Migration Notes

Recommended final naming:

- manuscript method: `RG-ALNS`;
- table and figure label: `RG-ALNS`;
- algorithm caption: `Recoverability-Guided Adaptive Large Neighborhood Search`;
- config label: `RG-ALNS`.

Legacy names to replace in final manuscript-facing materials:

- `NR-RG-RHO-LNS`;
- `SRG-RHO-LNS`;
- `RG-RHO-LNS-Fast`;
- `InitEnhanced-v1.3`.

Code function and class names can be migrated later. Until then, document that
`run_nr_rg_rho_lns()` and `RGRHOLNSFast` implement the paper method now named
RG-ALNS.

## 12. Current Evidence and Caution

Existing results suggest:

- 15-job exact comparison: RG-ALNS is best among heuristic baselines.
- 40-job comparison: RG-ALNS is best or tied-best on all tested instances.
- 80-job comparison: RG-ALNS currently ties EDD on mean `Z` and is slightly
  worse than VNS-Fast, with high runtime.
- `final_v13_validation` is not yet conclusive because most runs failed and the
  available OK subset is limited to medium pressure.

Therefore, the manuscript should not yet claim universal dominance. The safe
current claim is:

```text
RG-ALNS provides a theory-guided algorithmic framework whose benefit is
supported on small and medium diagnostic instances, while final large-scale
performance claims require complete validation and ablation results.
```

## 13. Required Ablations

To support the SCI algorithm-contribution claim, the following ablations are
recommended:

- Full RG-ALNS;
- without RG score;
- without `entity_shortfall` destroy;
- without `rg_priority` repair;
- without adaptive RG intensity;
- without sequence crossover;
- without bounded exact local repair;
- generic ALNS with only random, time-window, EDF, and regret repair.

The purpose is to show that the recoverability-guided modules contribute beyond
a generic ALNS baseline.
