# Paper A RG-RALNS Progress Snapshot

Date: 2026-06-10

Branch: `codex/paper-a-online-benchmark`

## 1. Current Position

Paper A now uses the following main algorithm口径:

```text
Recoverability-Guided Reactive ALNS, RG-RALNS
```

The main experimental protocol is the Paper A online event-driven protocol:

```text
same dynamic-arrival instance
same event-driven simulator
same online visibility
same current-time execution policy
same final global objective evaluation
```

At each event time, main-table algorithms observe only arrived jobs and current
state. Future jobs are hidden at the job level. For RG-RALNS, future jobs may
only enter recoverability diagnosis through entity-level aggregate quantity
buffer `Q_future,r(t)`.

## 2. Implemented Paper A Online Protocol

The benchmark protocol is implemented separately from legacy pilot experiments.

Main runner:

```text
scripts/run_paper_a_online_benchmark.py
```

Protocol module:

```text
sl_isp_rg_rho_lns/src/experiments/paper_a_online_protocol.py
```

Current main online table includes:

```text
EDD
SPT
WSPT
ATC
SWD
SFG
Lightweight RG Dispatch
Online-Legacy-RG-ALNS
RG-RALNS
```

Offline/oracle reference is separated as:

```text
Offline-Legacy-RG-ALNS
```

This offline/oracle algorithm is not part of the main fair online comparison.

## 3. Current RG-RALNS Implementation

RG-RALNS is implemented in:

```text
sl_isp_rg_rho_lns/src/algorithms/rg_ralns.py
```

The current version contains:

```text
online information view
recoverability diagnosis
deterministic trigger
affected-set construction with H_A cap
lightweight RG dispatch fallback
local RG-ALNS skeleton
current-time execution extraction
mechanism statistics
```

Recoverability diagnosis computes:

```text
Q_sec,r(t)
Q_rem,r(t)
Q_future,r(t)
Q_rec,r(t)
Q_cover,r(t)
U_info,r(t)
mandatory rescue jobs
heuristic service cover
entity recoverability class
```

Affected set `A(t)` is restricted to visible unfinished jobs and capped by
`H_A`. Future jobs cannot enter `A(t)`.

## 4. Latest Tuning Changes

The latest tuning round targeted this problem:

```text
Previous RG-RALNS had strong service protection:
WSF = 0
ZSR = 1.0

But it over-sacrificed TT/Z.
```

Implemented tuning changes:

```text
acceptance_mode = service_safe_z
bottleneck_trigger_mode = normal / strict
repair_service_safe_edd_spt
CLI overrides for small parameter sweeps
trigger_ratio denominator correction
```

### Acceptance

The new `service_safe_z` mode keeps the service safety floor:

```text
reject if U_info increases
reject if incumbent WSF is already zero and candidate increases WSF
```

When both incumbent and candidate are service-safe:

```text
compare Z first
then TT
then disruption
```

### Repair

The new service-safe repair has two stages:

```text
1. restore mandatory and cover jobs first
2. order remaining jobs by TT-oriented EDD/SPT logic
```

### Bottleneck Trigger and A(t)

`bottleneck_trigger_mode` supports:

```text
normal
strict
```

The code default remains `strict`, but the current benchmark config uses
`normal` after the small sweep because it gave the best Z/TT trade-off on the
current 20-job validation set.

Current config:

```text
H_A = 8
N_A = 20
acceptance_mode = service_safe_z
bottleneck_trigger_mode = normal
```

## 5. Small Benchmark Results

Benchmark command:

```bash
python3 scripts/run_paper_a_online_benchmark.py \
  --config configs/paper_a_online.yaml \
  --seeds 0 1 2 \
  --output results/paper_a_rg_ralns_tuned_small
```

Mean results over seeds `0, 1, 2`:

| Algorithm | Z | TT | WSF | ZSR | Runtime |
|---|---:|---:|---:|---:|---:|
| EDD | 71.00 | 67.00 | 4.003 | 0.667 | 0.0013 |
| SPT | 118.33 | 116.00 | 2.330 | 0.778 | 0.0012 |
| Lightweight RG Dispatch | 119.95 | 119.67 | 0.283 | 0.889 | 0.0057 |
| Online-Legacy-RG-ALNS | 49.11 | 48.67 | 0.443 | 0.778 | 1.9347 |
| RG-RALNS tuned | 107.95 | 107.67 | 0.283 | 0.889 | 0.0247 |
| Offline-Legacy-RG-ALNS | 29.00 | 29.00 | 0.000 | 1.000 | 4.5237 |

Compared with the previous RG-RALNS validation result:

| Metric | Previous RG-RALNS | Tuned RG-RALNS | Change |
|---|---:|---:|---:|
| Z | 129.00 | 107.95 | -21.05 |
| TT | 129.00 | 107.67 | -21.33 |
| WSF | 0.000 | 0.283 | +0.283 |
| ZSR | 1.000 | 0.889 | -0.111 |
| Runtime | 0.0146 | 0.0247 | +0.0102 |

Interpretation:

```text
The tuning successfully reduced TT/Z, but it did not fully preserve the earlier
WSF=0 and ZSR=1.0 advantage.
```

## 6. Mechanism Statistics

RG-RALNS tuned mechanism averages:

| Metric | Mean |
|---|---:|
| trigger_count | 35.33 |
| trigger_ratio | 0.345 |
| avg_A_size | 5.23 |
| max_A_size | 7.67 |
| alns_runtime_total | 0.0177 |
| dispatch_fallback_count | 17.00 |

The `trigger_ratio` is now computed as:

```text
trigger_count / algorithm_call_count
```

This avoids ratios above 1 when the simulator calls the algorithm multiple
times within the same event time during a dispatch cycle.

## 7. Online-Legacy-RG-ALNS Status

`Online-Legacy-RG-ALNS` is not a new independent algorithm file. It is the
legacy `run_rg_alns` algorithm executed under Paper A online visibility.

Creation path:

```text
paper_a_online_protocol.py -> create_paper_a_algorithm -> run_rg_alns
```

Legacy implementation:

```text
sl_isp_rg_rho_lns/src/algorithms/rg_rho_lns_fast.py
```

Important distinction:

```text
Online-Legacy-RG-ALNS:
  online_visibility = True
  receives OnlineProblemView
  sees only arrived jobs

Offline-Legacy-RG-ALNS:
  online_visibility = False
  receives full instance
  used only as offline/oracle reference
```

In the current small benchmark, Online-Legacy-RG-ALNS has strong `TT/Z`, but
weaker service performance than RG-RALNS:

```text
Online-Legacy-RG-ALNS:
Z = 49.11
TT = 48.67
WSF = 0.443
ZSR = 0.778
```

## 8. Current Judgment

Current state:

```text
Do not expand more baselines yet.
Do not run large-scale experiments yet.
Continue improving RG-RALNS itself.
```

Reason:

```text
RG-RALNS has a clear service-recoverability mechanism, but the latest tuning
introduced a service trade-off. The next step should repair this trade-off
before the algorithm is promoted to larger benchmark runs.
```

The most suspicious case is seed `2`:

```text
RG-RALNS tuned on seed 2:
Z = 154.85
TT = 154
WSF = 0.85
ZSR = 0.667
dispatch_fallback_count = 41
```

This suggests that the next debugging target should be:

```text
shortfall-triggered events where local ALNS fails to extract a rescue operation
and falls back to lightweight dispatch.
```

## 9. Recommended Next Step

Next work should focus on seed `2` diagnostics:

```text
1. log shortfall events where dispatch_fallback_count increases
2. inspect affected set A(t) at those events
3. check whether mandatory / cover jobs are present and ready
4. check why local schedule extraction returns no feasible operation
5. adjust repair or fallback so service-critical ready operations are not lost
```

The goal is:

```text
keep most of the TT/Z improvement
recover WSF close to 0 and ZSR close to 1.0
```

## 10. Verification Snapshot

Latest verification commands:

```bash
python3 -m pytest tests/test_rg_ralns.py \
  tests/test_paper_a_current_time_execution.py \
  tests/test_paper_a_online_visibility.py \
  tests/test_paper_a_online_benchmark_protocol.py -q

python3 -m py_compile \
  sl_isp_rg_rho_lns/src/algorithms/rg_ralns.py \
  sl_isp_rg_rho_lns/src/experiments/paper_a_online_protocol.py \
  scripts/run_paper_a_online_benchmark.py

python3 scripts/run_paper_a_online_benchmark.py \
  --config configs/paper_a_online.yaml \
  --seeds 0 \
  --output /tmp/paper_a_rg_ralns_tuned_smoke

python3 scripts/run_paper_a_online_benchmark.py \
  --config configs/paper_a_online.yaml \
  --seeds 0 1 2 \
  --output results/paper_a_rg_ralns_tuned_small
```

Observed test result:

```text
23 passed, 1 warning
```
