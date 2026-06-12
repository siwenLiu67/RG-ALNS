# RG-RALNS Stage 0.5 Rescue-Chain Diagnosis Log

## 1. Goal

Stage 0.5 diagnoses why RG-RALNS still produces service shortfall on seed 2 after Stage 0 service-ready extraction was fixed. The focus is precursor-chain and rescue-readiness behavior: whether mandatory or cover jobs enter the affected set before their final rescue operation is ready, whether their next unfinished operations are advanced early enough, whether `Q_rec` is too optimistic, and whether the trigger reacts too late.

The online information protocol and normalized objective evaluation remain unchanged. No new baselines or final-scale experiments were added.

## 2. Stage 0 Remaining Issue

Reference branch before this round:

```text
codex/rg-ralns-stage0-extraction-stabilization
2934dcb docs: record RG-RALNS stage0 push status
```

Stage 0 reference under beta_0 = 20, seeds 0,1,2:

| Method | Z_N | TT | WSF | ZSR | Runtime |
|---|---:|---:|---:|---:|---:|
| RG-RALNS | 0.1080 | 88.00 | 0.283 | 0.889 | 0.0504 |

Seed 2 remained weak:

```text
seed 2: TT=125, WSF=0.85, ZSR=0.667
fallback=36, local_extraction_success=26, affected_set_rescue_success=1
```

## 3. Rescue-Chain Diagnostic Design

The event trace was extended to record rescue-chain fields:

```text
entity_class_by_entity
ready_mandatory_jobs
ready_cover_jobs
not_ready_mandatory_jobs
not_ready_cover_jobs
mandatory_predecessor_ops
cover_predecessor_ops
whether_mandatory_predecessors_in_A
whether_cover_predecessors_in_A
whether_mandatory_predecessors_selected
whether_cover_predecessors_selected
A_ready_jobs
A_precursor_jobs
selected_decisions
selected_job_rescue_chain_rank
WSF_after_event_or_final_if_available
min_slack_lb_by_entity
avg_slack_lb_by_entity
low_slack_recoverable_by_entity
```

Mechanism statistics were also extended with precursor counters:

```text
mandatory_precursor_in_A_count
cover_precursor_in_A_count
mandatory_precursor_selected_count
cover_precursor_selected_count
```

## 4. Code Changes

Change 1: Recoverability slack diagnostics

- File: `sl_isp_rg_rho_lns/src/algorithms/rg_ralns.py`
- Functions/classes: `RGRALNSConfig`, `EntityDiagnostics`, `compute_recoverability_diagnostics`
- Reason: record whether visible recoverable jobs have little optimistic delivery slack.
- Expected effect: distinguish true rescue-readiness failure from overly optimistic `Q_rec`.
- Risk: changing the recoverability definition would alter the method. To avoid this, the default `recoverability_slack_margin` remains `0.0`.

Change 2: Rescue-chain rank for current-time decisions

- File: `sl_isp_rg_rho_lns/src/algorithms/rg_ralns.py`
- Functions/classes: `_rescue_chain_rank`, `_dispatch_priority`, `_rescue_fallback_priority`, `_select_current_ready_decisions`
- Reason: treat the next currently executable operation of mandatory or cover jobs as service-relevant, even if it is a precursor operation.
- Expected effect: ready rescue-chain operations can be selected before low-risk competitors.
- Risk: making chain rank the primary order destabilized seed 1. The final implementation keeps the original service rank as the primary key and uses rescue-chain rank as a tie-break/current-time diagnostic key.

Change 3: Affected-set precursor priority

- File: `sl_isp_rg_rho_lns/src/algorithms/rg_ralns.py`
- Function: `_affected_cap_priority`
- Reason: ensure ready mandatory and cover precursor jobs are not pushed out by the `H_A` cap.
- Expected effect: mandatory/cover precursor jobs remain eligible for local RG-ALNS before the final operation becomes ready.
- Risk: if used too aggressively, A(t) can drift from local repair to broader backlog selection. The size cap remains active.

Change 4: Optional early rescue trigger

- File: `sl_isp_rg_rho_lns/src/algorithms/rg_ralns.py`
- Functions/classes: `RGRALNSConfig`, `_should_trigger_due_to_ready_rescue_precursor`, `_trigger_reasons`
- Reason: allow controlled diagnosis of whether ready rescue precursors should trigger ALNS earlier.
- Expected effect: supports experimental probing.
- Risk: wider triggering can increase runtime and disruption. Default remains `early_rescue_trigger: false`.

Change 5: Benchmark config and mechanism output

- Files:
  - `configs/paper_a_online.yaml`
  - `sl_isp_rg_rho_lns/src/experiments/paper_a_online_protocol.py`
- Reason: pass through the new diagnostic/toggle parameters and export precursor counters.

## 5. Regression Tests

Added to `sl_isp_rg_rho_lns/tests/test_rg_ralns.py`:

```text
test_ready_mandatory_precursor_stays_in_affected_set_and_gets_chain_priority
test_cover_precursor_priority_beats_low_risk_competitor
test_ready_mandatory_precursor_cannot_be_excluded_by_affected_set_cap
test_slack_diagnostic_identifies_risky_recoverable_jobs
test_rescue_chain_logic_keeps_future_job_details_invisible
```

These tests check precursor inclusion, rescue-chain priority, `H_A` protection, slack diagnostics, and online visibility.

## 6. Validation Commands

```bash
python3 -m pytest sl_isp_rg_rho_lns/tests/test_rg_ralns.py \
  sl_isp_rg_rho_lns/tests/test_paper_a_online_benchmark_protocol.py \
  sl_isp_rg_rho_lns/tests/test_paper_a_online_baselines.py -q

python3 -m py_compile \
  sl_isp_rg_rho_lns/src/algorithms/rg_ralns.py \
  sl_isp_rg_rho_lns/src/experiments/paper_a_online_protocol.py \
  scripts/run_paper_a_online_benchmark.py

python3 scripts/run_paper_a_online_benchmark.py \
  --config configs/paper_a_online.yaml \
  --seeds 2 \
  --rg-debug-trace \
  --output results/paper_a_stage05_seed2_rescue_chain_debug

python3 scripts/run_paper_a_online_benchmark.py \
  --config configs/paper_a_online.yaml \
  --seeds 0 1 2 \
  --objective-beta 20 \
  --output results/paper_a_stage05_beta20

python3 scripts/run_paper_a_online_benchmark.py \
  --config configs/paper_a_online.yaml \
  --seeds 0 1 2 \
  --objective-beta 50 \
  --output results/paper_a_stage05_beta50
```

Additional diagnostic probes, not adopted as defaults:

```text
results/paper_a_stage05_beta20_early_probe
results/paper_a_stage05_beta20_margin1_probe
results/paper_a_stage05_seed1_rescue_chain_debug
```

## 7. Validation Results

Pytest:

```text
33 passed, 1 warning
```

The warning is the existing pytest configuration warning for unknown `timeout`.

Py compile:

```text
passed
```

## 8. Seed 2 Diagnostic Findings

Seed 2 debug output:

```text
results/paper_a_stage05_seed2_rescue_chain_debug/rg_ralns_event_trace_seed2.csv
```

RG-RALNS seed 2 result:

| Z_N | TT | WSF | ZSR | Runtime |
|---:|---:|---:|---:|---:|
| 0.2542 | 125 | 0.850 | 0.667 | 0.0616 |

Mechanism findings:

```text
trigger_ratio = 0.614
avg_A_size = 3.323
dispatch_fallback_count = 36
local_extraction_success_count = 26
affected_set_rescue_success_count = 1
ordinary_fallback_count = 35
mandatory_precursor_in_A_count = 24
cover_precursor_in_A_count = 34
mandatory_precursor_selected_count = 7
cover_precursor_selected_count = 13
```

Event-trace findings:

```text
mandatory predecessor in A events = 17
cover predecessor in A events = 21
mandatory predecessor selected events = 6
cover predecessor selected events = 12
no_ready_operation_available events = 29
low-slack recoverable events = 1
```

Interpretation: mandatory/cover precursor jobs do enter A(t) and are sometimes selected. The remaining seed 2 shortfall is not primarily caused by local-plan extraction skipping ready rescue operations. Many fallback events occur when no current ready operation exists at all, so the simulator cannot execute a rescue action at that event time.

The `recoverability_slack_margin=1.0` probe did not change beta_0=20 results, suggesting the seed 2 failure is not explained by a simple one-unit optimistic slack boundary in `Q_rec`.

The `early_rescue_trigger=true` probe did not improve WSF/ZSR and slightly worsened runtime/TT, so it was not adopted as the default.

## 9. beta_0 = 20 Comparison

Final Stage 0.5 results:

| Method | Z_N | TT | WSF | ZSR | Runtime |
|---|---:|---:|---:|---:|---:|
| RG-RALNS | 0.1080 | 88.00 | 0.283 | 0.889 | 0.0476 |
| Online-Legacy-ALNS | 0.1197 | 48.67 | 0.443 | 0.778 | 2.0975 |
| Lightweight RG Dispatch | 0.1261 | 119.67 | 0.283 | 0.889 | 0.0071 |
| EDD | 0.8802 | 67.00 | 4.003 | 0.667 | 0.0014 |

RG-RALNS per seed:

| Seed | Z_N | TT | WSF | ZSR |
|---:|---:|---:|---:|---:|
| 0 | 0.0266 | 50 | 0.000 | 1.000 |
| 1 | 0.0432 | 89 | 0.000 | 1.000 |
| 2 | 0.2542 | 125 | 0.850 | 0.667 |

## 10. beta_0 = 50 Comparison

Final Stage 0.5 results:

| Method | Z_N | TT | WSF | ZSR | Runtime |
|---|---:|---:|---:|---:|---:|
| RG-RALNS | 0.1975 | 88.00 | 0.283 | 0.889 | 0.0476 |
| Lightweight RG Dispatch | 0.2156 | 119.67 | 0.283 | 0.889 | 0.0071 |
| Online-Legacy-ALNS | 0.2596 | 48.67 | 0.443 | 0.778 | 2.1006 |
| EDD | 2.1443 | 67.00 | 4.003 | 0.667 | 0.0014 |

RG-RALNS per seed:

| Seed | Z_N | TT | WSF | ZSR |
|---:|---:|---:|---:|---:|
| 0 | 0.0266 | 50 | 0.000 | 1.000 |
| 1 | 0.0432 | 89 | 0.000 | 1.000 |
| 2 | 0.5226 | 125 | 0.850 | 0.667 |

## 11. Before/After Summary

| Setting | Version | Z_N | TT | WSF | ZSR | Runtime |
|---|---|---:|---:|---:|---:|---:|
| beta_0=20 | Stage 0 | 0.1080 | 88.00 | 0.283 | 0.889 | 0.0504 |
| beta_0=20 | Stage 0.5 | 0.1080 | 88.00 | 0.283 | 0.889 | 0.0476 |
| beta_0=50 | Stage 0 | 0.1975 | 88.00 | 0.283 | 0.889 | about 0.045 |
| beta_0=50 | Stage 0.5 | 0.1975 | 88.00 | 0.283 | 0.889 | 0.0476 |

Stage 0.5 preserves the Stage 0 small-benchmark performance while adding rescue-chain and slack diagnostics. It does not fix seed 2 WSF/ZSR.

## 12. Is Seed 2 Fixed?

No.

Seed 2 remains:

```text
WSF = 0.85
ZSR = 0.667
TT = 125
```

The trace indicates that:

1. Mandatory and cover precursor jobs are present in A(t) before final rescue completion.
2. Some precursor operations are selected.
3. Many failed fallback events have no currently ready operation at all.
4. Low-slack recoverability is rare in seed 2 and a positive slack margin probe did not alter the outcome.

Therefore, the current evidence points to a deeper timing/capacity issue rather than a current-time extraction priority bug. The remaining failure likely requires an earlier look-ahead style rescue readiness policy, a less myopic local decode for precursor chains, or a machine-capacity reservation/risk test. Those would be Stage 1 design changes and should not be slipped into Stage 0.5.

## 13. Readiness for Stage 1

RG-RALNS is ready for a Stage 1 expanded-small benchmark only with the caveat that seed 2 remains an unresolved stress case. Stage 1 should keep seed-level reporting and mechanism diagnostics enabled for at least a subset of runs.

Recommended Stage 1 guardrails:

```text
seeds: 0,1,2,3,4
beta_0: 20,50
main algorithms only
preserve per-seed WSF/ZSR and fallback diagnostics
```

Do not proceed to final paper-scale experiments until the seed-level robustness question is either fixed or explicitly framed as a stress-case limitation.

## 14. Git Metadata

Branch:

```text
codex/rg-ralns-stage05-rescue-chain
```

Commit after modification:

```text
f29c74c fix: add RG-RALNS rescue-chain readiness diagnostics
```

Push status:

```text
pending at documentation update time
```
