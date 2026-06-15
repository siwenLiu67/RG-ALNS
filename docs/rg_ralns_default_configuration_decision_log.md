# RG-RALNS Default Configuration Decision Log

## 1. Goal

This log records the default-configuration decision after Stage 1.5. Stage 1.5 tested a capacity-aware current-time rescue priority intended to reduce seed 2 and seed 4 service failures. The mechanism remains useful as an experimental diagnostic switch, but the confirmation benchmark shows it should not be enabled by default for Paper A experiments.

The goal of this round is to restore the stronger Stage 1 / Stage 0.5 default behavior while keeping the Stage 1.5 capacity-aware rescue logic available for controlled ablation and future debugging.

## 2. Why Stage 1.5 Was Tested

Stage 1 expanded-small results showed that RG-RALNS had strong mean performance but still had service tail failures:

```text
seed 2: WSF = 0.85, ZSR = 0.667
seed 4: WSF = 3.20, ZSR = 0.667
```

Stage 1.5 therefore tested whether a minimal capacity-aware rescue priority could reduce machine-contention failures without changing online visibility, normalized objective evaluation, or the capped affected-set design.

## 3. Stage 1 vs Stage 1.5 Comparison

| Setting | Version | Z_N | TT | WSF | ZSR |
|---|---|---:|---:|---:|---:|
| beta_0=20 | Stage 1 default | 0.2672 | 74.60 | 0.810 | 0.867 |
| beta_0=20 | Stage 1.5 capacity priority | 0.2875 | 81.60 | 0.868 | 0.867 |
| beta_0=50 | Stage 1 default | 0.6037 | 74.60 | 0.810 | 0.867 |
| beta_0=50 | Stage 1.5 capacity priority | 0.6497 | 81.60 | 0.868 | 0.867 |

Stage 1.5 worsened normalized objective, total tardiness, and weighted service shortfall. It did not improve the seed-level service tail.

## 4. Why Stage 1.5 Is Not the Default

The Stage 1.5 mechanism was useful diagnostically, but the minimal current-time capacity priority did not solve the root cause. Debug traces indicated:

1. Many failed rescue events still had no currently executable rescue operation.
2. Seed 2 and seed 4 failures are more consistent with rescue-chain timing and local decode limitations than with a simple low-risk job occupying a rescue-critical machine at the current event.
3. Stronger capacity intervention risks idling machines or increasing TT unless it is implemented inside a bounded local decode / visible rescue-chain reservation model.

Therefore the Stage 1.5 capacity-aware priority is retained as an optional experiment switch, but the default Paper A RG-RALNS configuration disables it.

## 5. Default Configuration

The default RG-RALNS configuration is now:

```yaml
rg_ralns:
  capacity_rescue_enabled: false
  rescue_reservation_window: 1
  rescue_machine_pressure_threshold: 1
  low_risk_on_rescue_machine_penalty: true
```

The additional parameters remain in the config file for reproducibility, but they are inactive unless `capacity_rescue_enabled: true`.

The implementation also ensures that the Stage 1.5 rescue-chain/capacity ordering changes in local initial ordering, repair operators, and regret insertion cost are bypassed when `capacity_rescue_enabled` is false.

## 6. Optional Experimental Config

To re-enable the Stage 1.5 capacity-aware mechanism for ablation or diagnostics:

```yaml
rg_ralns:
  capacity_rescue_enabled: true
```

When enabled, the code can compute rescue-critical machine pressure and apply the soft priority signal in dispatch/fallback/local ordering. The diagnostics remain available through:

```text
rescue_failure_summary.csv
rescue_machine_contention_trace.csv
```

## 7. Confirmation Commands

Tests:

```bash
python3 -m pytest sl_isp_rg_rho_lns/tests/test_rg_ralns.py \
  sl_isp_rg_rho_lns/tests/test_paper_a_online_benchmark_protocol.py \
  sl_isp_rg_rho_lns/tests/test_paper_a_online_baselines.py -q
```

Py compile:

```bash
python3 -m py_compile \
  sl_isp_rg_rho_lns/src/algorithms/rg_ralns.py \
  sl_isp_rg_rho_lns/src/experiments/paper_a_online_protocol.py \
  scripts/run_paper_a_online_benchmark.py
```

Confirmation benchmark:

```bash
python3 scripts/run_paper_a_online_benchmark.py \
  --config configs/paper_a_online.yaml \
  --seeds 0 1 2 3 4 \
  --objective-beta 20 \
  --output results/paper_a_default_config_confirmation_beta20

python3 scripts/run_paper_a_online_benchmark.py \
  --config configs/paper_a_online.yaml \
  --seeds 0 1 2 3 4 \
  --objective-beta 50 \
  --output results/paper_a_default_config_confirmation_beta50

python3 scripts/run_paper_a_online_benchmark.py \
  --config configs/paper_a_online.yaml \
  --seeds 0 1 2 3 4 \
  --beta-sensitivity 1 5 10 20 50 100 \
  --output results/paper_a_default_config_confirmation_sensitivity
```

## 8. Validation Results

Test result:

```text
42 passed, 1 warning
```

The warning is the existing pytest config warning for an unknown `timeout` option.

Py compile result:

```text
passed
```

## 9. Confirmation Results: beta_0=20

| Algorithm | Z_N | TT | WSF | ZSR | Runtime |
|---|---:|---:|---:|---:|---:|
| RG-RALNS | 0.2672 | 74.60 | 0.810 | 0.867 | 0.0446 |
| Online-Legacy-ALNS | 0.5824 | 52.80 | 1.870 | 0.733 | 1.5793 |
| Lightweight RG Dispatch | 0.6176 | 134.60 | 1.758 | 0.733 | 0.0075 |
| EDD | 0.8805 | 65.80 | 3.464 | 0.667 | 0.0014 |

The reset restores the Stage 1 target level for beta_0=20.

## 10. Confirmation Results: beta_0=50

| Algorithm | Z_N | TT | WSF | ZSR | Runtime |
|---|---:|---:|---:|---:|---:|
| RG-RALNS | 0.6037 | 74.60 | 0.810 | 0.867 | 0.0456 |
| Online-Legacy-ALNS | 1.4099 | 52.80 | 1.870 | 0.733 | 1.5540 |
| Lightweight RG Dispatch | 1.4268 | 134.60 | 1.758 | 0.733 | 0.0075 |
| EDD | 2.1430 | 65.80 | 3.464 | 0.667 | 0.0013 |

The reset restores the Stage 1 target level for beta_0=50.

## 11. Sensitivity Result

| beta_0 | RG-RALNS Z_N | Online-Legacy-ALNS Z_N | Lightweight RG Z_N | RG-RALNS TT | RG-RALNS WSF | RG-RALNS ZSR |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.0540 | 0.0582 | 0.1052 | 74.60 | 0.810 | 0.867 |
| 5 | 0.0989 | 0.1686 | 0.2131 | 74.60 | 0.810 | 0.867 |
| 10 | 0.1550 | 0.3065 | 0.3479 | 74.60 | 0.810 | 0.867 |
| 20 | 0.2672 | 0.5824 | 0.6176 | 74.60 | 0.810 | 0.867 |
| 50 | 0.6037 | 1.4099 | 1.4268 | 74.60 | 0.810 | 0.867 |
| 100 | 1.1646 | 2.7892 | 2.7753 | 74.60 | 0.810 | 0.867 |

The normalized SLA-sensitive trend remains favorable after resetting the default configuration.

## 12. Recommended Default for Future Experiments

Use the default Paper A configuration with:

```yaml
capacity_rescue_enabled: false
```

This is the recommended default for future Stage 1 / Stage 2 experiments. Stage 1.5 capacity-aware rescue should be reported only as an optional diagnostic or ablation mechanism, not as the proposed main algorithm default.

## 13. Stage 2 Readiness

The default reset restores the stronger Stage 1 performance and preserves RG-RALNS's mean advantage over the current main online baselines. However, the seed 2 and seed 4 service-tail issue remains:

```text
seed 2: WSF = 0.85, ZSR = 0.667
seed 4: WSF = 3.20, ZSR = 0.667
```

RG-RALNS is suitable for continued expanded-small validation and controlled ablation, but final-scale Stage 2 should still wait for either:

1. a bounded capacity-aware local decode / visible rescue-chain reservation mechanism, or
2. a clear decision to report the remaining tail risk transparently as a limitation.

## 14. Git Metadata

Branch:

```text
codex/rg-ralns-default-config-reset
```

Commit hash and push status are recorded after commit/push.

Implementation commit:

```text
d1e3e37 chore: reset RG-RALNS default capacity rescue configuration
```

Push status:

```text
Pending when this metadata section was first written. Final push status is recorded in the task response.
```
