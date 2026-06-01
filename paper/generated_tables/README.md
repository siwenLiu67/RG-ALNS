# Generated LaTeX Table Rows

This directory is intentionally empty until real experimental CSV files are
available. The manuscript `0522.tex` checks for row files in this directory and
falls back to pending placeholders when they are absent.

Generate rows after the final experiment outputs are available:

```powershell
python paper\tools\autofill_results.py --copy-figures
```

Expected row files include:

- `table3_overall_comparison_rows.tex`
- `table4_pressure_comparison_rows.tex`
- `table5_paired_tests_rows.tex`
- `table5b_pressure_specific_tests_rows.tex`
- `table6_ablation_rows.tex`
- `table7_scalability_rows.tex`
- `table8_operator_contribution_rows.tex`
- `table9_runtime_budget_rows.tex`

