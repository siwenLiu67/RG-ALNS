# RG-RALNS Stage 1.5 Capacity Rescue Stabilization Log

## 1. Goal

This Stage 1.5 round diagnoses the seed 2 and seed 4 service degradation observed after the expanded-small Paper A online benchmark. The intended stabilization is minimal and configurable: add capacity-aware rescue diagnostics and priority signals without changing online visibility, normalized objective evaluation, baseline scope, or the capped local affected-set design.

## 2. Stage 1 Findings

Starting branch: `codex/paper-a-stage1-expanded-small`.

Stage 1 reference results:

| Setting | Algorithm | Z_N | TT | WSF | ZSR |
|---|---:|---:|---:|---:|---:|
| beta_0=20 | RG-RALNS | 0.2672 | 74.60 | 0.810 | 0.867 |
| beta_0=50 | RG-RALNS | 0.6037 | 74.60 | 0.810 | 0.867 |

Per-seed service issue before this round:

| Seed | WSF | ZSR |
|---:|---:|---:|
| 0 | 0.00 | 1.000 |
| 1 | 0.00 | 1.000 |
| 2 | 0.85 | 0.667 |
| 3 | 0.00 | 1.000 |
| 4 | 3.20 | 0.667 |

Stage 1 showed that seed 2 is not isolated. Seed 4 has a much larger shortfall, so final-scale experiments are not yet appropriate.

## 3. Seed 2 and Seed 4 Failure Comparison

Debug outputs:

```text
results/paper_a_stage15_seed2_debug
results/paper_a_stage15_seed4_debug
```

Final Stage 1.5 debug findings:

| Seed | WSF | ZSR | no_ready_operation_available | ordinary_fallback | rescue_fallback_success | A-set rescue success | rescue machine contention events |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 | 0.85 | 0.667 | 29 | 35 | 0 | 1 | 10 |
| 4 | 3.49 | 0.667 | 20 | 26 | 0 | 1 | 22 |

Seed 2 and seed 4 both show many fallback events where no currently executable rescue candidate exists. The new machine-contention trace confirms that rescue-critical machine pressure exists, but low-risk ready competition is not consistently the immediate bottleneck in early failed events. This suggests the remaining failure is not fully explained by simple current-time machine contention.

## 4. Capacity Contention Diagnosis

New output files:

```text
rescue_failure_summary.csv
rescue_machine_contention_trace.csv
```

The trace records rescue machine pressure, critical machines, rescue-ready operations on critical machines, low-risk competitors, selected decisions, fallback reasons, and whether contention was present. The main diagnosis is:

1. Capacity contention exists in both outlier seeds.
2. The most damaging events are still often `no_ready_operation_available`.
3. Mandatory/cover precursor jobs enter `A(t)` but are not selected often enough to eliminate final shortfall.
4. A hard reservation-style intervention was not retained because it risks idle capacity and did not improve the measured outliers.

The stronger remaining suspicion is that RG-RALNS needs a capacity-aware local decode or rescue-chain reservation over visible operations, not only a current-time dispatch priority.

## 5. Implemented Mechanism

Changed files:

```text
sl_isp_rg_rho_lns/src/algorithms/rg_ralns.py
sl_isp_rg_rho_lns/src/experiments/paper_a_online_protocol.py
configs/paper_a_online.yaml
sl_isp_rg_rho_lns/tests/test_rg_ralns.py
sl_isp_rg_rho_lns/tests/test_paper_a_online_benchmark_protocol.py
```

Implemented changes:

1. Added configurable capacity rescue parameters:

```yaml
rg_ralns:
  capacity_rescue_enabled: true
  rescue_reservation_window: 1
  rescue_machine_pressure_threshold: 1
  low_risk_on_rescue_machine_penalty: true
```

2. Added rescue machine pressure diagnostics:

```text
_rescue_machine_pressure
_rescue_critical_machines
```

3. Added capacity-aware priority signals to dispatch, rescue fallback, local initial ordering, and repair insertion order. The final retained implementation treats the capacity signal as a tie-break / soft penalty rather than a hard machine-idling rule.

4. Extended event trace and benchmark outputs with:

```text
rescue_machine_contention_events
rescue_failure_summary.csv
rescue_machine_contention_trace.csv
```

The implementation uses only visible jobs, current state, ongoing operations, machine states, and entity-level diagnostics. It does not inspect future unreleased job-level details.

## 6. Regression Tests

Added regression tests in:

```text
sl_isp_rg_rho_lns/tests/test_rg_ralns.py
```

Coverage added:

1. Rescue-critical machine pressure is detected for near-ready rescue chains.
2. Rescue operation is selected before a low-risk competitor on a rescue-critical machine.
3. Capacity rescue does not idle a machine when no rescue operation is executable.
4. Capacity pressure respects online visibility and does not use future job details.
5. `A(t)` remains capped under capacity-rescue scenarios.

## 7. Validation Commands

Tests:

```bash
python3 -m pytest sl_isp_rg_rho_lns/tests/test_rg_ralns.py \
  sl_isp_rg_rho_lns/tests/test_paper_a_online_benchmark_protocol.py \
  sl_isp_rg_rho_lns/tests/test_paper_a_online_baselines.py -q
```

Result:

```text
38 passed, 1 warning
```

Py compile:

```bash
python3 -m py_compile \
  sl_isp_rg_rho_lns/src/algorithms/rg_ralns.py \
  sl_isp_rg_rho_lns/src/experiments/paper_a_online_protocol.py \
  scripts/run_paper_a_online_benchmark.py
```

Result: passed.

Benchmarks:

```bash
python3 scripts/run_paper_a_online_benchmark.py --config configs/paper_a_online.yaml \
  --seeds 2 --objective-beta 20 --rg-debug-trace \
  --output results/paper_a_stage15_seed2_debug

python3 scripts/run_paper_a_online_benchmark.py --config configs/paper_a_online.yaml \
  --seeds 4 --objective-beta 20 --rg-debug-trace \
  --output results/paper_a_stage15_seed4_debug

python3 scripts/run_paper_a_online_benchmark.py --config configs/paper_a_online.yaml \
  --seeds 0 1 2 3 4 --objective-beta 20 \
  --output results/paper_a_stage15_beta20

python3 scripts/run_paper_a_online_benchmark.py --config configs/paper_a_online.yaml \
  --seeds 0 1 2 3 4 --objective-beta 50 \
  --output results/paper_a_stage15_beta50

python3 scripts/run_paper_a_online_benchmark.py --config configs/paper_a_online.yaml \
  --seeds 0 1 2 3 4 --beta-sensitivity 1 5 10 20 50 100 \
  --output results/paper_a_stage15_beta_sensitivity
```

## 8. beta_0=20 Results

| Algorithm | Z_N | TT | WSF | ZSR | Runtime |
|---|---:|---:|---:|---:|---:|
| RG-RALNS | 0.2875 | 81.60 | 0.868 | 0.867 | 0.0720 |
| Online-Legacy-ALNS | 0.5824 | 52.80 | 1.870 | 0.733 | 1.5619 |
| Lightweight RG Dispatch | 0.6176 | 134.60 | 1.758 | 0.733 | 0.0081 |
| EDD | 0.8805 | 65.80 | 3.464 | 0.667 | 0.0013 |

RG-RALNS remains better than the main online baselines in mean normalized objective and service metrics, but the Stage 1.5 capacity-aware changes did not improve its own Stage 1 reference.

## 9. beta_0=50 Results

| Algorithm | Z_N | TT | WSF | ZSR | Runtime |
|---|---:|---:|---:|---:|---:|
| RG-RALNS | 0.6497 | 81.60 | 0.868 | 0.867 | 0.0728 |
| Online-Legacy-ALNS | 1.4099 | 52.80 | 1.870 | 0.733 | 1.5778 |
| Lightweight RG Dispatch | 1.4268 | 134.60 | 1.758 | 0.733 | 0.0080 |
| EDD | 2.1430 | 65.80 | 3.464 | 0.667 | 0.0013 |

The SLA-sensitive advantage remains clear at beta_0=50, but the seed-level service outliers remain.

## 10. Per-seed WSF/ZSR Before and After

| Seed | Stage 1 WSF | Stage 1 ZSR | Stage 1.5 WSF | Stage 1.5 ZSR |
|---:|---:|---:|---:|---:|
| 0 | 0.00 | 1.000 | 0.00 | 1.000 |
| 1 | 0.00 | 1.000 | 0.00 | 1.000 |
| 2 | 0.85 | 0.667 | 0.85 | 0.667 |
| 3 | 0.00 | 1.000 | 0.00 | 1.000 |
| 4 | 3.20 | 0.667 | 3.49 | 0.667 |

Seed 2 did not improve. Seed 4 did not improve and became slightly worse in WSF under the final retained capacity-aware priority variant.

## 11. Mechanism Diagnostics

RG-RALNS mechanism statistics under beta_0=20:

| Seed | trigger_ratio | avg_A_size | max_A_size | fallback | local extraction | A-set rescue | ordinary fallback | contention events |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 0.265 | 5.96 | 8 | 6 | 21 | 3 | 3 | 23 |
| 1 | 0.136 | 7.07 | 8 | 1 | 13 | 1 | 0 | 15 |
| 2 | 0.614 | 3.32 | 7 | 36 | 26 | 1 | 35 | 10 |
| 3 | 0.228 | 4.62 | 8 | 4 | 17 | 0 | 4 | 8 |
| 4 | 0.553 | 3.04 | 8 | 27 | 30 | 1 | 26 | 22 |

`A(t)` remains local and capped. The problematic seeds have high trigger ratios and high fallback counts, especially ordinary fallback and no-ready-operation events.

## 12. Beta Sensitivity

| beta_0 | RG-RALNS Z_N | Online-Legacy-ALNS Z_N | Lightweight RG Z_N | RG-RALNS WSF | RG-RALNS ZSR |
|---:|---:|---:|---:|---:|---:|
| 1 | 0.0581 | 0.0582 | 0.1052 | 0.868 | 0.867 |
| 5 | 0.1064 | 0.1686 | 0.2131 | 0.868 | 0.867 |
| 10 | 0.1668 | 0.3065 | 0.3479 | 0.868 | 0.867 |
| 20 | 0.2875 | 0.5824 | 0.6176 | 0.868 | 0.867 |
| 50 | 0.6497 | 1.4099 | 1.4268 | 0.868 | 0.867 |
| 100 | 1.2533 | 2.7892 | 2.7753 | 0.868 | 0.867 |

The normalized SLA-sensitive trend remains favorable: RG-RALNS improves relative to the baselines as beta_0 increases.

## 13. Readiness Assessment

RG-RALNS is still not ready for Stage 2 final-style main benchmarking. It is competitive in mean normalized objective and much faster than Online-Legacy-ALNS, but the service tail remains unstable.

Capacity-aware priority diagnostics were useful, but the minimal stabilization did not reduce the outlier WSF/ZSR failures. The next stabilization should target capacity-aware local decode or explicit visible rescue-chain reservation inside the local plan, while preserving current-time commit and online visibility.

## 14. Remaining Risks

1. `Q_rec` remains optimistic because it uses a lower-bound processing estimate and does not reserve capacity for visible rescue chains.
2. Local ALNS can include precursor jobs but still fail to advance them early enough.
3. Fallback often occurs when there is no currently executable rescue operation, so current-time dispatch cannot recover from earlier chain delays.
4. Stronger capacity reservation could reduce WSF but risks increasing TT/runtime or idling machines unless carefully bounded.

## 15. Git Metadata

Branch:

```text
codex/rg-ralns-stage15-capacity-rescue
```

Implementation commit:

```text
247570c fix: add RG-RALNS capacity-aware rescue stabilization
```

Push status:

```text
Succeeded. Branch pushed to origin/codex/rg-ralns-stage15-capacity-rescue via SSH.
```
