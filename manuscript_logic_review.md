# Manuscript Logic Review

Target manuscript: `paper/0522.tex`

## Current Logic Chain

The manuscript now follows this chain:

1. Classical tardiness-oriented shop scheduling is insufficient when feasibility
   is determined by entity-level on-time quantity.
2. SL-ISP formalizes this setting through flexible operations, service-entity
   mapping, deterministic entity-level transportation delay, fulfillment ratio,
   and weighted shortfall.
3. The offline MILP establishes the formal reference model but is not positioned
   as the large-scale solver.
4. NP-completeness of a restricted zero-shortfall version motivates heuristic
   solution.
5. Recoverability analysis identifies residual service risk, fragile entities,
   unavoidable shortfall, and mandatory rescue jobs.
6. NR-RG-RHO-LNS uses these indicators to generate service-risk-aware candidate
   diversity, while no-regret selection keeps all acceptance decisions tied to
   the original objective `Z`.
7. The computational section describes the experimental method and reserves all
   result-dependent analysis until real CSV files and figures are available.

This chain is coherent for ESWA, Applied Soft Computing, and EJOR-style
positioning.

## Completed Adjustments

- Restored the original proof chain from `test_sec3` / `sec3_problem_theory.tex`.
- Kept the MILP language as "offline benchmark and formal reference model".
- Replaced old recoverability symbols with final manuscript notation.
- Changed the implication section so it does not claim that RG always improves
  the incumbent.
- Connected the marginal recoverability proposition to mandatory rescue
  candidate generation in the algorithm implications.
- Added a LaTeX row-input interface so future result tables can be generated
  from CSV files without manually editing placeholder rows.

## Points to Watch Before Final Submission

- The existing code-side analysis script
  `sl_isp_rg_rho_lns/src/analysis/final_paper_outputs.py` contains some old
  generated text and labels, including `RG-RHO-LNS-Fast`. Do not paste its
  narrative text directly into the manuscript. Use it only as a data-processing
  reference unless the text is cleaned.
- The final run-level CSV should include job-size and machine-size information
  for Table 7. If `final_raw.csv` only stores `instance_index`, a separate
  instance-index mapping is needed before scalability rows can be generated.
- The ablation table requires true ablation outputs. It should not be inferred
  from unrelated baseline algorithms.
- The runtime-budget table can report average and maximum runtime from
  `runtime_total_s`, but schedule evaluations, construction time, and search
  time require explicit log columns.
- Conclusions, abstract results, and statistical claims must remain pending until
  the real outputs are read.

## Style Notes

- The theoretical section is now closer to an EJOR-style structural analysis:
  definitions and results are formal, proofs are compact, and each result has a
  direct algorithmic implication.
- The algorithm section is closer to ESWA/Applied Soft Computing style: it
  emphasizes the solver-free heuristic design, candidate generation, LNS
  mechanics, and empirical evaluation protocol.
- The current balance is appropriate for a manuscript that combines structural
  scheduling analysis with a metaheuristic algorithm.

