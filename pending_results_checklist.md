# Pending Results Checklist

Target manuscript: `paper/0522.tex`

This checklist records all locations that must wait for real experimental outputs. Do not replace these placeholders with inferred or fabricated values.

## Tables Waiting for Experimental CSV Files

- Table `tab:overall_comparison`
  - Needs final run-level CSV.
  - Expected fields: algorithm, `Z`, `TT`, `WSF`, `ZSR`, runtime.
  - Auto-fill row file: `paper/generated_tables/table3_overall_comparison_rows.tex`.

- Table `tab:pressure_comparison`
  - Needs pressure-level aggregation from final run-level CSV.
  - Expected grouping: pressure level x algorithm.
  - Auto-fill row file: `paper/generated_tables/table4_pressure_comparison_rows.tex`.

- Table `tab:paired_tests`
  - Needs matched instance-seed paired comparisons.
  - Expected fields: baseline, mean or median `Delta Z`, win rate, p-value, effect size.
  - Auto-fill row file: `paper/generated_tables/table5_paired_tests_rows.tex`.

- Table `tab:pressure_specific_tests`
  - Needs pressure-specific paired tests.
  - Expected grouping: pressure level x baseline.
  - Auto-fill row file: `paper/generated_tables/table5b_pressure_specific_tests_rows.tex`.

- Table `tab:ablation`
  - Needs ablation or tagged variant outputs.
  - Required variants: EDF-only, Best-of-5, Multi-start, +polishing, +top-k LNS, Full NR-RG-RHO-LNS.
  - Auto-fill row file: `paper/generated_tables/table6_ablation_rows.tex`.
  - Do not infer this table from unrelated baseline algorithms.

- Table `tab:scalability`
  - Needs job-size x machine-size aggregation.
  - Must include relative gap to best and improvement over RHO-LNS, not only raw `Z`.
  - Auto-fill row file: `paper/generated_tables/table7_scalability_rows.tex`.
  - `final_raw.csv` must contain job-size and machine-size columns, or a separate instance-index mapping must be supplied.

- Table `tab:runtime_budget`
  - Needs runtime and evaluation-budget logs.
  - Expected fields: average runtime, maximum runtime, schedule evaluations, construction time, search time.
  - Auto-fill row file: `paper/generated_tables/table9_runtime_budget_rows.tex`.

- Table `tab:operator_contribution`
  - Needs operator diagnostics.
  - Expected fields: operator usage ratio, success rate, mean `Delta Z` improvement.
  - Auto-fill row file: `paper/generated_tables/table8_operator_contribution_rows.tex`.

Tables `tab:experimental_settings` and `tab:algorithm_classification` are design tables and can be updated from the experiment configuration if the final config changes.

## Figures Waiting for Generated Files

- Figure `fig:overall_z`: `figures/fig1_overall_Z.pdf`
- Figure `fig:tt_wsf_decomposition`: `figures/fig2_tt_wsf_decomposition.pdf`
- Figure `fig:pressure_z`: `figures/fig3_pressure_Z.pdf`
- Figure `fig:pressure_wsf`: `figures/fig4_pressure_WSF.pdf`
- Figure `fig:ablation`: `figures/fig5_ablation.pdf`
- Figure `fig:candidate_selection`: `figures/fig6_candidate_selection_frequency.pdf`
- Figure `fig:convergence`: `figures/fig7_convergence_best_so_far_Z.pdf`
- Figure `fig:runtime`: `figures/fig8_runtime_log_scale.pdf`
- Figure `fig:scalability_heatmap`: `figures/fig9_scalability_heatmap.pdf`
- Figure `fig:operator_contribution`: `figures/fig10_operator_contribution.pdf`
- Figure `fig:gantt`: `figures/fig11_representative_gantt.pdf`

The convergence figure and Gantt chart are required, not optional.

After figure files are generated under the experiment output directory, run:

```powershell
python paper\tools\autofill_results.py --copy-figures
```

The script copies available figure PDFs into `paper/figures/` using the filenames
referenced by `0522.tex`.

## Conclusions That Must Not Be Written Yet

Do not write any of the following until the real result files have been read:

- NR-RG-RHO-LNS outperforms all baselines.
- NR-RG-RHO-LNS is statistically significantly better than a named baseline.
- Any p-value, effect size, or win rate.
- Any percentage improvement.
- Any pressure-level dominance claim.
- Any ablation contribution ranking.
- Any convergence-speed conclusion.
- Any runtime scalability conclusion.
- Any statement that a representative Gantt chart demonstrates general performance.

## Locations Requiring Automatic Filling After Results

- Abstract: add verified quantitative findings only after final results are available.
- Section `sec:overall_comparison`: replace placeholder paragraph with real aggregate interpretation.
- Section `sec:pressure_analysis`: add pressure-specific interpretation from Table `tab:pressure_comparison` and Figures `fig:pressure_z`, `fig:pressure_wsf`.
- Section `sec:statistical_tests`: add paired-test conclusions from Tables `tab:paired_tests` and `tab:pressure_specific_tests`.
- Section `sec:ablation`: add verified component-level conclusions from Table `tab:ablation` and Figures `fig:ablation`, `fig:candidate_selection`.
- Section `sec:scalability`: add relative-gap and improvement analysis from Table `tab:scalability` and Figure `fig:scalability_heatmap`.
- Section `sec:convergence_runtime`: add convergence and runtime interpretation from Figure `fig:convergence`, Figure `fig:runtime`, and Table `tab:runtime_budget`.
- Section `sec:operator_contribution`: add operator-level interpretation only if diagnostics exist.
- Section `sec:gantt`: describe the selected representative instance and avoid broad claims beyond the illustrated case.
- Section `sec:conclusions`: replace the current pre-result conclusion with evidence-based findings.

## Input Files Expected Later

Likely result sources based on the current project structure:

- `sl_isp_rg_rho_lns/outputs/final_v13_validation/final_raw.csv`
- `sl_isp_rg_rho_lns/outputs/final_v13_validation/convergence_raw.csv`
- `sl_isp_rg_rho_lns/outputs/final_v13_validation/initial_candidate_performance.csv`
- `sl_isp_rg_rho_lns/outputs/final_v13_validation/diagnostics_operator_success.csv`
- Aggregated table files under `sl_isp_rg_rho_lns/outputs/final_v13_validation/tables/`
- Generated figure files under `sl_isp_rg_rho_lns/outputs/final_v13_validation/figures/`

## Auto-Fill Interface

Current interface:

- Script: `paper/tools/autofill_results.py`
- Generated status report: `paper/generated_results_status.md`
- Generated row directory: `paper/generated_tables/`
- Default input directory: `sl_isp_rg_rho_lns/outputs/final_v13_validation/`

The script is conservative: it does not create numerical rows when the required
CSV file or required columns are missing.
