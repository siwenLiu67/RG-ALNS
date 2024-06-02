# Manuscript Structure Report

Target manuscript: `paper/0522.tex`

## Completed Structure

The manuscript now follows the requested SCI-style structure:

1. Introduction
2. Literature review
   - Integrated production and service-level scheduling
   - Flexible job-shop and event-driven scheduling
   - Metaheuristic and rolling-horizon methods
   - Research gaps and positioning of this study
3. Problem description and mathematical formulation
   - Problem description
   - Mathematical programming model
   - Complexity and motivation for heuristic solution
4. Structural recoverability analysis
   - Optimistic recoverability relaxation
   - Recoverable quantity and unavoidable shortfall
   - Recoverability erosion
   - Mandatory rescue jobs
   - Implications for algorithm design
5. Proposed algorithm: NR-RG-RHO-LNS
   - Overall framework
   - No-regret multi-start initialization
   - Recoverability-guided candidate generation
   - Rolling-horizon LNS search
   - Incumbent preservation and acceptance rule
   - Computational complexity and implementation notes
6. Computational experiments
   - Experimental design
   - Compared algorithms
   - Evaluation metrics
   - Overall performance comparison
   - Pressure-level analysis
   - Statistical tests
   - Ablation study
   - Scalability analysis
   - Convergence and runtime analysis
   - Operator contribution
   - Gantt-chart illustration
7. Conclusions

## Added Tables

- Table `tab:abbreviations`: Abbreviations.
- Table `tab:notation`: Unified notation.
- Table `tab:experimental_settings`: Experimental settings.
- Table `tab:algorithm_classification`: Algorithm classification.
- Table `tab:overall_comparison`: Overall comparison placeholder.
- Table `tab:pressure_comparison`: Pressure-level comparison placeholder.
- Table `tab:paired_tests`: Paired statistical tests placeholder.
- Table `tab:pressure_specific_tests`: Pressure-specific paired tests placeholder.
- Table `tab:ablation`: Ablation study placeholder.
- Table `tab:scalability`: Scalability analysis placeholder.
- Table `tab:runtime_budget`: Runtime and budget placeholder.
- Table `tab:operator_contribution`: Operator contribution placeholder.

Result-dependent tables now include a guarded row-input interface. If a matching
file exists under `paper/generated_tables/`, `0522.tex` inputs the generated
rows; otherwise it keeps the pending placeholders. This avoids manual table
editing after the experimental CSV files become available.

## Added Figures

The manuscript reserves all requested figure locations with safe `\includegraphics` placeholders:

- `figures/fig1_overall_Z.pdf`
- `figures/fig2_tt_wsf_decomposition.pdf`
- `figures/fig3_pressure_Z.pdf`
- `figures/fig4_pressure_WSF.pdf`
- `figures/fig5_ablation.pdf`
- `figures/fig6_candidate_selection_frequency.pdf`
- `figures/fig7_convergence_best_so_far_Z.pdf`
- `figures/fig8_runtime_log_scale.pdf`
- `figures/fig9_scalability_heatmap.pdf`
- `figures/fig10_operator_contribution.pdf`
- `figures/fig11_representative_gantt.pdf`

The placeholder macro compiles even when the figure files are not yet present.

## Mathematical Model Status

- The MILP uses the operation set `\mathcal A`.
- The pair set `\mathcal P_h` restricts sequencing variables to machine-compatible operation pairs.
- The on-time indicator uses `D_j \le d_{g(j)} + H(1-z_j)`.
- All variable domains are included, including `T_j,U_r\ge0`.
- The MILP section states that the formulation is an offline small-instance benchmark and that NR-RG-RHO-LNS is the scalable solver-free method.

## Recoverability Section Status

The structural section has been expanded again using the original proof source. The file `paper/test_sec3.tex` is a wrapper that inputs `paper/sec3_problem_theory.tex`; the restored manuscript section follows that proof chain while normalizing the notation to the current SL-ISP conventions.

The recoverability section now contains:

- Restricted zero-shortfall service fulfillment problem definition.
- NP-completeness theorem and proof via 0-1 knapsack decision.
- Optimistic service-recovery relaxation with minimum-workload and maximum-recoverable-quantity views.
- Equivalent dual-knapsack characterization of optimistic zero-shortfall recoverability.
- Unavoidable shortfall lower bound.
- Zero-shortfall unattainability corollary.
- Recoverability erosion theorem under the original non-recovery capacity-consumption conditions.
- Mandatory rescue job definition and theorem.
- Quantity-mandatory and capacity-mandatory propositions.
- Marginal recoverability characterization.
- Concise implication sentence after each result.

The text explicitly states that recoverability guidance provides service-risk-aware candidate diversity and does not guarantee improvement by itself.

## Algorithm Section Status

The proposed method is framed around:

- Solver-free RHO-LNS backbone.
- No-regret multi-start initialization.
- EDF, EDD-oriented, SPT, WSPT, ATC, regret-k, RG-SPT, and RG-ATC candidates.
- Lightweight polishing.
- Top-ranked incumbent retention.
- Guarded RG intensification.
- Final selection by original objective `Z`.

Two algorithm environments are included:

- Algorithm 1: Overall NR-RG-RHO-LNS framework.
- Algorithm 2: No-regret multi-start initialization.

## Compilation Status

Verified with:

`latexmk -pdf -interaction=nonstopmode -halt-on-error 0522.tex`

Run directory:

`paper/`

Output:

`paper/0522.pdf`

The final compile completed successfully after the proof restoration and result
row-input interface were added. Remaining warnings are layout-level overfull or
underfull boxes caused by long title/table placeholder text, not unresolved
references or fatal errors.

## Additional Support Files

- `proof_preservation_audit.md`: theorem-by-theorem audit from `test_sec3` /
  `sec3_problem_theory.tex` to the current manuscript.
- `manuscript_logic_review.md`: logic-chain and style review for the current
  manuscript.
- `paper/tools/autofill_results.py`: CSV-to-LaTeX row generator for result
  tables and optional figure copying.
- `paper/generated_tables/README.md`: generated-row interface documentation.
- `paper/generated_results_status.md`: current status of available result files.
