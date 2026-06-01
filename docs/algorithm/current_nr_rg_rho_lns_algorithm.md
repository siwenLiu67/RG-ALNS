# Current NR-RG-RHO-LNS Algorithm Record

Last updated: 2026-05-31

This document records the current implementation of the proposed method for
reproducible experiments. The source of truth is:

- `sl_isp_rg_rho_lns/src/algorithms/rg_rho_lns_fast.py`
- `sl_isp_rg_rho_lns/src/experiments/run_pilot_benchmark.py`
- `sl_isp_rg_rho_lns/configs/final_v13_validation.yaml`

## 1. Method Overview

The current proposed method is `NR-RG-RHO-LNS`, implemented by
`run_nr_rg_rho_lns()` and `RGRHOLNSFast`.

The method is an event-driven rolling-horizon scheduler. At each simulator event
time, it decides operations for currently idle machines. Its core design is:

1. Construct a projected schedule within a rolling horizon.
2. Score jobs using recoverability-guided RG signals.
3. Build diverse initial schedules from EDD, SPT, ATC, RG, cover, and RG-SPT
   structures.
4. Improve the projected schedule by adaptive LNS, sequence crossover, local
   search, and bounded exact local repair.
5. Extract only simulator-feasible immediate dispatch decisions from the
   projected schedule.

Baseline dispatching rules such as EDD, SPT, WSPT, and ATC are used as
initialization structures or comparison algorithms. They are not used as
complete-run substitutes for the proposed method in the paper main setting.

The objective minimized is:

```text
Z = alpha * total_tardiness + beta * weighted_service_shortfall
```

For the final validation config, `alpha = 1.0` and `beta = 1.0`.

## 2. Main Event-Driven Flow

At each decision event, `RGRHOLNSFast.__call__()` runs the following logic.

```text
Input: instance, current schedule state
Output: dispatch decisions (job_id, op_id, machine_id, start_time)

1. If this event time was already processed, return no decisions.

2. If exact-small oracle mode is enabled for small instances:
      solve the full small instance by CP-SAT;
      replay the exact plan.
   This mode is diagnostic and is not the paper main method.

3. Build the rolling-horizon candidate job set:
      jobs not completed and released within current_time + horizon.

4. Compute RG scores for candidate jobs.

5. Generate the projected schedule:
      if use_multi_start_init:
          build candidate pool from EDD, SPT, ATC, RG, Cover, RG-SPT;
          polish each candidate;
          choose the best Z, with a secondary WSF-aware tie option.
      else:
          construct a single greedy projected schedule.

6. If adaptive RG is enabled:
      classify entity risk;
      scale RG destroy/repair probabilities by risk intensity.

7. If LNS is enabled:
      repeat until lns_iterations, max_total_repairs, or max_no_improve:
          choose a destroy operator;
          remove selected jobs;
          choose a repair operator;
          repair the schedule;
          accept if Z improves, or if within tolerance and WSF improves;
          update adaptive operator weights.

8. If local search is enabled:
      try job swap and reinsertion moves.

9. If exact local repair is enabled:
      select a small repair subset and solve a bounded CP-SAT local repair.

10. Extract feasible immediate decisions:
      only ready next operations;
      only idle machines;
      no duplicate operation or machine in the same dispatch cycle;
      use quota marginal service and tardiness opportunity in dispatch ranking.
```

## 3. Diagnostic Rollout Portfolio

The previous no-regret rollout portfolio is retained only as a diagnostic or
ablation facility. It is disabled in the paper main method because complete
baseline rollouts such as EDD, SPT, WSPT, and ATC should not substitute for the
proposed ALNS-based method's final result.

When `use_rollout_portfolio = true` in a diagnostic run, the initial event can
evaluate a portfolio of complete rollout candidates. Each candidate is simulated
to completion under the same objective, and the best realized `Z` is selected.

Base candidates always included:

```text
EDD
SPT
WSPT
ATC
```

Conditional candidates:

```text
NR-RG-RHO-LNS-quota-rescue
  Enabled if:
      use_quota_rescue_rollout = true
      num_jobs >= quota_rescue_job_threshold

NR-RG-RHO-LNS-vns-polish
  Enabled if:
      use_vns_polish_rollout = true
      vns_polish_job_threshold <= num_jobs <= vns_polish_job_limit

Inner NR family
  Enabled if:
      rollout_portfolio_include_nr = true
      num_jobs <= rollout_inner_nr_job_limit

  Includes:
      NR-RG-RHO-LNS
      NR-RG-RHO-LNS-quota-only
      NR-RG-RHO-LNS-sequence-commit
      NR-RG-RHO-LNS-no-exact-local

Sequence evolution
  Enabled inside the inner NR family if:
      use_sequence_evolution_rollout = true
      num_jobs <= sequence_evolution_job_limit

Intensified sequence evolution
  Disabled in final validation.
```

Current intent:

- Final validation disables complete-run rollout portfolio selection.
- EDD, SPT, WSPT, ATC, cover, and RG-derived orders remain valid as multi-start
  initialization structures inside the ALNS path.
- Rollout portfolio diagnostics may still be run separately to understand why a
  simple dispatching rule is competitive on a particular instance, but those
  results should not be reported as the proposed method.

## 4. Important Internal Components

### 4.1 RG Scoring

`_compute_rg_scores()` evaluates candidate jobs using a weighted combination of:

```text
a1: tardiness urgency
a2: service pressure
a3: mandatory rescue signal
a4: processing efficiency
a5: slack/release related signal
a6: quota-aware WSPT/service-efficiency signal
a7: additional service/cover signal
```

Current main-method RG weights:

```text
a1 = 0.40
a2 = 0.15
a3 = 0.10
a4 = 0.05
a5 = 0.10
a6 = 0.50
a7 = 0.20
```

### 4.2 Quota-Aware Marginal Service

`_quota_marginal_service_quantity()` estimates how much a job truly contributes
to reducing service shortfall. It prevents the algorithm from over-protecting
jobs that are on-time but redundant with respect to an entity's quota.

### 4.3 Tardiness Opportunity Gain

`_tardiness_opportunity_gain()` estimates how much additional tardiness is caused
if a ready operation waits for another operation duration. It helps identify
jobs that may no longer be on time but are still worth processing early to
reduce total tardiness.

### 4.4 Sequence Crossover Repair

`_repair_by_sequence_crossover()` is a GA-inspired LNS repair operator. It:

1. extracts the current schedule's job order;
2. builds donor orders from EDD, SPT, WSPT-like, RG, Cover, and service-efficiency
   structures;
3. applies order crossover and mutation;
4. decodes the resulting job order with SGS-style greedy construction;
5. accepts it only if it improves the projected objective.

This captures GA's useful global sequence recombination without using GA as an
external fallback.

### 4.5 Quota-Rescue Rollout

`_QuotaRescueRollout` starts from due-date and ATC-like base orders and applies
`_quota_rescue_pull_forward()`. It attempts to pull late quota-reducing jobs
ahead of redundant on-time blockers.

### 4.6 VNS-Polish Rollout

`_VNSPolishRollout` is a dynamic rollout candidate. At each event, it:

1. builds projected schedules from EDD, ATC, and SPT base orders;
2. applies a lightweight VNS-style polish:
   - random destroy/repair;
   - pairwise swap;
   - single-job reinsertion;
3. extracts immediate feasible dispatch decisions.

It is intended only for a bounded job-size band, currently 80-100 jobs.

## 5. Main Algorithm Pseudocode

```text
Algorithm NR-RG-RHO-LNS(instance, state)

Parameters:
    horizon H
    LNS iteration limit I
    destroy fraction gamma
    RG weights a1..a7
    local repair budget B_exact
    no-regret portfolio switches and thresholds

At each event time t:

    if t has already been processed:
        return empty decision set

    if stored rollout plan exists:
        return feasible_replay(stored rollout plan, state)

    C <- unreleased/completed filtered jobs with release_time <= t + H
    if C is empty:
        return empty decision set

    scores <- RG_scores(C, state, a1..a7)

    if multi_start_initialization:
        pool <- {
            greedy_schedule(EDD order),
            greedy_schedule(SPT order),
            greedy_schedule(ATC order),
            greedy_schedule(RG order),
            greedy_schedule(Cover order),
            greedy_schedule(RG-SPT order)
        }
        polish each schedule in pool
        S <- best schedule by Z, with WSF-aware tie option
    else:
        S <- greedy_schedule(EDD or RG order)

    classify entity recoverability risk
    adapt RG destroy/repair probabilities

    best_Z <- Z(S)
    no_improve <- 0
    repairs <- 0

    while repairs < max_total_repairs
          and repairs < I
          and no_improve < max_no_improve:

        D <- select destroy operator
        R <- select repair operator

        J_removed <- D(S)
        S_trial <- remove J_removed from S
        S_trial <- R(S_trial, J_removed)

        Z_trial <- Z(S_trial)

        if Z_trial < best_Z:
            S <- S_trial
            best_Z <- Z_trial
            no_improve <- 0
            update operator reward positively
        else if Z_trial within tolerance and WSF improves:
            S <- S_trial
            best_Z <- Z_trial
            no_improve <- 0
            update operator reward mildly
        else:
            no_improve <- no_improve + 1
            update operator reward negatively

        repairs <- repairs + 1

    S <- local_search(S)

    if exact_local_repair_enabled:
        R_exact <- select bounded repair subset
        S <- CP-SAT local repair(S, R_exact, time_limit)

    return extract_feasible_immediate_decisions(
        S,
        state,
        quota_marginal_service = true,
        tardiness_opportunity = true
    )
```

## 6. Final Validation Experiment Parameters

Config file:

```text
sl_isp_rg_rho_lns/configs/final_v13_validation.yaml
```

### 6.1 Pilot Parameters

```yaml
pilot:
  seed: 42
  experiment_mode: normal
  num_seeds: 15
```

### 6.2 Instance Groups

All groups use:

```yaml
weight_pattern: mild
arrival_intensity: medium
ops_per_job: [2, 4]
proc_time_range: [10, 50]
transport_delay_range: [10, 40]
eligible_machines_range: [2, 3]
alpha: 1.0
beta: 1.0
```

Pressure groups:

```yaml
medium:
  rho_range: [0.75, 0.85]
  deadline_tightness: 1.0
  effective_due_spread: 0.50

high:
  rho_range: [0.85, 0.95]
  deadline_tightness: 0.5
  effective_due_spread: 0.60

very_high:
  rho_range: [0.95, 0.99]
  deadline_tightness: 0.25
  effective_due_spread: 0.70
```

Size combinations per pressure level:

```text
Jobs:      40, 80, 120, 160
Machines: 5, 10, 15
Entities:
  40 jobs  -> 3 entities
  80 jobs  -> 5 entities
  120 jobs -> 8 entities
  160 jobs -> 10 entities

Machine eligibility:
  5 machines:  [2, 3]
  10 machines: [3, 6]
  15 machines: [4, 8]
```

The full design is:

```text
3 pressure levels x 12 size combinations x 15 seeds
```

### 6.3 Compared Algorithms

```text
EDD
SPT
WSPT
ATC
Service-Weighted
Shortfall-Greedy
Plain-RHO-Fast
RHO-LNS-Fast
Adaptive-RG-v1.2
ILS-Fast
VNS-Fast
TS-Fast
NR-RG-RHO-LNS
```

### 6.4 Baseline Metaheuristic Settings

```yaml
ils_fast:
  horizon: 300
  max_iter: 20

vns_fast:
  horizon: 300
  max_iter: 20

ts_fast:
  horizon: 300
  max_iter: 20
  tabu_tenure: 7
```

### 6.5 Proposed Method Settings

```yaml
nr_rg_rho_lns:
  type: nr_rg_rho_lns
  label: NR-RG-RHO-LNS
  horizon: 300
  lns_iterations: 20
  exact_local_job_limit: 8
  exact_local_time_limit_s: 0.2

  use_rollout_portfolio: false
  rollout_inner_nr_job_limit: 30

  use_quota_rescue_rollout: true
  quota_rescue_job_threshold: 31
  quota_rescue_max_moves: 12

  use_vns_polish_rollout: true
  vns_polish_job_threshold: 80
  vns_polish_job_limit: 100
  vns_polish_max_iter: 4

  use_sequence_evolution_rollout: true
  sequence_evolution_job_limit: 30
  use_intensified_sequence_evolution: false
```

Additional defaults from `run_nr_rg_rho_lns()`:

```text
destroy_fraction = 0.4
local_search_iters = 40
rg weights = (0.40, 0.15, 0.10, 0.05, 0.10, 0.50, 0.20)
rg_repair_prob = 0.40
rg_destroy_prob = 0.25
max_total_repairs = 60
max_no_improve = 15
use_multi_start_init = true
use_operator_adaptation = true
use_tabu_memory = true
tabu_tenure = 5
z_tolerance = 0.01
use_sequence_crossover = true
sequence_crossover_trials = 4
use_tardiness_opportunity_dispatch = true
use_exact_local_repair = true
use_exact_small_portfolio = false
use_rollout_portfolio = false
use_due_dispatch_guard = false
rollout_portfolio_include_nr = true
```

## 7. Reproduction Commands

From repository root:

```bash
cd /Volumes/siwen_硬盘/论文/0326/paper0520/sl_isp_rg_rho_lns
python3 -m pytest
python3 -m src.experiments.run_pilot_benchmark configs/final_v13_validation.yaml
```

After final experiment outputs are available, update paper result tables:

```bash
cd /Volumes/siwen_硬盘/论文/0326/paper0520
python3 paper/tools/autofill_results.py
```

To generate rollout portfolio diagnostics for a portfolio CSV:

```bash
cd /Volumes/siwen_硬盘/论文/0326/paper0520/sl_isp_rg_rho_lns
python3 -m src.analysis.rollout_portfolio_diagnostics \
  outputs/final_v13_validation/rollout_portfolio_raw.csv \
  outputs/final_v13_validation/rollout_candidate_diagnostics.csv
```

## 8. Current Implementation Notes

1. `use_intensified_sequence_evolution` is disabled in final validation because
   previous tests showed high runtime without objective improvement.
2. `VNS-polish` is enabled only for `80 <= num_jobs <= 100` to cover the
   observed 80-job weakness while avoiding uncontrolled runtime growth at 120
   and 160 jobs.
3. `quota-rescue` is enabled for `num_jobs >= 31`, but the no-regret portfolio
   selects it only if its full simulated objective is best.
4. Sequence evolution remains available for small instances where complete
   rollout simulation is affordable.
5. The main method does not use exact CP-SAT as a full-instance fallback. Exact
   optimization is limited to bounded local repair.
6. The no-regret portfolio records candidate-level diagnostics:
   `candidate`, `Z`, `TT`, `WSF`, `runtime_s`, and `selected`.
