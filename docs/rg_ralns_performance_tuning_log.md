# RG-RALNS Performance Tuning Log

Date: 2026-06-11

## 1. Goal

Improve RG-RALNS under the normalized Paper A online benchmark by diagnosing seed-specific rescue/fallback failures, improving service-safe fallback behavior, and verifying whether RG-RALNS can achieve a better trade-off among normalized objective, TT, WSF, ZSR, and runtime.

This round does not change the online information protocol, does not add new baselines, and does not change the theoretical objective structure. The normalized objective calibration from the previous round remains:

```text
TT_hat  = TT / Theta_I
WSF_hat = WSF / Omega_I
Z_N     = alpha_0 * TT_hat + beta_0 * WSF_hat
```

## 2. Baseline Before Modification

Branch before modification:

```text
codex/normalized-objective-sensitivity
```

Commit hash before modification:

```text
4c324fa docs: record normalized objective validation log
```

Reference benchmark output path used as baseline:

```text
results/paper_a_normalized_small
```

Pre-modification beta_0 = 20 reference results:

| Algorithm | Z_N | TT | WSF | ZSR | runtime |
|---|---:|---:|---:|---:|---:|
| RG-RALNS | 0.1191 | 107.67 | 0.283 | 0.889 | 0.0251 |
| Online-Legacy-ALNS | 0.1197 | 48.67 | 0.443 | 0.778 | 2.0074 |
| Lightweight RG Dispatch | 0.1261 | 119.67 | 0.283 | 0.889 | 0.0056 |
| EDD | 0.8802 | 67.00 | 4.003 | 0.667 | 0.0013 |

Known issue before this round:

```text
seed 2 had WSF = 0.85, ZSR = 0.667, dispatch_fallback_count = 41,
and shortfall-trigger events = 41.
```

## 3. Problem Diagnosis

Seed 2 diagnostic command:

```bash
python3 scripts/run_paper_a_online_benchmark.py \
  --config configs/paper_a_online.yaml \
  --seeds 2 \
  --rg-debug-trace \
  --output results/paper_a_rg_ralns_seed2_debug
```

Seed 2 trace output:

```text
results/paper_a_rg_ralns_seed2_debug/rg_ralns_event_trace_seed2.csv
```

Diagnostic findings for RG-RALNS on seed 2 after the tuning implementation:

| Item | Value |
|---|---:|
| event trace rows | 98 |
| triggered ALNS rows | 63 |
| fallback events | 41 |
| shortfall trigger count | 41 |
| empty local extraction fallback | 26 |
| empty affected set fallback | 15 |
| fallback events with empty ready set | 31 |
| fallback events with mandatory jobs present | 23 |
| fallback events with cover jobs present | 26 |
| fallback events where `A(t)` intersects mandatory jobs | 7 |
| fallback events where `A(t)` intersects cover jobs | 19 |
| rescue fallback successes | 4 |
| ordinary fallback count | 37 |

Fallback failure counters:

| Reason | Count |
|---|---:|
| no_rescue_candidate_in_A | 22 |
| no_rescue_candidate_ready | 37 |

The main suspected failure mechanism is not that ordinary fallback always ignores rescue candidates. In many fallback events there is no currently executable rescue candidate. In other events the accepted local plan has no executable first operation at the current event time, so the execution policy falls back even though service-risk diagnostics are active. The affected set is usually local and capped, but seed 2 still contains shortfall states where mandatory/cover information exists without a ready rescue action. This remains the main unresolved seed-specific weakness.

An attempted TT polishing setting with `tt_polish_max_moves = 10` worsened seed 2 substantially (`WSF = 2.85`, `ZSR = 0.667` in the diagnostic run). Therefore the TT polish mechanism is retained in code but disabled by default in the selected configuration.

## 4. Implemented Changes

Change 1: RescueFallbackDispatch

- File: `sl_isp_rg_rho_lns/src/algorithms/rg_ralns.py`
- Functions/classes: `_rescue_fallback_dispatch`, `_rescue_fallback_priority`, `RGRALNS._fallback_dispatch`
- Reason: ALNS extraction can return no current-time executable operation even when service-risk diagnostics are active.
- Expected effect: Try mandatory, cover, and high-risk ready operations before ordinary lightweight dispatch.
- Risk: Can preserve service at the cost of TT if used too aggressively.

Change 2: service-aware extraction and fallback accounting

- File: `sl_isp_rg_rho_lns/src/algorithms/rg_ralns.py`
- Functions/classes: `RGRALNS.__call__`, `RGRALNS._fallback_dispatch`, `RGRALNS._record_event_trace`
- Reason: Need to distinguish empty affected sets, empty local extraction, rescue fallback, and ordinary fallback.
- Expected effect: Make seed-specific failures auditable and prevent silent loss of rescue opportunities.
- Risk: Adds diagnostic state to the algorithm object; all counters are reset per algorithm instance and do not affect online visibility.

Change 3: adaptive destroy size

- File: `sl_isp_rg_rho_lns/src/algorithms/rg_ralns.py`
- Functions/classes: `RGRALNSConfig`, `RGRALNS._destroy_size`
- Reason: Higher-risk states need more repair freedom, while low-risk states should avoid unnecessary disruption.
- Expected effect: Improve local ALNS flexibility without increasing affected-set scope.
- Risk: More aggressive destruction in risk states can increase runtime slightly.

Change 4: conservative service-risk acceptance

- File: `sl_isp_rg_rho_lns/src/algorithms/rg_ralns.py`
- Functions/classes: `_accept_candidate`, `_acceptance_reason`
- Reason: With normalized objective and beta_0 >= 20, a candidate should not move from zero WSF to positive WSF just for a TT gain.
- Expected effect: Preserve WSF/ZSR advantage while allowing Z/TT improvements when service is safe.
- Risk: Can reject some TT-improving candidates.

Change 5: operator scoring and logging

- File: `sl_isp_rg_rho_lns/src/algorithms/rg_ralns.py`
- Functions/classes: `_operator_reward`, `RGRALNS.operator_stats_rows`, local ALNS loop
- Reason: Standard ALNS practice uses operator performance feedback. This round keeps the mechanism simple and bounded.
- Expected effect: Record which destroy/repair operators are selected and accepted.
- Risk: The current small benchmark is too small to draw strong conclusions about operator weights.

Change 6: benchmark diagnostic outputs

- File: `sl_isp_rg_rho_lns/src/experiments/paper_a_online_protocol.py`
- Functions/classes: `run_paper_a_online_benchmark`, `_run_one_algorithm`, `_tuning_comparison_rows`
- Reason: The benchmark needs event trace, fallback stats, operator stats, and tuning comparison exports.
- Expected effect: Make Paper A RG-RALNS tuning reproducible and auditable.
- Risk: Additional CSV outputs are for diagnostics only and are not used by algorithms.

Change 7: runner flags

- File: `scripts/run_paper_a_online_benchmark.py`
- Functions/classes: `main`
- Reason: Need command-line support for seed traces and beta override.
- Expected effect: Support `--rg-debug-trace` and `--objective-beta`.
- Risk: None observed; defaults preserve existing behavior.

## 5. Configuration Changes

Selected configuration in `configs/paper_a_online.yaml`:

```yaml
rg_ralns:
  H_A: 8
  N_A: 40
  acceptance_mode: service_safe_z
  bottleneck_trigger_mode: normal
  rescue_fallback_enabled: true
  protect_zero_wsf: true
  adaptive_destroy_size: true
  destroy_fraction_low: 0.25
  destroy_fraction_mid: 0.35
  destroy_fraction_high: 0.50
  tt_polish_max_moves: 0
  regret_k: 2
  eps: 1.0e-9
  destroy_fraction: 0.35
```

Small internal sweep at beta_0 = 20, seeds 0,1,2:

| Configuration | Z_N | TT | WSF | ZSR | runtime | fallback | rescue successes |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline emulation | 0.1191 | 107.67 | 0.283 | 0.889 | 0.0258 | 17.0 | 0.0 |
| rescue only | 0.1191 | 107.67 | 0.283 | 0.889 | 0.0256 | 17.0 | 3.67 |
| rescue + adaptive | 0.1191 | 107.67 | 0.283 | 0.889 | 0.0259 | 17.0 | 3.67 |
| full with TT polish 10 | 0.2757 | 114.00 | 0.997 | 0.778 | 0.0304 | 24.33 | 3.67 |
| H_A 8, N_A 40, TT polish 0 | 0.1084 | 87.67 | 0.283 | 0.889 | 0.0444 | 16.0 | 3.0 |

The selected configuration keeps TT polish disabled and uses the larger `N_A = 40` local search budget.

## 6. Validation Commands

Test command:

```bash
python3 -m pytest sl_isp_rg_rho_lns/tests/test_paper_a_current_time_execution.py \
  sl_isp_rg_rho_lns/tests/test_paper_a_online_visibility.py \
  sl_isp_rg_rho_lns/tests/test_paper_a_online_baselines.py \
  sl_isp_rg_rho_lns/tests/test_paper_a_online_benchmark_protocol.py \
  sl_isp_rg_rho_lns/tests/test_rg_ralns.py sl_isp_rg_rho_lns/tests/test_online_simulator.py \
  sl_isp_rg_rho_lns/tests/test_simulator.py sl_isp_rg_rho_lns/tests/test_recoverability.py -q
```

Compile command:

```bash
python3 -m py_compile \
  sl_isp_rg_rho_lns/src/algorithms/rg_ralns.py \
  sl_isp_rg_rho_lns/src/experiments/paper_a_online_protocol.py \
  scripts/run_paper_a_online_benchmark.py
```

Smoke benchmark:

```bash
python3 scripts/run_paper_a_online_benchmark.py \
  --config configs/paper_a_online.yaml \
  --seeds 0 \
  --output /tmp/paper_a_rg_ralns_tuned_smoke
```

Seed 2 diagnostic:

```bash
python3 scripts/run_paper_a_online_benchmark.py \
  --config configs/paper_a_online.yaml \
  --seeds 2 \
  --rg-debug-trace \
  --output results/paper_a_rg_ralns_seed2_debug
```

Focused beta_0 = 20 benchmark:

```bash
python3 scripts/run_paper_a_online_benchmark.py \
  --config configs/paper_a_online.yaml \
  --seeds 0 1 2 \
  --objective-beta 20 \
  --output results/paper_a_rg_ralns_tuning_beta20
```

Focused beta_0 = 50 benchmark:

```bash
python3 scripts/run_paper_a_online_benchmark.py \
  --config configs/paper_a_online.yaml \
  --seeds 0 1 2 \
  --objective-beta 50 \
  --output results/paper_a_rg_ralns_tuning_beta50
```

Beta sensitivity:

```bash
python3 scripts/run_paper_a_online_benchmark.py \
  --config configs/paper_a_online.yaml \
  --seeds 0 1 2 \
  --beta-sensitivity 1 5 10 20 50 100 \
  --output results/paper_a_rg_ralns_tuned_beta_sensitivity
```

## 7. Validation Results

Pytest result:

```text
96 passed, 1 warning in 0.56s
```

Warning:

```text
PytestConfigWarning: Unknown config option: timeout
```

This warning is pre-existing test configuration behavior and did not fail the test run.

Py compile result:

```text
passed
```

Smoke result at seed 0:

| Algorithm | Z_N | TT | WSF | ZSR | runtime |
|---|---:|---:|---:|---:|---:|
| RG-RALNS | 0.0069 | 13.00 | 0.000 | 1.000 | 0.0464 |
| Online-Legacy-ALNS | 0.0122 | 23.00 | 0.000 | 1.000 | 3.1829 |
| Lightweight RG Dispatch | 0.0469 | 88.00 | 0.000 | 1.000 | 0.0069 |
| EDD | 0.0106 | 20.00 | 0.000 | 1.000 | 0.0014 |

## 8. Before/After Comparison

beta_0 = 20:

| Algorithm | Z_N | TT | WSF | ZSR | runtime | trigger_ratio | avg_A_size | dispatch_fallback_count | rescue_success |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RG-RALNS before this round | 0.1191 | 107.67 | 0.283 | 0.889 | 0.0251 | n/a | n/a | 17.0 | 0.0 |
| RG-RALNS after this round | 0.1084 | 87.67 | 0.283 | 0.889 | 0.0442 | 0.3409 | 5.4314 | 16.0 | 3.0 |
| Online-Legacy-ALNS | 0.1197 | 48.67 | 0.443 | 0.778 | 2.0444 | 0.0 | 0.0 | 0.0 | 0.0 |
| Lightweight RG Dispatch | 0.1261 | 119.67 | 0.283 | 0.889 | 0.0059 | 0.0 | 0.0 | 0.0 | 0.0 |
| EDD | 0.8802 | 67.00 | 4.003 | 0.667 | 0.0013 | 0.0 | 0.0 | 0.0 | 0.0 |

beta_0 = 50:

| Algorithm | Z_N | TT | WSF | ZSR | runtime | trigger_ratio | avg_A_size | dispatch_fallback_count | rescue_success |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RG-RALNS after this round | 0.1979 | 87.67 | 0.283 | 0.889 | 0.0438 | 0.3409 | 5.4314 | 16.0 | 3.0 |
| Online-Legacy-ALNS | 0.2596 | 48.67 | 0.443 | 0.778 | 2.0585 | 0.0 | 0.0 | 0.0 | 0.0 |
| Lightweight RG Dispatch | 0.2156 | 119.67 | 0.283 | 0.889 | 0.0061 | 0.0 | 0.0 | 0.0 | 0.0 |
| EDD | 2.1443 | 67.00 | 4.003 | 0.667 | 0.0014 | 0.0 | 0.0 | 0.0 | 0.0 |

## 9. Beta Sensitivity After Tuning

| beta_0 | RG-RALNS Z_N | Lightweight RG Z_N | Online-Legacy-ALNS Z_N | EDD Z_N | RG rank by Z_N |
|---:|---:|---:|---:|---:|---:|
| 1 | 0.0518 | 0.0694 | 0.0310 | 0.0796 | 3 |
| 5 | 0.0637 | 0.0814 | 0.0497 | 0.2482 | 3 |
| 10 | 0.0786 | 0.0963 | 0.0730 | 0.4588 | 3 |
| 20 | 0.1084 | 0.1261 | 0.1197 | 0.8802 | 2 |
| 50 | 0.1979 | 0.2156 | 0.2596 | 2.1443 | 2 |
| 100 | 0.3470 | 0.3647 | 0.4929 | 4.2511 | 2 |

RG-RALNS keeps the same mean `WSF = 0.283` and `ZSR = 0.889` as Lightweight RG Dispatch, while reducing mean TT from 119.67 to 87.67. Compared with Online-Legacy-ALNS, RG-RALNS has higher TT but lower WSF and higher ZSR; it becomes better on normalized Z_N at beta_0 >= 20 in this small benchmark.

## 10. Interpretation

1. Did seed 2 WSF/ZSR improve?

No. Seed 2 remains `WSF = 0.85` and `ZSR = 0.667`. The tuning improved the three-seed mean TT/Z_N but did not remove the seed 2 rescue weakness.

2. Did fallback count decrease?

Only at the three-seed average level, from about 17.0 to 16.0. Seed 2 itself remains at 41 fallback events. Rescue fallback succeeded 4 times on seed 2, but most fallback events still had no ready rescue candidate.

3. Did RG-RALNS improve at beta_0 = 20?

Yes on the small three-seed benchmark. `Z_N` improved from 0.1191 to 0.1084 and TT improved from 107.67 to 87.67, while WSF and ZSR stayed at 0.283 and 0.889.

4. Did RG-RALNS remain clearly advantageous at beta_0 = 50/100?

Yes in this small benchmark. RG-RALNS has lower Z_N than Online-Legacy-ALNS and Lightweight RG Dispatch at beta_0 = 50 and beta_0 = 100.

5. Did runtime remain acceptable?

Yes. RG-RALNS runtime increased to about 0.044 seconds on the small benchmark, still far below Online-Legacy-ALNS at about 2.04 seconds.

6. Is the method ready for a slightly larger benchmark?

It is ready for a slightly larger diagnostic benchmark, not a final large-scale experiment. The beta_0 = 20 result is stronger than before, but seed 2 still exposes a rescue/fallback weakness.

7. What remains unresolved?

The main unresolved issue is seed 2: shortfall triggers are frequent, but current-time executable rescue opportunities are often absent or not present in the local plan's executable first step. The next tuning step should focus on affected-set readiness and local plan decoding/extraction, not on adding more baselines.

## 11. Output Files

Preserved output folders:

```text
/tmp/paper_a_rg_ralns_tuned_smoke
results/paper_a_rg_ralns_seed2_debug
results/paper_a_rg_ralns_tuning_beta20
results/paper_a_rg_ralns_tuning_beta50
results/paper_a_rg_ralns_tuned_beta_sensitivity
```

Files generated where applicable:

```text
results_summary.csv
per_instance_results.csv
mechanism_stats.csv
trigger_reason_counts.csv
objective_calibration.csv
beta_sensitivity_summary.csv
config_used.yaml
rg_ralns_event_trace_seed2.csv
operator_stats.csv
fallback_stats.csv
tuning_comparison.csv
```

Benchmark output folders are kept in the working directory for reproducibility but are not staged for commit.

## 12. Reproducibility and Git Information

Branch:

```text
codex/rg-ralns-performance-tuning
```

Commit hash after modification:

```text
9161f39 feat: tune RG-RALNS service-safe fallback and performance diagnostics
```

Push status:

```text
pushed to origin/codex/rg-ralns-performance-tuning via SSH
```

If push fails, recovery command:

```bash
git push -u origin codex/rg-ralns-performance-tuning
```
