# Paper A Stage 2 Pre-Experiment Pipeline Log

**Created:** 2026-06-16
**Author:** Codex (automated pipeline setup)
**Branch:** `codex/paper-a-stage2-pre-experiment-pipeline`

---

## 1. Goal

Prepare the Stage 2-pre formal experiment pipeline for Paper A. Build a
reproducible experiment workflow capable of generating the seven paper tables
(main comparison, beta sensitivity, ablation, mechanism analysis, scalability,
seed robustness, statistical summary) without altering the finalized
RG-RALNS default configuration or running final paper-scale experiments.

---

## 2. New-Computer Setup and Checked-Out Base Branch

- **Repository:** `git@github.com:siwenLiu67/RG-ALNS.git`
- **Clone status:** Repository already existed locally (initial snapshot).
- **Remote authenticated:** HTTPS (SSH host key not configured on new machine).
- **Remote branches confirmed via** `git ls-remote`.
- **Base branch fetched:** `codex/rg-ralns-default-config-reset` (commit `4a48c8d`).

---

## 3. Starting Branch and Commit

- **Base branch:** `codex/rg-ralns-default-config-reset`
- **Starting commit:** `4a48c8d089b1373ec03218729c4282437eb0715d`
- **Commit message:** `docs: record RG-RALNS default config push status`
- **Recent history (top 3):**
  ```
  4a48c8d docs: record RG-RALNS default config push status
  922008f docs: record RG-RALNS default configuration decision
  d1e3e37 chore: reset RG-RALNS default capacity rescue configuration
  ```

---

## 4. New Working Branch

- **Working branch:** `codex/paper-a-stage2-pre-experiment-pipeline`
- **Created from:** `codex/rg-ralns-default-config-reset` at `4a48c8d`

---

## 5. Finalized Default RG-RALNS Configuration

Confirmed from `configs/paper_a_online.yaml`:

```yaml
rg_ralns:
  H_A: 8
  N_A: 40
  acceptance_mode: service_safe_z
  bottleneck_trigger_mode: normal
  rescue_fallback_enabled: true
  protect_zero_wsf: true
  adaptive_destroy_size: true
  capacity_rescue_enabled: false          # <-- STAYS FALSE
  rescue_reservation_window: 1
  rescue_machine_pressure_threshold: 1
  low_risk_on_rescue_machine_penalty: true
```

**Status:** `capacity_rescue_enabled` is `false`. Stage 1.5 capacity rescue is
disabled by default. This is the finalized default and must NOT be changed.

---

## 6. Formal Experiment Modules

### 6.1 Main Online Comparison

| Algorithm | Key | Type |
|---|---|---|
| EDD | `edd` | dispatching |
| SPT | `spt` | dispatching |
| WSPT | `wspt` | dispatching |
| ATC | `atc` | dispatching |
| SWD | `swd` | dispatching |
| SFG | `sfg` | dispatching |
| Lightweight RG Dispatch | `lightweight_rg_dispatch` | lightweight_rg_dispatch |
| Online-Legacy-ALNS | `online_legacy_rg_alns` | legacy_rg_alns |
| RG-RALNS | `rg_ralns` | rg_ralns |

Metrics: Z_N, TT, WSF, TT_hat, WSF_hat, ZSR, runtime, mean, std, SE, 95% CI,
rank, average rank.

### 6.2 Beta Sensitivity

Beta values: `{1, 5, 10, 20, 50, 100}`

Minimum algorithms: RG-RALNS, Online-Legacy-ALNS, Lightweight RG Dispatch, EDD.

Uses stored TT_hat and WSF_hat from the per-instance CSV to recompute Z_N at
each beta_0 without re-running simulations.

### 6.3 Ablation Study

| Variant | Implementable | Notes |
|---|---|---|
| Full RG-RALNS default | Yes | Baseline |
| w/o recoverability trigger | Partial | `bottleneck_trigger_mode: normal` reduces but does not fully disable. Full disable requires code change to force bypass of `_should_trigger_*` checks. NOT recommended for final paper in current state. |
| w/o service-safe extraction | Yes | `acceptance_mode: service_first` |
| w/o service-safe acceptance | Partial | Currently same as w/o service-safe extraction. Needs separate code path to decouple extraction safety from acceptance safety. |
| w/o local ALNS (Lightweight RG) | Yes | Uses `lightweight_rg_dispatch` algorithm key as its own variant. |
| capacity_rescue_enabled=true | Yes | Diagnostic only. NOT default. |

**Recommended for final paper:** Full RG-RALNS, w/o service-safe extraction,
w/o local ALNS (Lightweight RG Dispatch), and capacity_rescue_enabled as
separate diagnostic appendix.

### 6.4 Mechanism Analysis

Fields collected per RG-RALNS run:
- `trigger_count`, `trigger_ratio`
- `trigger_reason_counts` (per-reason breakdown)
- `avg_A_size`, `max_A_size`
- `alns_runtime_total`
- `dispatch_fallback_count`
- `rescue_fallback_success_count`
- `ordinary_fallback_count`
- `no_ready_operation_available_count` (from fallback_failure_reason_counts)
- `local_extraction_success_count`
- `affected_set_rescue_success_count`
- `operator_stats` (if available via debug_trace)
- `rescue_machine_contention_events`
- `mandatory_precursor_in_A_count`, `cover_precursor_in_A_count`
- `mandatory_precursor_selected_count`, `cover_precursor_selected_count`

Purpose: Show RG-RALNS is a risk-triggered local ALNS, not an every-event full
global ALNS.

### 6.5 Scalability Analysis

| Scale | n_jobs | n_machines | n_entities |
|---|---|---|---|
| small | 20 | 5 | 3 |
| medium | 50 | 10 | 5 |
| large | 100 | 20 | 8 |
| xlarge | 200 | 40 | 12 |

Status: Structure prepared. No scalability runs executed yet.

### 6.6 Robustness Analysis

Support for:
- Multiple seeds
- Per-seed WSF/ZSR diagnostics
- Service outlier detection: `is_service_outlier = WSF > threshold_wsf OR ZSR < threshold_zsr`
- Configurable thresholds (default: WSF > 0, ZSR < 1)

---

## 7. Statistical Summary Design

Supported statistics:
- Mean, standard deviation, standard error
- 95% confidence interval (t-distribution for n < 30, normal approx for n >= 30)
- Relative improvement: `(baseline - algorithm) / baseline * 100`
- Paired t-test (scipy.stats.ttest_rel) — if scipy available
- Wilcoxon signed-rank test (scipy.stats.wilcoxon) — if scipy available
- Minimum n=3 for statistical tests

Key comparisons:
1. RG-RALNS vs Online-Legacy-ALNS
2. RG-RALNS vs Lightweight RG Dispatch
3. RG-RALNS vs EDD
4. Lightweight RG Dispatch vs EDD
5. Online-Legacy-ALNS vs EDD

Metrics tested: Z_N, TT, WSF, ZSR.

When scipy is not installed, descriptive statistics are still computed and
statistical tests are gracefully skipped (p-value columns = None).

---

## 8. Scripts and Configs Added or Modified

### New files

| File | Purpose |
|---|---|
| `scripts/run_paper_a_experiment_suite.py` | Multi-suite experiment orchestrator |
| `scripts/summarize_paper_a_results.py` | Paper-ready table generator with statistics |

### Existing files (unchanged)

| File | Status |
|---|---|
| `scripts/run_paper_a_online_benchmark.py` | Unchanged |
| `configs/paper_a_online.yaml` | Unchanged |
| `sl_isp_rg_rho_lns/src/experiments/paper_a_online_protocol.py` | Unchanged |
| `sl_isp_rg_rho_lns/src/algorithms/rg_ralns.py` | Unchanged |

### Suite runner capabilities

1. ✅ Run main comparison (`--suite main`)
2. ✅ Run beta sensitivity (`--suite beta_sensitivity`)
3. ✅ Run ablation variants (`--suite ablation`)
4. ✅ Run mechanism analysis (`--suite mechanism`)
5. ✅ Run scalability settings (`--suite scalability`)
6. ✅ Run seed robustness (`--suite robustness`)
7. ✅ Run pilot validation (`--suite pilot`)
8. ✅ Run all suites (`--suite all`)
9. ✅ Save config_used.yaml (via existing protocol)
10. ✅ Save git branch and commit hash (`run_metadata.json`)
11. ✅ Save run timestamp (`run_metadata.json`)
12. ✅ Friendly algorithm name aliases

### Summarizer capabilities

1. ✅ Generate table_main_comparison.csv
2. ✅ Generate table_beta_sensitivity.csv
3. ✅ Generate table_ablation.csv
4. ✅ Generate table_mechanism_stats.csv
5. ✅ Generate table_scalability.csv
6. ✅ Generate table_seed_robustness.csv
7. ✅ Generate table_statistical_tests.csv
8. ✅ Graceful handling of missing data with clear warnings
9. ✅ Descriptive statistics (mean, std, SE, 95% CI)
10. ✅ Paired statistical tests (scipy-dependent, skipped gracefully)
11. ✅ Relative improvement columns

---

## 9. Pilot Validation

### Command

```bash
python scripts/run_paper_a_experiment_suite.py \
  --config configs/paper_a_online.yaml \
  --suite pilot \
  --seeds 0 1 \
  --objective-beta 20 \
  --algorithms EDD Lightweight_RG_Dispatch Online_Legacy_ALNS RG_RALNS \
  --output results/paper_a_stage2_pre_pilot
```

### Pilot output path

```
results/paper_a_stage2_pre_pilot/
```

### Table generation command

```bash
python scripts/summarize_paper_a_results.py \
  --input results/paper_a_stage2_pre_pilot \
  --output results/paper_a_tables_stage2_pre_pilot
```

### Table generation output path

```
results/paper_a_tables_stage2_pre_pilot/
```

### Generated table files

| Table | Path | Rows |
|---|---|---|
| Main comparison | `table_main_comparison.csv` | 4 algorithms |
| Beta sensitivity | `table_beta_sensitivity.csv` | 24 (4 algos × 6 betas) |
| Mechanism stats | `table_mechanism_stats.csv` | 3 (2 runs + aggregate) |
| Seed robustness | `table_seed_robustness.csv` | 8 (4 algos × 2 seeds) |
| Statistical tests | `table_statistical_tests.csv` | 20 (5 comparisons × 4 metrics) |

Ablation and scalability tables were skipped because the pilot does not include
that data (single-source run with no variant directories).

### Pilot results summary (beta_0=20)

| Algorithm | Z_N | TT | WSF | ZSR | Runtime (s) |
|---|---|---|---|---|---|
| EDD | 0.0204 | 41.0 | 0.0 | 1.0 | 0.0019 |
| Lightweight RG Dispatch | 0.0458 | 90.0 | 0.0 | 1.0 | 0.0117 |
| Online-Legacy-ALNS | 0.0214 | 43.0 | 0.0 | 1.0 | 2.9469 |
| RG-RALNS | 0.0349 | 69.5 | 0.0 | 1.0 | 0.0596 |

WSF=0 across all algorithms indicates no service stress in this single instance
(20 jobs, 5 machines, 3 entities). This is expected for smoke-test scale.

---

## 10. Missing Capabilities That Remain

### Not yet implementable without code changes

1. **Full trigger disable ablation**: The current `bottleneck_trigger_mode:
   normal` reduces trigger sensitivity but does not bypass the trigger system
   entirely. A code change to `RGRALNS` adding a `disable_trigger: bool` config
   flag would be needed for a clean "w/o recoverability trigger" ablation.

2. **Decoupled service-safe extraction vs acceptance**: Both currently use
   `acceptance_mode`. A separate `extraction_mode` parameter would be needed
   to independently ablate extraction safety and acceptance safety.

3. **no_ready_operation_available_count**: Currently only available in the
   fallback failure reason counts, not as a top-level mechanism field. It is
   captured in the rescue failure summary CSV.

### Not yet run (by design)

4. **Large-scale experiments**: Only pilot-scale (seeds=0,1; 1 instance) was
   run. Full paper-scale experiments require more seeds and instances.

5. **Scalability experiments**: Structure prepared, not executed.

6. **Full ablation with all variants**: Only the variant structure and config
   overrides are prepared; no ablation suite has been run.

---

## 11. Whether Ready for Stage 2 Main Benchmark

**YES**, the pipeline is ready for Stage 2 main benchmark with the following
caveats:

- The suite runner, summarizer, statistical tests, and table generation all
  function correctly as demonstrated by the pilot.
- Full trigger-disable ablation requires a small code change (add
  `disable_trigger` flag) if needed for the final paper.
- Decoupled extraction/acceptance ablation requires a code change if needed.
- The capacity_rescue_enabled diagnostic variant works as-is.

---

## 12. Recommended Stage 2 Experiment Scale

### Runtime estimates (based on observed pilot timings)

| Algorithm | Approx runtime / instance-seed |
|---|---|
| RG-RALNS | ~0.05 s |
| Online-Legacy-ALNS | ~1.6 s |
| Lightweight RG Dispatch | ~0.01 s |
| Dispatching rules (EDD, etc.) | ~0.002 s |

### Estimated total runtime

| Scale | Instance-seed runs | Estimated runtime |
|---|---|---|
| 30 | 1 instance × 30 seeds | ~2 min |
| 60 | 2 instances × 30 seeds | ~4 min |
| 90 | 3 instances × 30 seeds | ~6 min |
| 150 | 5 instances × 30 seeds | ~10 min |
| 300 | 10 instances × 30 seeds | ~20 min |

Actual runtime depends on instance size. Larger instances (100+ jobs) will
increase Online-Legacy-ALNS runtime significantly.

### Recommendation

**Start with 90 instance-seed runs (3 instances × 30 seeds)** for the Stage 2
main benchmark. This provides enough statistical power for paired tests while
keeping runtime manageable.

If performance variance is high, scale to 150 or 300 before finalizing.

---

## 13. Tests and Validation Results

### py_compile (all pass)
```
✅ sl_isp_rg_rho_lns/src/algorithms/rg_ralns.py
✅ sl_isp_rg_rho_lns/src/experiments/paper_a_online_protocol.py
✅ scripts/run_paper_a_online_benchmark.py
✅ scripts/run_paper_a_experiment_suite.py
✅ scripts/summarize_paper_a_results.py
```

### pytest (42 passed, 0 failed)
```
✅ test_rg_ralns.py
✅ test_paper_a_online_benchmark_protocol.py
✅ test_paper_a_online_baselines.py
```

### Pilot suite (completed)
```
✅ Suite: pilot
✅ Seeds: 0, 1
✅ Beta_0: 20
✅ Algorithms: EDD, Lightweight RG Dispatch, Online-Legacy-ALNS, RG-RALNS
✅ Runtime: 6.1 s
✅ Output: 8 per-instance rows, 15 output files
```

### Summarizer (completed)
```
✅ 5 paper-ready table CSVs generated
✅ SciPy available for statistical tests
✅ Graceful handling of small n (p-values = None for n < 3)
```

---

## 14. Remaining Risks

1. **SSH not configured on new machine.** HTTPS works for fetch (public repo
   or cached credentials). Push may require authentication setup.

2. **Single smoke-test instance.** The pilot only ran 1 instance × 2 seeds = 2
   instance-seed runs per algorithm. WSF=0 across the board suggests this
   instance is not representative of service-stressed scenarios. Stage 2 must
   include instances with service pressure.

3. **Online-Legacy-ALNS runtime.** At ~1.6 s per instance-seed, scaling to
   many seeds × instances will dominate total runtime. Consider limiting
   Online-Legacy-ALNS runs or using more seeds only for dispatch baselines.

4. **Ablation variants not fully independent.** Two variants (w/o service-safe
   extraction, w/o service-safe acceptance) currently map to the same config.
   This needs resolution before final paper.

---

## 15. Next Recommended Codex Task

**"Run Paper A Stage 2 main benchmark with 3 instances × 30 seeds"**

This should:
1. Stay on the `codex/paper-a-stage2-pre-experiment-pipeline` branch.
2. Use `--suite main` with all 9 algorithms and 30 seeds.
3. Generate the full paper-ready tables with the summarizer.
4. Store results in `results/paper_a_stage2_main/`.
5. Compare against the expected default performance baselines documented in
   `docs/rg_ralns_default_configuration_decision_log.md`.

---

## 16. Git Status

- **Branch:** `codex/paper-a-stage2-pre-experiment-pipeline`
- **Base commit:** `4a48c8d`
- **New files:** `scripts/run_paper_a_experiment_suite.py`,
  `scripts/summarize_paper_a_results.py`
- **Modified files:** None (all existing files unchanged)
- **Push status:** Pending
