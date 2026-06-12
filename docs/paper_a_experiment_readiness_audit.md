# Paper A Experiment Readiness Audit

Date: 2026-06-12

Branch: `codex/paper-a-experiment-readiness-audit`

Base branch: `codex/rg-ralns-performance-tuning`

Base commits:

```text
a0d55fd docs: record RG-RALNS tuning push status
a16bd9c docs: record RG-RALNS tuning commit metadata
9161f39 feat: tune RG-RALNS service-safe fallback and performance diagnostics
```

## 1. Goal

Conduct a full experiment-readiness audit for Paper A. The purpose is to determine whether the current codebase is ready to support the full experimental section of the paper, and if not, to identify the exact missing code functions, experiment runners, output files, validation checks, algorithm weaknesses, and computational-budget-aware next steps.

This is an audit and roadmap task. It does not add new algorithms, does not change the online visibility protocol, does not change the normalized objective, and does not run final-scale experiments.

## 2. Current Code Architecture Summary

### 2.1 Main Algorithm Module

Primary file:

```text
sl_isp_rg_rho_lns/src/algorithms/rg_ralns.py
```

Implemented Paper A algorithm:

```text
Recoverability-Guided Reactive ALNS (RG-RALNS)
```

Key implemented classes and functions:

| Component | Status | Notes |
|---|---|---|
| `RGRALNSConfig` | ready | Central parameters: `H_A`, `N_A`, `acceptance_mode`, `bottleneck_trigger_mode`, rescue fallback, zero-WSF guard, adaptive destroy size, TT polish cap, debug trace. |
| `compute_recoverability_diagnostics` | ready | Computes secured quantity, remaining requirement, visible recoverable quantity, future aggregate buffer, service cover, mandatory rescue jobs, and entity classes. |
| trigger functions | ready | Separate deterministic functions for shortfall, mandatory-ready, high-risk arrival, bottleneck competition, and cover violation. |
| `lightweight_rg_dispatch` | ready | Deterministic service-rank dispatch fallback/ablation. |
| `construct_affected_set` | ready | Builds visible unfinished affected set and applies `H_A` cap. |
| Local RG-ALNS skeleton | ready for small/medium validation | Implements initial local order, destroy/repair operators, acceptance, operator reward logging, and local decoding. |
| `RescueFallbackDispatch` | ready but partial effect | Prioritizes mandatory, cover, high-risk, EDD/SPT candidates when ALNS extraction returns no executable operation. |
| event trace and operator/fallback stats | ready | Supports seed-specific diagnostics and mechanism analysis. |

Important limitation:

```text
The local decoder/extraction still sometimes produces no current executable operation
under shortfall risk, especially in seed 2.
```

### 2.2 Online Visibility Enforcement

Primary files:

```text
sl_isp_rg_rho_lns/src/core/online.py
sl_isp_rg_rho_lns/src/core/simulator.py
sl_isp_rg_rho_lns/src/experiments/paper_a_online_protocol.py
```

The simulator owns the full `SLISPInstance` for event generation and final objective evaluation. Algorithms in online mode receive only `OnlineProblemView`.

The online view exposes:

```text
visible jobs only
service entities
machines
alpha/beta
entity_future_quantity
metadata with visible_job_ids
```

It does not expose future unreleased jobs as job objects. The future information allowed to online algorithms is the entity-level aggregate quantity buffer:

```text
entity_future_quantity
```

Current tests verify:

```text
future job details are hidden before arrival
Q_future changes only on arrival
main-table algorithms receive online views
dispatch baselines cannot select unreleased jobs
Online-Legacy-ALNS uses visible backlog only
```

### 2.3 Current-Time Execution Enforcement

Primary file:

```text
sl_isp_rg_rho_lns/src/experiments/paper_a_online_protocol.py
```

The `CurrentTimeCommitWrapper` wraps all Paper A algorithms and calls:

```text
validate_current_decisions(...)
```

This enforces:

```text
start_time == current event time
job is visible
job has arrived
operation is next operation
operation is not completed or ongoing
machine is idle
machine is eligible
predecessors are complete
no duplicate operation or machine assignment in one dispatch cycle
```

The simulator also validates decisions before mutating state. This gives two layers of protection: benchmark-level validation and simulator-level validation.

### 2.4 Normalized Objective Evaluation

Primary file:

```text
sl_isp_rg_rho_lns/src/experiments/paper_a_online_protocol.py
```

Implemented formulas:

```text
Theta_I = sum_j max(1, d_g(j) - tau_g(j) - r_j)
Omega_I = sum_r w_r * Q_min,r
TT_hat  = TT / Theta_I
WSF_hat = WSF / Omega_I
Z_N     = alpha_0 * TT_hat + beta_0 * WSF_hat
```

Equivalent calibrated raw form:

```text
Z_N = alpha_I * TT + beta_I * WSF
alpha_I = alpha_0 / Theta_I
beta_I  = beta_0 / Omega_I
```

The code keeps the existing deterministic service requirement convention:

```text
Q_min,r = max(1.0, rho_r * Q_r)
```

Current output includes:

```text
Z_original
Z_N
normalized_Z
TT
WSF
TT_hat
WSF_hat
ZSR
Theta_I
Omega_I
alpha_0
beta_0
alpha_I
beta_I
```

### 2.5 Paper A Benchmark Runner

Primary files:

```text
scripts/run_paper_a_online_benchmark.py
configs/paper_a_online.yaml
sl_isp_rg_rho_lns/src/experiments/paper_a_online_protocol.py
```

Current runner supports:

```text
--config
--seeds
--output
--beta-sensitivity
--objective-beta
--rg-debug-trace
```

The default Paper A config currently contains one small dynamic instance family:

```text
smoke_dynamic_20
20 jobs
5 machines
3 entities
arrival_intensity = medium
rho_range = [0.65, 0.80]
```

Default main-online algorithms:

```text
EDD
SPT
WSPT
ATC
SWD
SFG
Lightweight RG Dispatch
Online-Legacy-ALNS
RG-RALNS
```

Offline/oracle reference:

```text
Offline-Legacy-ALNS
```

Optional online metaheuristic specs exist in the registry:

```text
Online-ILS
Online-VNS
Online-TS
Online-SA
Online-GA
```

However, they are not part of the current default config and have not been validated as Paper A main-table algorithms under the current protocol.

### 2.6 Current Output Files

The runner currently writes:

| Output file | Status | Main use |
|---|---|---|
| `results_summary.csv` | ready | Main aggregate comparison. |
| `per_instance_results.csv` | ready | Per-instance metrics and raw schedule outcomes. |
| `mechanism_stats.csv` | ready | Trigger, affected-set, fallback, event-count, and runtime mechanism stats. |
| `trigger_reason_counts.csv` | ready | Trigger reason frequency. |
| `objective_calibration.csv` | ready | `Theta_I`, `Omega_I`, `alpha_I`, `beta_I`. |
| `beta_sensitivity_summary.csv` | ready | Recomputed normalized objective across beta values. |
| `config_used.yaml` | ready | Reproducibility. |
| `rg_ralns_event_trace_seed2.csv` | partially ready | Useful for debug trace, but currently named seed2-specific even when multiple seeds are used. |
| `operator_stats.csv` | ready | Operator selected/accepted/reward/weight stats. |
| `fallback_stats.csv` | ready | Rescue fallback and ordinary fallback diagnostics. |
| `tuning_comparison.csv` | partially ready | Contains useful tuning fields for one config; not a full multi-config tuning runner. |

### 2.7 Current Test Coverage

Relevant tests:

```text
sl_isp_rg_rho_lns/tests/test_rg_ralns.py
sl_isp_rg_rho_lns/tests/test_paper_a_online_benchmark_protocol.py
sl_isp_rg_rho_lns/tests/test_paper_a_online_baselines.py
sl_isp_rg_rho_lns/tests/test_paper_a_current_time_execution.py
sl_isp_rg_rho_lns/tests/test_paper_a_online_visibility.py
sl_isp_rg_rho_lns/tests/test_online_simulator.py
sl_isp_rg_rho_lns/tests/test_simulator.py
sl_isp_rg_rho_lns/tests/test_recoverability.py
```

Current coverage is strong for:

```text
online visibility
current-time execution
future quantity buffer
RG-RALNS diagnostics
trigger determinism
affected-set cap
fallback decision validity
normalized objective outputs
main-online vs offline/oracle separation
```

Current coverage is weaker for:

```text
ablation variants
multi-scale benchmark configs
medium/large instance smoke tests
seed 2 rescue/fallback regression target
optional online metaheuristics
automated paper table generation
statistical significance / confidence interval reporting
```

## 3. Current Implemented Experiment Capabilities

Ready now:

1. Unified online event-driven protocol for main algorithms.
2. Online visibility adapter through `OnlineProblemView`.
3. Current-time commit validation for all Paper A algorithms.
4. Main minimum fair baseline set.
5. Offline/oracle legacy separation.
6. Normalized objective calibration and beta sensitivity recomputation.
7. Mechanism statistics proving event-triggered local behavior.
8. Seed-level and event-level RG-RALNS debug trace.
9. Small benchmark execution with reproducible config and seed list.
10. Documentation logs for protocol, normalized objective, and performance tuning.

Partially ready:

1. Medium-scale benchmark: generator supports it, but Paper A config does not yet define a medium experiment matrix.
2. Ablation study: some parameters make variants possible, but there is no explicit ablation runner/config matrix.
3. Scalability study: generator supports jobs/machines/entities, but runner does not yet provide a dedicated scale sweep.
4. Robustness study: seeds, beta, rho range, and arrival intensity are supported, but no robustness config matrix or summary script exists.
5. Optional online metaheuristics: code registry exists, but they are not validated for Paper A main table.

Not ready:

1. Final experimental section tables are not yet reproducibly generated from one command.
2. There is no paper-table post-processing script dedicated to the new Paper A online outputs.
3. There is no statistical reporting layer.
4. Seed 2 rescue/fallback weakness remains unresolved.
5. No final-scale benchmark plan has been executed or validated.

## 4. Required Capabilities for the Paper Experimental Section

### 4.1 Main Comparison

Minimum required algorithms:

```text
EDD
SPT
WSPT
ATC
SWD
SFG
Lightweight RG Dispatch
Online-Legacy-ALNS
RG-RALNS
```

Status:

```text
ready for small/expanded-small experiments
partially ready for final experiments
```

The current runner and config can run this set. Before final experiments, RG-RALNS needs seed 2 stabilization and the instance matrix must be expanded beyond `smoke_dynamic_20`.

Optional later algorithms:

```text
Online-ILS
Online-VNS
Online-TS
Online-SA
Online-GA
```

Recommendation:

```text
Not required for the first SCI main table if the paper clearly positions the
comparison around dispatching rules, lightweight RG, and legacy online ALNS.
They can be left for robustness/appendix after the main protocol is stable.
```

Required metrics:

```text
Z_N
TT
WSF
TT_hat
WSF_hat
ZSR
runtime
```

Status:

```text
ready
```

### 4.2 Beta Sensitivity

Required beta values:

```text
beta_0 in {1, 5, 10, 20, 50, 100}
```

Purpose:

```text
show that RG-RALNS becomes more valuable as SLA penalty intensity increases
```

Status:

```text
ready for current algorithm set
```

The runner supports `--beta-sensitivity` and writes `beta_sensitivity_summary.csv`.

### 4.3 Ablation Study

Candidate variants:

| Variant | Currently implementable? | Required code/config change |
|---|---|---|
| Full RG-RALNS | yes | none |
| Lightweight RG Dispatch | yes | already present |
| without recoverability trigger | not cleanly | need config flag to disable risk trigger and always use dispatch or always local search. |
| without affected-set cap | partially | could set very large `H_A`, but should add explicit ablation label and safety cap. |
| without service-safe fallback | yes | set `rescue_fallback_enabled=false`; needs ablation config matrix. |
| without service-safe acceptance | partially | set `acceptance_mode=service_first` or `protect_zero_wsf=false`; needs clear mapping to paper ablation. |
| without adaptive destroy size | yes | set `adaptive_destroy_size=false`; needs config matrix. |
| without TT polish | yes | current default `tt_polish_max_moves=0`; since TT polish was harmful, it should not be framed as core contribution. |

Status:

```text
partially ready
```

Missing:

```text
scripts/run_paper_a_ablation.py or config-driven ablation matrix support
ablation_variant field in outputs
ablation_summary.csv
tests verifying variant labels and config overrides
```

### 4.4 Mechanism Analysis

Required outputs:

```text
trigger_count
trigger_ratio
trigger_reason_counts
avg_A_size
max_A_size
alns_runtime_total
dispatch_fallback_count
rescue_fallback_success_count
operator_stats
fallback_stats
```

Status:

```text
ready for RG-RALNS mechanism analysis
```

Purpose supported:

```text
prove RG-RALNS is risk-triggered local ALNS rather than every-event global ALNS
```

Current caveat:

```text
event trace file name is seed2-specific. For final experiments it should be renamed
or supplemented with a general event_trace.csv when debug tracing is enabled.
```

### 4.5 Scalability Analysis

Required scale dimensions:

```text
number of jobs
number of machines
number of entities/zones
arrival density or service pressure level
```

Generator support:

| Dimension | Supported? | Evidence |
|---|---|---|
| jobs | yes | `InstanceConfig.num_jobs` supports int/range; predefined configs from 10 to 100 jobs. |
| machines | yes | `InstanceConfig.num_machines`. |
| entities/zones | yes | `InstanceConfig.num_entities`. |
| arrival density | yes | `build_dynamic_scenario(..., arrival_intensity)` with static/low/medium/high. |
| service pressure | yes | `rho_range`, `deadline_tightness`, due spread. |

Runner support:

```text
partially ready
```

The runner can execute any instance entries listed in YAML, but there is no dedicated scalability config or summarizer yet.

Missing:

```text
configs/paper_a_scalability.yaml
scale_group / jobs / machines / entities fields highlighted in summary
scalability_summary.csv or table-generation script
runtime-budget guard for slow baselines
```

### 4.6 Robustness Analysis

Required dimensions:

```text
multiple random seeds
different beta_0 values
different service ratio rho
different dynamic arrival settings
```

Status:

| Dimension | Supported now? | Missing |
|---|---|---|
| multiple seeds | yes | none |
| beta_0 values | yes | none for sensitivity summary |
| rho/service pressure | partially | YAML supports `rho_range`, but no robustness matrix runner. |
| arrival settings | partially | YAML supports `arrival_intensity`, but no robustness matrix runner. |

Missing:

```text
configs/paper_a_robustness.yaml
robustness_factor field in outputs
robustness_summary.csv
statistical confidence intervals
```

## 5. Paper Table Readiness

| Paper table | Readiness | Required output files | Currently available fields | Missing fields / code |
|---|---|---|---|---|
| Table 1: Main online comparison under beta_0 = 20 or 50 | Partially ready | `results_summary.csv`, `per_instance_results.csv`, `objective_calibration.csv` | `Z_N`, `TT`, `WSF`, `TT_hat`, `WSF_hat`, `ZSR`, `runtime`, calibration constants | Need final instance matrix, seed count, statistical intervals, seed 2 stabilization. |
| Table 2: Beta sensitivity summary | Ready for small experiments; partially ready for final | `beta_sensitivity_summary.csv` | beta-specific `mean_Z_N`, `TT`, `WSF`, `TT_hat`, `WSF_hat`, `ZSR`, rank, RG gaps | Need final seed/instance count; maybe include confidence intervals. |
| Table 3: Ablation study | Partially ready | currently can reuse `results_summary.csv` and `tuning_comparison.csv` | Some variants can be configured manually | Need ablation runner/config matrix, `ablation_variant`, `ablation_summary.csv`. |
| Table 4: Mechanism statistics | Ready for current RG-RALNS; partially ready for paper | `mechanism_stats.csv`, `trigger_reason_counts.csv`, `operator_stats.csv`, `fallback_stats.csv` | trigger stats, A-size, ALNS runtime, fallback counts, operator stats | Need final-scale mechanism run; rename/generalize event trace output. |
| Table 5: Scalability / runtime analysis | Not ready | none dedicated | basic runtime in `results_summary.csv` | Need scalability config, scale metadata in summaries, runtime budget plan. |
| Table 6: Robustness across seeds/service pressure | Not ready | none dedicated | per-seed rows and beta sensitivity exist | Need robustness config matrix and grouped summaries by rho/arrival/deadline pressure. |

## 6. Main Algorithm Readiness Assessment

Current small benchmark, beta_0 = 20:

| Algorithm | Z_N | TT | WSF | ZSR | runtime |
|---|---:|---:|---:|---:|---:|
| RG-RALNS | 0.1084 | 87.67 | 0.283 | 0.889 | 0.0442 |
| Online-Legacy-ALNS | 0.1197 | 48.67 | 0.443 | 0.778 | 2.0444 |
| Lightweight RG Dispatch | 0.1261 | 119.67 | 0.283 | 0.889 | 0.0059 |
| EDD | 0.8802 | 67.00 | 4.003 | 0.667 | 0.0013 |

Current small benchmark, beta_0 = 50:

| Algorithm | Z_N | TT | WSF | ZSR | runtime |
|---|---:|---:|---:|---:|---:|
| RG-RALNS | 0.1979 | 87.67 | 0.283 | 0.889 | 0.0438 |
| Online-Legacy-ALNS | 0.2596 | 48.67 | 0.443 | 0.778 | 2.0585 |
| Lightweight RG Dispatch | 0.2156 | 119.67 | 0.283 | 0.889 | 0.0061 |
| EDD | 2.1443 | 67.00 | 4.003 | 0.667 | 0.0014 |

Answers:

1. Is RG-RALNS currently better than Online-Legacy-ALNS under beta_0 = 20?

```text
Yes on the current small three-seed benchmark by Z_N, but the margin is modest.
```

2. Is RG-RALNS clearly better under beta_0 = 50 and 100?

```text
Yes in the current small benchmark. The normalized objective advantage grows as beta_0 increases.
```

3. Is runtime acceptable?

```text
Yes. RG-RALNS is around 0.04 seconds per small instance and far below Online-Legacy-ALNS at about 2 seconds per small instance.
```

4. Is WSF/ZSR stable enough?

```text
Not yet fully. Mean WSF/ZSR are competitive, but seed 2 remains weak.
```

5. Does seed 2 failure block medium-scale experiments?

```text
It does not block a diagnostic expanded-small benchmark, but it should block final-scale experiments and final paper claims.
```

6. What exact code mechanism should be fixed before larger experiments?

Priority mechanisms:

```text
local decode and extraction of current-time executable rescue operations
readiness of mandatory/cover jobs inside A(t)
fallback behavior when no rescue candidate is currently executable
shortfall-trigger states with empty affected set
event trace generalization for all seeds
```

## 7. Seed 2 Issue

Known seed 2 result:

```text
WSF = 0.85
ZSR = 0.667
dispatch_fallback_count = 41
shortfall trigger count = 41
```

Diagnostic conclusion:

```text
The failure is not simply ordinary dispatch choosing the wrong low-risk job.
Many fallback events have no ready rescue candidate. Some events have
mandatory/cover risk information, but local extraction produces no current
executable operation from the accepted local solution. Rescue fallback helps in
a few cases, but does not fix the root cause.
```

Blocking assessment:

```text
Seed 2 does not prevent running Stage 1 expanded-small experiments, because
the algorithm is already competitive on average and runtime is light. It does
block final large-scale claims because reviewers may question service
robustness if the method fails on a visible rescue/fallback corner case.
```

Most likely next fix:

```text
Add a service-ready extraction layer that, after local ALNS, explicitly scans
ready mandatory/cover/high-risk operations in A(t), ranks them by rescue
priority, and commits them if the local plan's first scheduled operation is not
current-time executable. Also log why ready mandatory/cover jobs are missing
from A(t) when shortfall triggers fire.
```

## 8. Missing Code Functions and Outputs

### 8.1 Missing Code Functions

Recommended functions or modules:

```text
scripts/run_paper_a_ablation.py
scripts/run_paper_a_scalability.py
scripts/run_paper_a_robustness.py
src/analysis/paper_a_online_tables.py
```

Recommended small protocol additions:

```text
ablation_variant field in result rows
scale_group / num_jobs / num_machines / num_entities fields in summary rows
robustness_factor fields: rho_range, arrival_intensity, deadline_tightness
general event_trace.csv instead of seed2-specific filename
confidence interval / standard deviation aggregation
runtime budget estimate helper
```

Recommended RG-RALNS stabilization additions:

```text
_extract_service_ready_decisions(...)
_diagnose_rescue_candidate_availability(...)
fallback_failure_reason values for no_ready_ops, no_ready_mandatory, no_A_intersection
unit test reproducing seed 2-style empty local extraction with ready cover job
```

### 8.2 Missing Experiment Outputs

Needed before final paper experiments:

```text
main_comparison_summary.csv
ablation_summary.csv
mechanism_summary.csv
scalability_summary.csv
robustness_summary.csv
paper_table_1_main.csv
paper_table_2_beta_sensitivity.csv
paper_table_3_ablation.csv
paper_table_4_mechanism.csv
paper_table_5_scalability.csv
paper_table_6_robustness.csv
```

The current generic CSVs are enough for engineering validation but not yet enough for a clean paper table pipeline.

## 9. Proposed Experiment Tables

### Table 1: Main Online Comparison

Algorithms:

```text
EDD, SPT, WSPT, ATC, SWD, SFG,
Lightweight RG Dispatch, Online-Legacy-ALNS, RG-RALNS
```

Metrics:

```text
Z_N, TT, WSF, TT_hat, WSF_hat, ZSR, runtime
```

Recommended beta setting:

```text
beta_0 = 20 as main setting, beta_0 = 50 as SLA-intensive comparison
```

### Table 2: Beta Sensitivity

Algorithms:

```text
RG-RALNS, Online-Legacy-ALNS, Lightweight RG Dispatch, EDD
```

Beta values:

```text
1, 5, 10, 20, 50, 100
```

### Table 3: Ablation Study

Variants:

```text
Full RG-RALNS
Lightweight RG Dispatch
without service-safe fallback
without adaptive destroy size
without service-safe acceptance / zero-WSF protection
large-H_A affected-set cap ablation
```

Do not include TT polish as a core ablation unless it is reworked, because the current setting is disabled after it worsened seed 2.

### Table 4: Mechanism Statistics

Fields:

```text
trigger_count
trigger_ratio
shortfall / mandatory / cover / bottleneck reason counts
avg_A_size
max_A_size
alns_runtime_total
dispatch_fallback_count
rescue_fallback_success_count
operator acceptance/reward summary
```

### Table 5: Scalability

Scale groups:

```text
20 jobs, 5 machines, 3 entities
30 jobs, 8 machines, 3 entities
45 jobs, 10 machines, 5 entities
60 jobs, 12 machines, 5 entities
80 jobs, 12 machines, 5 entities
100 jobs, 15 machines, 5 entities
```

For 80/100-job groups, consider excluding Offline-Legacy-ALNS and limiting Online-Legacy-ALNS iterations if runtime grows too sharply.

### Table 6: Robustness

Factors:

```text
arrival_intensity: low, medium, high
rho_range: low, medium, high service pressure
deadline_tightness: loose, medium, tight
seeds: at least 5
```

## 10. Compute-Budget-Aware Staged Experiment Plan

Observed small-instance runtime per run:

```text
RG-RALNS: about 0.04 seconds
Online-Legacy-ALNS: about 2.0 seconds
Offline-Legacy-ALNS: about 4.8 seconds
dispatching baselines: below 0.01 seconds each
Lightweight RG Dispatch: about 0.006 seconds
```

Approximate main-online runtime per small instance, including all nine main algorithms:

```text
about 2.1 seconds
```

Approximate runtime if Offline-Legacy-ALNS is included:

```text
about 6.9 seconds per small instance
```

### Stage 0: Code Stabilization

Purpose:

```text
fix seed 2 readiness / extraction issue
```

Suggested scale:

```text
seeds 0,1,2
beta_0 = 20, 50
small instances only
```

Required work:

```text
add service-ready extraction
add seed-2-style regression test
verify fallback_count and WSF/ZSR
```

Run time:

```text
minutes, not hours
```

### Stage 1: Expanded Small Benchmark

Purpose:

```text
check whether the current trend is stable
```

Suggested scale:

```text
seeds 0,1,2,3,4
main algorithms only
beta_0 = 20, 50
20-job instances first
```

Estimated runtime:

```text
5 seeds * 2 beta settings * 2.1 seconds = about 21 seconds for one instance family
```

Add overhead and CSV writing:

```text
budget 1-3 minutes
```

### Stage 2: Main Benchmark

Purpose:

```text
generate main comparison table
```

Candidate experiment sizes with main-online algorithms only:

| Runs | Estimated small-instance runtime | Practical budget |
|---:|---:|---:|
| 30 | about 63 seconds | 2-5 minutes |
| 60 | about 126 seconds | 4-8 minutes |
| 90 | about 189 seconds | 6-12 minutes |
| 150 | about 315 seconds | 10-20 minutes |

These estimates are based on 20-job small instances. For 60-100 job instances, use a conservative multiplier of 3-10x until measured.

Recommended first main-scale plan:

```text
3 instance sizes
5 seeds each
2 beta settings
main-online algorithms only
total = 30 runs per algorithm family
```

Do not include Offline-Legacy-ALNS in the main table.

### Stage 3: Beta Sensitivity

Purpose:

```text
show SLA penalty intensity trend
```

Recommended algorithms:

```text
RG-RALNS
Online-Legacy-ALNS
Lightweight RG Dispatch
EDD
```

Recommended beta values:

```text
1, 5, 10, 20, 50, 100
```

Use fewer algorithms and the same completed schedules if possible, because beta sensitivity is an evaluation recomputation over final TT/WSF.

### Stage 4: Ablation and Mechanism Analysis

Purpose:

```text
support algorithm design claims
```

Suggested scale:

```text
same 20-job and 45-job groups
seeds 0-4
beta_0 = 20 and 50
```

Run fewer variants first:

```text
Full RG-RALNS
Lightweight RG Dispatch
no rescue fallback
no adaptive destroy
no zero-WSF guard
large H_A
```

### Stage 5: Scalability

Purpose:

```text
show runtime and solution quality under larger instance sizes
```

Suggested plan:

```text
20, 30, 45, 60, 80, 100 jobs
3 seeds first
RG-RALNS, Lightweight RG, EDD, Online-Legacy-ALNS
drop or cap Online-Legacy-ALNS if runtime becomes too high
```

## 11. Current Readiness Checklist

| Requirement | Status | Notes |
|---|---|---|
| Paper A online protocol | Ready | Strict online visibility and current-time commit exist. |
| Main minimum algorithm set | Ready for small benchmarks | All required algorithms run under current runner. |
| Normalized objective | Ready | Reports raw and normalized components plus calibration constants. |
| Beta sensitivity | Ready | Implemented and exported. |
| Mechanism stats | Ready | Trigger, affected-set, fallback, operator stats available. |
| Seed-level debug | Partially ready | Useful trace exists; filename should be generalized. |
| Ablation | Partially ready | Some variants can be toggled; no ablation matrix/labels. |
| Scalability | Not ready | Generator supports it; runner config/output layer missing. |
| Robustness | Not ready | Factors supported individually; no robustness runner/config. |
| Final paper table pipeline | Not ready | Need dedicated summary/table generation scripts. |
| RG-RALNS stability | Partially ready | Competitive, but seed 2 issue remains. |

## 12. Recommended Immediate Next Coding Tasks

1. Fix seed 2 rescue/extraction weakness.

```text
Add service-ready extraction after local ALNS and before ordinary fallback.
Add trace fields that explain why mandatory/cover jobs are not ready or not in A(t).
Add a regression test around empty local extraction with ready cover/mandatory jobs.
```

2. Generalize event trace output.

```text
Rename or supplement rg_ralns_event_trace_seed2.csv with rg_ralns_event_trace.csv.
Keep seed filtering as a runner option if needed.
```

3. Add ablation config matrix.

```text
Add ablation_variant labels and config overrides.
Export ablation_summary.csv.
```

4. Add scale/robustness configs.

```text
configs/paper_a_main_small.yaml
configs/paper_a_scalability.yaml
configs/paper_a_robustness.yaml
```

5. Add paper table generation.

```text
src/analysis/paper_a_online_tables.py
```

## 13. Recommended Immediate Benchmark Tasks

After Stage 0 code stabilization:

```bash
python3 scripts/run_paper_a_online_benchmark.py \
  --config configs/paper_a_online.yaml \
  --seeds 0 1 2 3 4 \
  --objective-beta 20 \
  --output results/paper_a_stage1_beta20

python3 scripts/run_paper_a_online_benchmark.py \
  --config configs/paper_a_online.yaml \
  --seeds 0 1 2 3 4 \
  --objective-beta 50 \
  --output results/paper_a_stage1_beta50
```

Then run beta sensitivity on the selected four algorithms if runtime needs to be constrained.

## 14. Audit Conclusion

The codebase is ready for:

```text
small and expanded-small Paper A online validation
beta sensitivity on the current minimum algorithm set
mechanism diagnostics for RG-RALNS
engineering-level comparison of RG-RALNS vs Online-Legacy-ALNS and dispatch baselines
```

The codebase is not yet ready for:

```text
final paper-scale experiments
final ablation table
final scalability table
final robustness table
fully defensible service-stability claims
```

The main blocker is not the benchmark protocol. The protocol is in good shape. The main blocker is algorithm stability under service-risk fallback, specifically the seed 2 rescue/extraction weakness. The second blocker is experiment orchestration: ablation, scalability, robustness, and paper-table generation need dedicated configs or scripts.

Recommended next action:

```text
Do Stage 0 stabilization next: fix service-ready extraction and add a seed-2-style regression test.
Only after that, run Stage 1 expanded-small experiments.
```

## 15. Git Metadata

Branch:

```text
codex/paper-a-experiment-readiness-audit
```

Commit hash:

```text
916927b docs: audit Paper A experiment readiness
```

Push status:

```text
pending before push attempt
```
