# RG-RALNS Stage 0 Extraction Stabilization Log

Date: 2026-06-12

Branch: `codex/rg-ralns-stage0-extraction-stabilization`

Base branch: `codex/paper-a-experiment-readiness-audit`

## 1. Goal

Implement Stage 0 stabilization for RG-RALNS before expanded experiments. The goal is to fix the service-ready extraction and rescue fallback weakness observed in seed 2, add regression tests that prevent this failure from reappearing, and verify whether RG-RALNS can reliably convert shortfall-triggered events into currently executable rescue decisions when such decisions exist.

This round preserves:

```text
Paper A online visibility
normalized objective evaluation
current-time execution policy
the existing main algorithm name RG-RALNS
the existing baseline set
```

No final-scale experiments were run.

## 2. Previous Issue

Previous performance-tuning result:

| Setting | Z_N | TT | WSF | ZSR | runtime |
|---|---:|---:|---:|---:|---:|
| beta_0 = 20 | 0.1084 | 87.67 | 0.283 | 0.889 | 0.0442 |
| beta_0 = 50 | 0.1979 | 87.67 | 0.283 | 0.889 | 0.0438 |

Known seed 2 weakness before this round:

```text
seed 2 WSF = 0.85
seed 2 ZSR = 0.667
dispatch_fallback_count = 41
shortfall trigger count = 41
```

Diagnosis from the readiness audit:

```text
Many shortfall-triggered or fallback events have no currently executable rescue candidate,
or the local plan's first executable step is not a rescue operation.
```

## 3. Diagnostic Findings

Current flow before this change:

```text
ALNS triggered
-> A(t) constructed
-> local solution decoded
-> _extract_current_feasible_operations(...)
-> if extraction empty, _fallback_dispatch(...)
```

The old extraction logic only accepted scheduled operations whose decoded local start time equaled the current event time:

```text
sop.start_time == state.current_time
```

This created a failure mode:

```text
The local plan may contain a ready mandatory/cover job,
but if the decoded local schedule places that job at a later local start time,
the extractor skips it and returns a lower-priority current operation or no operation.
```

The fallback ladder also mixed two rescue levels:

```text
rescue over A(t)
rescue over all visible ready jobs
ordinary LightweightRGDispatch
```

but it did not separately count A(t)-level rescue success.

## 4. Code Changes

### Change 1: service-ready local extraction

File:

```text
sl_isp_rg_rho_lns/src/algorithms/rg_ralns.py
```

Functions changed:

```text
_extract_current_feasible_operations(...)
_select_current_ready_decisions(...)
```

Change:

```text
The extractor now scans local-plan operations belonging to A(t) and checks whether
they are currently executable at event time t, even if their decoded local
start_time is later than t.
```

Priority among executable local-plan operations:

```text
mandatory rescue jobs
service-cover jobs
high-risk entity jobs
earlier effective production deadline
shorter processing time
larger marginal service contribution
job/op deterministic tie-breaks
```

Expected effect:

```text
Ready rescue-relevant operations in A(t) can be committed immediately even if
they are not the first operation in the decoded local plan.
```

### Change 2: A(t)-level rescue before general rescue fallback

File:

```text
sl_isp_rg_rho_lns/src/algorithms/rg_ralns.py
```

Functions changed:

```text
RGRALNS._fallback_dispatch(...)
```

New fallback ladder:

```text
local-plan executable extraction
-> A(t)-level rescue extraction
-> RescueFallbackDispatch over visible ready jobs
-> ordinary LightweightRGDispatch
```

New counters:

```text
local_extraction_success_count
affected_set_rescue_success_count
```

Updated fallback reasons:

```text
local_plan_no_executable_operation
affected_set_no_ready_rescue
affected_set_rescue_success
rescue_fallback_success
ordinary_fallback_used
no_ready_operation_available
no_rescue_candidate_ready
```

### Change 3: ready rescue priority in A(t) cap

File:

```text
sl_isp_rg_rho_lns/src/algorithms/rg_ralns.py
```

Function changed:

```text
_affected_cap_priority(...)
```

New priority:

```text
ready mandatory jobs first
all mandatory jobs second
ready cover jobs third
all cover jobs fourth
new high-risk arrivals fifth
ready high-risk jobs sixth
bottleneck competitors seventh
earlier effective deadline eighth
smaller remaining work ninth
```

Expected effect:

```text
Small H_A values should not push ready mandatory jobs out of A(t).
```

### Change 4: mechanism output fields

File:

```text
sl_isp_rg_rho_lns/src/experiments/paper_a_online_protocol.py
```

Added fields to mechanism and fallback outputs:

```text
local_extraction_success_count
affected_set_rescue_success_count
mean_local_extraction_success_count
mean_affected_set_rescue_success_count
```

## 5. Regression Tests Added

File:

```text
sl_isp_rg_rho_lns/tests/test_rg_ralns.py
```

New/updated tests:

| Test | Purpose |
|---|---|
| `test_local_extraction_skips_non_rescue_prefix_and_selects_ready_mandatory` | Ensures a ready mandatory job scheduled later in the local plan is extracted before a lower-priority current operation. |
| `test_ready_mandatory_job_cannot_be_excluded_by_affected_set_cap` | Ensures a ready mandatory job remains in A(t) even when `H_A = 1`. |
| `test_affected_set_rescue_dispatch_runs_before_ordinary_fallback` | Ensures A(t)-level rescue is attempted before ordinary dispatch. |
| `test_ordinary_fallback_is_allowed_when_no_rescue_candidate_exists` | Ensures ordinary fallback is still allowed when no rescue candidate exists. |
| `test_service_ready_extraction_keeps_future_jobs_invisible` | Ensures future job-level details remain invisible to extraction. |

Red/green evidence:

```text
Before implementation, 4 of the 5 new focused tests failed.
After implementation, all 5 focused tests passed.
```

## 6. Validation Commands

Focused new regression tests:

```bash
python3 -m pytest \
  sl_isp_rg_rho_lns/tests/test_rg_ralns.py::test_local_extraction_skips_non_rescue_prefix_and_selects_ready_mandatory \
  sl_isp_rg_rho_lns/tests/test_rg_ralns.py::test_ready_mandatory_job_cannot_be_excluded_by_affected_set_cap \
  sl_isp_rg_rho_lns/tests/test_rg_ralns.py::test_affected_set_rescue_dispatch_runs_before_ordinary_fallback \
  sl_isp_rg_rho_lns/tests/test_rg_ralns.py::test_ordinary_fallback_is_allowed_when_no_rescue_candidate_exists \
  sl_isp_rg_rho_lns/tests/test_rg_ralns.py::test_service_ready_extraction_keeps_future_jobs_invisible -q
```

Required tests:

```bash
python3 -m pytest sl_isp_rg_rho_lns/tests/test_rg_ralns.py \
  sl_isp_rg_rho_lns/tests/test_paper_a_online_benchmark_protocol.py \
  sl_isp_rg_rho_lns/tests/test_paper_a_online_baselines.py -q
```

Compile:

```bash
python3 -m py_compile \
  sl_isp_rg_rho_lns/src/algorithms/rg_ralns.py \
  sl_isp_rg_rho_lns/src/experiments/paper_a_online_protocol.py \
  scripts/run_paper_a_online_benchmark.py
```

Seed 2 diagnostic:

```bash
python3 scripts/run_paper_a_online_benchmark.py \
  --config configs/paper_a_online.yaml \
  --seeds 2 \
  --rg-debug-trace \
  --output results/paper_a_stage0_seed2_extraction_debug
```

Small validation:

```bash
python3 scripts/run_paper_a_online_benchmark.py \
  --config configs/paper_a_online.yaml \
  --seeds 0 1 2 \
  --objective-beta 20 \
  --output results/paper_a_stage0_beta20

python3 scripts/run_paper_a_online_benchmark.py \
  --config configs/paper_a_online.yaml \
  --seeds 0 1 2 \
  --objective-beta 50 \
  --output results/paper_a_stage0_beta50
```

## 7. Validation Results

Focused regression tests:

```text
5 passed, 1 warning
```

Required tests:

```text
28 passed, 1 warning
```

Warning:

```text
PytestConfigWarning: Unknown config option: timeout
```

This warning is pre-existing and does not fail the run.

Py compile:

```text
passed
```

## 8. Benchmark Results

### beta_0 = 20

| Algorithm | Z_N | TT | WSF | ZSR | runtime |
|---|---:|---:|---:|---:|---:|
| RG-RALNS | 0.1080 | 88.00 | 0.283 | 0.889 | 0.0447 |
| Online-Legacy-ALNS | 0.1197 | 48.67 | 0.443 | 0.778 | 2.0143 |
| Lightweight RG Dispatch | 0.1261 | 119.67 | 0.283 | 0.889 | 0.0058 |
| EDD | 0.8802 | 67.00 | 4.003 | 0.667 | 0.0013 |

RG-RALNS mechanism by seed:

| Seed | trigger_ratio | avg_A_size | fallback | local extraction success | A(t) rescue success | general rescue success | ordinary fallback |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 0.255 | 6.07 | 6 | 21 | 3 | 0 | 3 |
| 1 | 0.136 | 7.07 | 1 | 13 | 1 | 0 | 0 |
| 2 | 0.614 | 3.32 | 36 | 26 | 1 | 0 | 35 |

### beta_0 = 50

| Algorithm | Z_N | TT | WSF | ZSR | runtime |
|---|---:|---:|---:|---:|---:|
| RG-RALNS | 0.1975 | 88.00 | 0.283 | 0.889 | 0.0448 |
| Online-Legacy-ALNS | 0.2596 | 48.67 | 0.443 | 0.778 | 2.0118 |
| Lightweight RG Dispatch | 0.2156 | 119.67 | 0.283 | 0.889 | 0.0059 |
| EDD | 2.1443 | 67.00 | 4.003 | 0.667 | 0.0014 |

### Seed 2 diagnostic

Seed 2 RG-RALNS after Stage 0:

```text
Z_N(beta_0=20) = 0.2542
TT = 125
WSF = 0.85
ZSR = 0.667
trigger_ratio = 0.614
dispatch_fallback_count = 36
local_extraction_success_count = 26
affected_set_rescue_success_count = 1
ordinary_fallback_count = 35
```

Seed 2 event trace:

```text
trace rows = 101
shortfall rows = 40
fallback count = 36
fallback reasons:
  no_ready_operation_available = 29
  ordinary_fallback_used = 6
  affected_set_rescue_success = 1
nonfallback decision rows = 38
fallback rows with decisions = 7
```

## 9. Before/After Comparison

| Setting | Version | Z_N | TT | WSF | ZSR | fallback | local extraction success | A(t) rescue success |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| beta_0 = 20 | previous | 0.1084 | 87.67 | 0.283 | 0.889 | 17.0 mean | n/a | n/a |
| beta_0 = 20 | Stage 0 | 0.1080 | 88.00 | 0.283 | 0.889 | 14.3 mean | 20.0 mean | 1.7 mean |
| beta_0 = 50 | previous | 0.1979 | 87.67 | 0.283 | 0.889 | 17.0 mean | n/a | n/a |
| beta_0 = 50 | Stage 0 | 0.1975 | 88.00 | 0.283 | 0.889 | 14.3 mean | 20.0 mean | 1.7 mean |
| seed 2 | previous | 0.2717 at beta_0=20 | 154 | 0.85 | 0.667 | 41 | n/a | n/a |
| seed 2 | Stage 0 | 0.2542 at beta_0=20 | 125 | 0.85 | 0.667 | 36 | 26 | 1 |

Interpretation:

```text
Stage 0 improved extraction/fallback behavior and reduced seed 2 TT and fallback count.
It did not fix seed 2 WSF/ZSR.
```

## 10. Was Seed 2 Fixed?

No, not fully.

Improved:

```text
seed 2 TT improved from 154 to 125
seed 2 fallback count improved from 41 to 36
local extraction now succeeds 26 times on seed 2
A(t)-level rescue succeeds once on seed 2
overall Z_N slightly improves at beta_0=20 and beta_0=50
```

Not improved:

```text
seed 2 WSF remains 0.85
seed 2 ZSR remains 0.667
ordinary fallback remains high at 35 on seed 2
many fallback events still have no ready operation available
```

Conclusion:

```text
The service-ready extraction bug is fixed, but seed 2 service shortfall is not fully solved.
The remaining issue is likely earlier rescue opportunity timing / affected-set readiness,
not merely extraction from an already-decoded local plan.
```

## 11. Remaining Limitations

1. `no_ready_operation_available` remains frequent in seed 2.
2. A(t)-level rescue success is low on seed 2.
3. WSF/ZSR did not improve in the three-seed mean because seed 2 service failure remains.
4. The event trace file is still named `rg_ralns_event_trace_seed2.csv`; a general event trace filename remains a future cleanup.
5. This round did not add ablation, scalability, or robustness runners.

## 12. Readiness for Stage 1

RG-RALNS is now more stable mechanically and more auditable than before Stage 0. The code can proceed to a small Stage 1 expanded-small diagnostic benchmark, but final paper-scale experiments should still wait until the seed 2 service shortfall is addressed more directly.

Recommended Stage 1 condition:

```text
Run seeds 0-4 only after adding one more diagnostic/fix around early rescue timing
or accept that Stage 1 is diagnostic rather than final.
```

## 13. Git Metadata

Branch:

```text
codex/rg-ralns-stage0-extraction-stabilization
```

Commit hash:

```text
pending at initial log creation
```

Push status:

```text
pending at initial log creation
```
