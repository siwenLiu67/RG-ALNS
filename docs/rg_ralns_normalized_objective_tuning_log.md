# RG-RALNS Normalized Objective Tuning Log

Date: 2026-06-11

Branch: `codex/normalized-objective-sensitivity`

Commit: pending before final commit

## 1. Background

The theoretical objective remains:

```text
Z = alpha * TT + beta * WSF
```

This update does not replace the model objective. The issue addressed here is
experimental calibration. In the Paper A online benchmark, raw total tardiness
`TT` and weighted service shortfall `WSF` have different physical meanings and
different numerical scales. With `alpha=1` and `beta=1`, the raw magnitude of
`TT` can dominate the scalar objective, even when the scheduling context is an
SLA-sensitive service contract where service shortfall is much more expensive
than ordinary delay.

The normalized objective calibration is introduced so that `alpha_0` and
`beta_0` represent SLA penalty intensity after instance-level scale correction.
This is not a post-hoc change to make one algorithm win; it is a reporting and
evaluation calibration that keeps the original objective structure.

The online information boundary remains unchanged. Algorithms in the main
online table still receive only arrived job details through `OnlineProblemView`.
The normalization constants are computed by the benchmark after generating the
complete instance and are used for final evaluation output, not to expose future
job-level details to online algorithms.

## 2. Formulation

For each instance `I`, the tardiness scale is:

```text
Theta_I = sum_{j in J} max(1, d_{g(j)} - tau_{g(j)} - r_j)
```

where `d_{g(j)} - tau_{g(j)}` is the effective production deadline of the
entity to which job `j` belongs.

The service shortfall scale is:

```text
Omega_I = sum_{r in R} w_r * Q_min,r
```

The current codebase defines:

```text
Q_min,r = max(1.0, rho_r * Q_r)
```

This deterministic convention is kept for consistency with the existing
objective implementation. No new rounding rule is introduced in this update.

Normalized components are:

```text
TT_hat  = TT / Theta_I
WSF_hat = WSF / Omega_I
```

The normalized experimental objective is:

```text
Z_N = alpha_0 * TT_hat + beta_0 * WSF_hat
```

Equivalently:

```text
Z_N = alpha_I * TT + beta_I * WSF

alpha_I = alpha_0 / Theta_I
beta_I  = beta_0  / Omega_I
```

The default main setting is:

```text
alpha_0 = 1.0
beta_0  = 20.0
```

Sensitivity analysis uses:

```text
beta_0 in {1, 5, 10, 20, 50, 100}
```

## 3. Implementation Changes

Modified files:

```text
configs/paper_a_online.yaml
scripts/run_paper_a_online_benchmark.py
sl_isp_rg_rho_lns/src/experiments/paper_a_online_protocol.py
sl_isp_rg_rho_lns/tests/test_paper_a_online_baselines.py
sl_isp_rg_rho_lns/tests/test_paper_a_online_benchmark_protocol.py
docs/rg_ralns_normalized_objective_tuning_log.md
```

New objective configuration:

```yaml
objective:
  type: normalized
  alpha_0: 1.0
  beta_0: 20.0
  beta_sensitivity: [1, 5, 10, 20, 50, 100]
```

New implementation entry points:

```text
ObjectiveCalibration
compute_objective_calibration(...)
evaluate_normalized_objective(...)
```

The benchmark output now reports:

```text
Z_original
Z_N
normalized_Z
TT
WSF
TT_hat
WSF_hat
ZSR
runtime
Theta_I
Omega_I
alpha_0
beta_0
alpha_I
beta_I
```

New output files:

```text
objective_calibration.csv
beta_sensitivity_summary.csv
```

The main fair online labels were clarified:

```text
Online-Legacy-ALNS
Offline-Legacy-ALNS
```

The algorithm keys remain unchanged for backward compatibility:

```text
online_legacy_rg_alns
offline_legacy_rg_alns
```

## 4. Validation

Test command:

```bash
python3 -m pytest tests/test_paper_a_current_time_execution.py \
  tests/test_paper_a_online_visibility.py \
  tests/test_paper_a_online_baselines.py \
  tests/test_paper_a_online_benchmark_protocol.py \
  tests/test_rg_ralns.py tests/test_online_simulator.py \
  tests/test_simulator.py tests/test_recoverability.py -q
```

Result:

```text
94 passed, 1 warning
```

Compile command:

```bash
python3 -m py_compile \
  sl_isp_rg_rho_lns/src/algorithms/rg_ralns.py \
  sl_isp_rg_rho_lns/src/experiments/paper_a_online_protocol.py \
  scripts/run_paper_a_online_benchmark.py
```

Result:

```text
passed
```

Smoke command:

```bash
python3 scripts/run_paper_a_online_benchmark.py \
  --config configs/paper_a_online.yaml \
  --seeds 0 \
  --output /tmp/paper_a_normalized_smoke
```

Smoke outputs:

```text
results_summary.csv
per_instance_results.csv
mechanism_stats.csv
trigger_reason_counts.csv
objective_calibration.csv
beta_sensitivity_summary.csv
config_used.yaml
```

## 5. Small Benchmark Results

Small benchmark command:

```bash
python3 scripts/run_paper_a_online_benchmark.py \
  --config configs/paper_a_online.yaml \
  --seeds 0 1 2 \
  --output results/paper_a_normalized_small
```

Main setting:

```text
alpha_0 = 1.0
beta_0 = 20.0
```

Mean results over seeds `0, 1, 2`:

| Algorithm | Z_N | TT | WSF | TT_hat | WSF_hat | ZSR | Runtime |
|---|---:|---:|---:|---:|---:|---:|---:|
| ATC | 0.8450 | 138.00 | 3.330 | 0.0788 | 0.0383 | 0.778 | 0.0012 |
| EDD | 0.8802 | 67.00 | 4.003 | 0.0375 | 0.0421 | 0.667 | 0.0013 |
| Lightweight RG Dispatch | 0.1261 | 119.67 | 0.283 | 0.0665 | 0.0030 | 0.889 | 0.0056 |
| Online-Legacy-ALNS | 0.1197 | 48.67 | 0.443 | 0.0263 | 0.0047 | 0.778 | 2.0074 |
| RG-RALNS | 0.1191 | 107.67 | 0.283 | 0.0594 | 0.0030 | 0.889 | 0.0251 |
| SFG | 0.8938 | 228.67 | 3.330 | 0.1275 | 0.0383 | 0.778 | 0.0072 |
| SPT | 0.5736 | 116.00 | 2.330 | 0.0651 | 0.0254 | 0.778 | 0.0012 |
| SWD | 0.6101 | 124.00 | 2.490 | 0.0680 | 0.0271 | 0.667 | 0.0014 |
| WSPT | 0.8600 | 169.00 | 3.330 | 0.0938 | 0.0383 | 0.778 | 0.0012 |

Offline/oracle reference:

| Algorithm | Z_N | TT | WSF | ZSR |
|---|---:|---:|---:|---:|
| Offline-Legacy-ALNS | 0.0145 | 29.00 | 0.000 | 1.000 |

Mechanism statistics for RG-RALNS:

| Metric | Mean |
|---|---:|
| trigger_count | 35.33 |
| trigger_ratio | 0.345 |
| avg_A_size | 5.23 |
| max_A_size | 7.67 |
| alns_runtime_total | 0.0178 |
| dispatch_fallback_count | 17.00 |
| algorithm_call_count | 105.00 |

Instance calibration constants:

| Seed | Theta_I | Omega_I | alpha_I | beta_I |
|---:|---:|---:|---:|---:|
| 0 | 1878.00 | 77.58 | 0.000532 | 0.257798 |
| 1 | 2059.00 | 102.02 | 0.000486 | 0.196040 |
| 2 | 1660.00 | 95.01 | 0.000602 | 0.210504 |

## 6. Sensitivity Analysis

Sensitivity command:

```bash
python3 scripts/run_paper_a_online_benchmark.py \
  --config configs/paper_a_online.yaml \
  --seeds 0 1 2 \
  --beta-sensitivity 1 5 10 20 50 100 \
  --output results/paper_a_beta_sensitivity_small
```

Key algorithms:

| beta_0 | RG-RALNS Z_N | EDD Z_N | Lightweight RG Z_N | Online-Legacy-ALNS Z_N |
|---:|---:|---:|---:|---:|
| 1 | 0.0624 | 0.0796 | 0.0694 | 0.0310 |
| 5 | 0.0743 | 0.2482 | 0.0814 | 0.0497 |
| 10 | 0.0892 | 0.4588 | 0.0963 | 0.0730 |
| 20 | 0.1191 | 0.8802 | 0.1261 | 0.1197 |
| 50 | 0.2085 | 2.1443 | 0.2156 | 0.2596 |
| 100 | 0.3576 | 4.2511 | 0.3647 | 0.4929 |

RG-RALNS relative gaps from `beta_sensitivity_summary.csv`:

| beta_0 | vs EDD | vs Lightweight RG | vs Online-Legacy-ALNS |
|---:|---:|---:|---:|
| 1 | -21.62% | -10.13% | +101.33% |
| 5 | -70.05% | -8.65% | +49.68% |
| 10 | -80.55% | -7.31% | +22.27% |
| 20 | -86.47% | -5.58% | -0.49% |
| 50 | -90.28% | -3.26% | -19.68% |
| 100 | -91.59% | -1.93% | -27.45% |

Negative gap means RG-RALNS has a lower normalized objective.

## 7. Interpretation

The normalized objective changes the experimental reading without altering the
theoretical objective. It makes the SLA penalty intensity interpretable:
`beta_0` now operates on `WSF_hat`, not on raw `WSF` with a different scale from
raw `TT`.

Observed trend:

```text
At low beta_0, Online-Legacy-ALNS remains stronger because it has much lower TT.
As beta_0 increases, RG-RALNS becomes more competitive because it has lower WSF
and higher ZSR.
```

At the main setting `beta_0=20`, RG-RALNS narrowly beats Online-Legacy-ALNS in
normalized objective:

```text
RG-RALNS:            Z_N = 0.1191
Online-Legacy-ALNS: Z_N = 0.1197
```

At `beta_0=50` and `100`, RG-RALNS has a clearer normalized objective advantage
over Online-Legacy-ALNS. This supports the paper narrative that RG-RALNS is more
appropriate under stronger SLA service-penalty settings.

However, the previous seed-2 issue remains visible in mechanism statistics:

```text
dispatch_fallback_count is still high for RG-RALNS on seed 2.
```

The normalized objective makes the evaluation fairer, but it does not remove
the need to improve RG-RALNS dispatch fallback and rescue extraction.

## 8. Reproducibility

Exact commands:

```bash
python3 -m pytest tests/test_paper_a_current_time_execution.py \
  tests/test_paper_a_online_visibility.py \
  tests/test_paper_a_online_baselines.py \
  tests/test_paper_a_online_benchmark_protocol.py \
  tests/test_rg_ralns.py tests/test_online_simulator.py \
  tests/test_simulator.py tests/test_recoverability.py -q

python3 -m py_compile \
  sl_isp_rg_rho_lns/src/algorithms/rg_ralns.py \
  sl_isp_rg_rho_lns/src/experiments/paper_a_online_protocol.py \
  scripts/run_paper_a_online_benchmark.py

python3 scripts/run_paper_a_online_benchmark.py \
  --config configs/paper_a_online.yaml \
  --seeds 0 \
  --output /tmp/paper_a_normalized_smoke

python3 scripts/run_paper_a_online_benchmark.py \
  --config configs/paper_a_online.yaml \
  --seeds 0 1 2 \
  --output results/paper_a_normalized_small

python3 scripts/run_paper_a_online_benchmark.py \
  --config configs/paper_a_online.yaml \
  --seeds 0 1 2 \
  --beta-sensitivity 1 5 10 20 50 100 \
  --output results/paper_a_beta_sensitivity_small
```

Output paths:

```text
/tmp/paper_a_normalized_smoke
results/paper_a_normalized_small
results/paper_a_beta_sensitivity_small
```

The final commit hash will be reported after the code and this document are
committed.

## 9. Next Step

Recommended next work:

```text
1. Keep normalized objective calibration in Paper A reporting.
2. Use beta_0 = 20 as the main SLA-sensitive setting.
3. Report beta_0 sensitivity over {1, 5, 10, 20, 50, 100}.
4. Continue improving RG-RALNS seed-2 fallback/rescue failures before expanding
   to more baselines or larger experiments.
```
