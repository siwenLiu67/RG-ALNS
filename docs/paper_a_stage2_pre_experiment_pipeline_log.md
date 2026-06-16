# Paper A Stage 2-Pre Experiment Pipeline Log

## 1. Goal

This Stage 2-pre task prepares a reproducible, paper-ready experiment workflow for Paper A without changing the RG-RALNS algorithm, the Paper A online visibility protocol, or the normalized objective definition.

The goal is to support the formal experimental section with:

- main online comparison;
- beta sensitivity analysis;
- ablation planning;
- mechanism analysis;
- scalability summaries;
- seed/service robustness summaries;
- statistical summaries and confidence intervals.

This is not a final paper-scale benchmark run.

## 2. Starting Branch and Commit

- Starting branch: `codex/rg-ralns-default-config-reset`
- New branch: `codex/paper-a-stage2-pre-experiment-pipeline`
- Starting commit: `4a48c8d089b1373ec03218729c4282437eb0715d`

## 3. Finalized Default RG-RALNS Configuration

The Stage 1.5 capacity-aware rescue mechanism remains available as an optional experimental switch, but it is not adopted by default.

Current default in `configs/paper_a_online.yaml`:

```yaml
rg_ralns:
  capacity_rescue_enabled: false
  rescue_reservation_window: 1
  rescue_machine_pressure_threshold: 1
  low_risk_on_rescue_machine_penalty: true
```

The important default is:

```yaml
capacity_rescue_enabled: false
```

## 4. Formal Experiment Modules

### Main Online Comparison

Required main-table algorithms:

- `EDD`
- `SPT`
- `WSPT`
- `ATC`
- `SWD`
- `SFG`
- `Lightweight RG Dispatch`
- `Online-Legacy-ALNS`
- `RG-RALNS`

Required metrics:

- `Z_N`
- `TT`
- `WSF`
- `TT_hat`
- `WSF_hat`
- `ZSR`
- `runtime`

The new summarizer computes mean, standard deviation, standard error, 95% confidence interval, best count by `Z_N`, rank by mean `Z_N`, and average per-instance rank.

### Beta Sensitivity

Required beta values:

```text
beta_0 in {1, 5, 10, 20, 50, 100}
```

The pipeline can use all main algorithms or a reduced set:

- `RG-RALNS`
- `Online-Legacy-ALNS`
- `Lightweight RG Dispatch`
- `EDD`

The generated beta table includes relative improvement columns against:

- `Online-Legacy-ALNS`
- `Lightweight RG Dispatch`
- `EDD`

### Ablation Design

Current implementability:

| Variant | Implementable Now | Recommended |
| --- | --- | --- |
| Full RG-RALNS default | yes | yes |
| w/o recoverability trigger | no | yes, requires code switch |
| w/o service-safe extraction | no | yes, requires code switch |
| w/o rescue-chain precursor priority | no | maybe, diagnostic value |
| w/o service-safe acceptance | yes | yes |
| w/o local ALNS | yes, use Lightweight RG Dispatch | yes |
| capacity_rescue_enabled=true | yes | diagnostic only, not default |

The suite script writes `ablation_plan.csv` for the current implementability state. It does not fake unavailable ablation results.

### Mechanism Analysis

Required mechanism fields are supported by the existing benchmark output and summarized by the new table generator:

- `trigger_count`
- `trigger_ratio`
- `avg_A_size`
- `max_A_size`
- `alns_runtime_total`
- `dispatch_fallback_count`
- `rescue_fallback_success_count`
- `ordinary_fallback_count`
- `local_extraction_success_count`
- `affected_set_rescue_success_count`
- `rescue_machine_contention_events`

Purpose: show that RG-RALNS is a risk-triggered local ALNS rather than every-event full global rescheduling.

### Scalability Design

The suite script defines scale presets:

| Scale | Jobs | Machines | Entities |
| --- | ---: | ---: | ---: |
| small | 20 | 5 | 3 |
| medium | 50 | 8 | 5 |
| large | 100 | 12 | 8 |
| xlarge | 200 | 16 | 12 |

The table generator can summarize runtime and quality by instance/scale label. Large-scale runs were not executed in this task.

### Robustness Design

The seed robustness table reports:

- `seed`
- `algorithm`
- `Z_N`
- `TT`
- `WSF`
- `ZSR`
- `runtime`
- `is_service_outlier`

Default service outlier rule:

```text
is_service_outlier = WSF > 0 or ZSR < 1
```

Thresholds are configurable in the summarizer CLI.

## 5. Scripts and Configs Added

### `scripts/run_paper_a_experiment_suite.py`

Purpose: thin suite wrapper around the existing Paper A online benchmark runner.

Supported suites:

- `pilot`
- `main`
- `beta_sensitivity`
- `ablation`
- `mechanism`
- `scalability`
- `robustness`

Key features:

- normalizes algorithm aliases such as `RG_RALNS`, `Online_Legacy_ALNS`, and `Lightweight_RG_Dispatch`;
- writes `suite_metadata.yaml` with branch, commit, timestamp, seeds, algorithms, and overrides;
- keeps `offline_oracle` algorithms out of main online suite runs;
- supports `--dry-run-plan` for planning metadata without benchmark execution;
- supports scale presets without modifying the source config.

### `scripts/summarize_paper_a_results.py`

Purpose: read benchmark output folders and generate paper-ready CSV tables.

Generated files:

- `table_main_comparison.csv`
- `table_beta_sensitivity.csv`
- `table_ablation.csv`
- `table_mechanism_stats.csv`
- `table_scalability.csv`
- `table_seed_robustness.csv`
- `table_statistical_tests.csv`
- `missing_inputs.csv`

If an input is missing, the script writes an explicit missing-input row instead of failing silently.

## 6. Statistical Summary Design

The table generator computes:

- mean;
- standard deviation;
- standard error;
- 95% confidence interval;
- relative improvement;
- paired differences where per-instance pairing is available.

Paired comparisons are currently generated for:

- `RG-RALNS` vs `Online-Legacy-ALNS`;
- `RG-RALNS` vs `Lightweight RG Dispatch`;
- `RG-RALNS` vs `EDD`.

If SciPy is available, paired t-test and Wilcoxon signed-rank p-values are attempted. If SciPy is unavailable or the sample is degenerate, the descriptive statistics are still generated.

## 7. Pilot Validation Commands

Tests:

```bash
python3 -m pytest sl_isp_rg_rho_lns/tests/test_rg_ralns.py \
  sl_isp_rg_rho_lns/tests/test_paper_a_online_benchmark_protocol.py \
  sl_isp_rg_rho_lns/tests/test_paper_a_online_baselines.py \
  sl_isp_rg_rho_lns/tests/test_paper_a_stage2_pipeline.py -q
```

Py compile:

```bash
python3 -m py_compile \
  sl_isp_rg_rho_lns/src/algorithms/rg_ralns.py \
  sl_isp_rg_rho_lns/src/experiments/paper_a_online_protocol.py \
  scripts/run_paper_a_online_benchmark.py \
  scripts/run_paper_a_experiment_suite.py \
  scripts/summarize_paper_a_results.py
```

Pilot suite:

```bash
python3 scripts/run_paper_a_experiment_suite.py \
  --config configs/paper_a_online.yaml \
  --suite pilot \
  --seeds 0 1 \
  --objective-beta 20 \
  --algorithms EDD Lightweight_RG_Dispatch Online_Legacy_ALNS RG_RALNS \
  --output results/paper_a_stage2_pre_pilot
```

Table generation:

```bash
python3 scripts/summarize_paper_a_results.py \
  --input results/paper_a_stage2_pre_pilot \
  --output results/paper_a_tables_stage2_pre_pilot
```

## 8. Pilot Output Paths

Benchmark output:

```text
results/paper_a_stage2_pre_pilot
```

Generated table output:

```text
results/paper_a_tables_stage2_pre_pilot
```

Generated table files:

- `table_main_comparison.csv`
- `table_beta_sensitivity.csv`
- `table_ablation.csv`
- `table_mechanism_stats.csv`
- `table_scalability.csv`
- `table_seed_robustness.csv`
- `table_statistical_tests.csv`
- `missing_inputs.csv`

The `results/` folders are intentionally not committed.

## 9. Pilot Results

This pilot is a workflow validation with seeds `0,1` and four algorithms. It is not a paper result.

| Algorithm | mean Z_N | mean TT | mean WSF | mean ZSR | mean runtime |
| --- | ---: | ---: | ---: | ---: | ---: |
| EDD | 0.0204 | 41.0 | 0.0 | 1.0 | 0.0014 |
| Online-Legacy-ALNS | 0.0214 | 43.0 | 0.0 | 1.0 | 2.2046 |
| RG-RALNS | 0.0349 | 69.5 | 0.0 | 1.0 | 0.0392 |
| Lightweight RG Dispatch | 0.0458 | 90.0 | 0.0 | 1.0 | 0.0083 |

Mechanism sanity:

- RG-RALNS mean trigger ratio: `0.1953`
- RG-RALNS mean affected-set size: `6.5728`

These pilot seeds have no service shortfall for any of the four algorithms, so they do not validate service-robustness claims.

## 10. Missing Capabilities That Remain

The pipeline is ready to run formal modules, but some experiment content still needs later code or design decisions:

1. Several ablation variants require explicit code switches:
   - w/o recoverability trigger;
   - w/o service-safe extraction;
   - w/o rescue-chain precursor priority.
2. Scalability presets are defined, but final scale values may need adjustment after medium-size timing.
3. Optional Online-ILS/VNS/TS/SA/GA baselines remain future work and are not part of the current main table.
4. Seed-level service outliers remain a research risk for RG-RALNS and should be tracked in every expanded benchmark.

## 11. Recommended Stage 2 Scale

Current observed approximate runtimes:

- `RG-RALNS`: about `0.045 s / instance`;
- `Online-Legacy-ALNS`: about `1.6 s / instance`;
- dispatch baselines: about `0.001-0.01 s / instance`.

Assuming the main-table cost is dominated by `Online-Legacy-ALNS`, a rough small-instance runtime estimate is:

| Instance-seed runs | Estimated runtime |
| ---: | ---: |
| 30 | about 1 minute |
| 60 | about 2 minutes |
| 90 | about 3 minutes |
| 150 | about 5 minutes |

Recommendation:

Start Stage 2 with `60` or `90` instance-seed runs before scaling to `150+`. Larger instance sizes should be introduced gradually because `Online-Legacy-ALNS` may scale much more sharply than dispatch rules or RG-RALNS.

## 12. Readiness Assessment

The Stage 2-pre experiment pipeline is ready for a controlled Stage 2 benchmark run. The algorithm itself is usable as the current main method, but the known seed-level WSF/ZSR tail risk should remain visible in the robustness and mechanism tables.

Recommended next step:

Run Stage 2 main benchmark at 60 or 90 instance-seed runs with the default RG-RALNS configuration, beta values `20` and `50`, and the main online algorithm set only. Then generate tables with `scripts/summarize_paper_a_results.py`.

## 13. Git Metadata

- Branch: `codex/paper-a-stage2-pre-experiment-pipeline`
- Implementation commit: `8eae546 feat: add Paper A Stage 2 pre-experiment pipeline`
- Metadata/merge commit before push-status update: `7e4fe68 merge: reconcile Paper A Stage 2 pre-experiment pipeline`
- Push status: succeeded to `origin/codex/paper-a-stage2-pre-experiment-pipeline`; this final metadata update records that successful push.
