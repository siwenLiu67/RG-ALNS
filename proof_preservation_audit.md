# Proof Preservation Audit

Target manuscript: `paper/0522.tex`

Original source requested by the user: `paper/test_sec3.tex`

`paper/test_sec3.tex` is a wrapper file:

```tex
\input{sec3_problem_theory.tex}
```

Therefore, the audited proof source is `paper/sec3_problem_theory.tex`.

## Summary

All formal results in the original structural-analysis file have been retained in
`paper/0522.tex`. The current manuscript does not copy the old symbols verbatim:
it rewrites them into the unified SL-ISP notation required by the paper plan.

Key symbol normalizations:

- `Q_r^{min}` -> `Q_r^{\min}`
- `\overline Q_{r,\mathcal B}^{rec}(t)` -> `Q_{r,\mathcal B}^{rec}(t)`
- `\underline U_{r,\mathcal B}(t)` -> `U_{r,\mathcal B}(t)`
- `\operatorname{Cap}_{\mathcal B}(t,d_r)` -> `\mathrm{Cap}_{\mathcal B}(t,d_r)`
- Old implication wording for `RG-RHO-LNS` -> `NR-RG-RHO-LNS`
- Old label `def:mandatory` -> `def:mandatory_rescue`
- Old label `prop:marginal` -> `prop:marginal_recoverability`
- Old label `cor:zero_unattainable` -> `cor:unattainable`

## Result-by-Result Mapping

| Original item in `sec3_problem_theory.tex` | Current item in `0522.tex` | Status | Notes |
|---|---|---|---|
| Definition `def:rzssfp`: Restricted Zero-Shortfall Service Fulfillment Problem | Definition `def:rzssfp`: Restricted zero-shortfall service fulfillment problem | Preserved | Wording tightened; acronym avoided in main text to reduce abbreviation load. |
| Theorem `thm:np_complete`: RZSSFP is NP-complete | Theorem `thm:np_complete`: Complexity of zero-shortfall verification | Preserved | Proof still uses 0-1 knapsack decision reduction; old informal citation text removed to avoid an uncited reference. |
| Optimistic service-recovery relaxation definitions | Section `sec:optimistic_recoverability` | Preserved and normalized | Retains `Q_r^{sec}(t)`, `Q_r^{rem}(t)`, `\underline D_j(t)`, `\mathcal E_r(t)`, `\underline w_{j,\mathcal B}(t)`, and bottleneck capacity. |
| Minimum-workload recovery problem | Equations `eq:min_workload`--`eq:min_workload_quantity` | Preserved | Symbol normalized to `W_{r,\mathcal B}^{\min}(t)`. |
| Maximum recoverable service quantity problem | Equations `eq:recoverable_quantity`--`eq:recoverable_capacity` | Preserved | Symbol normalized to `Q_{r,\mathcal B}^{rec}(t)`; local selector changed from `z_j` to `x_j` to avoid conflict with on-time indicator. |
| Theorem `thm:dual_knapsack` | Theorem `thm:dual_knapsack` | Preserved | Both proof directions retained. |
| Theorem `thm:unavoidable_shortfall` | Theorem `thm:unavoidable_shortfall` | Preserved | Bound rewritten with `U_{r,\mathcal B}(t)`. |
| Corollary `cor:zero_unattainable` | Corollary `cor:unattainable` | Preserved | Label changed for compactness; claim unchanged. |
| Theorem `thm:erosion` | Theorem `thm:erosion` | Preserved | Conditions C1--C4 and monotonic proof retained. |
| Definition `def:mandatory`: Mandatory rescue job | Definition `def:mandatory_rescue` | Preserved | Label clarified to avoid a generic label. |
| Theorem `thm:mandatory_delivery` | Theorem `thm:mandatory_delivery` | Preserved | Contradiction proof retained. |
| Proposition `prop:quantity_mandatory` | Proposition `prop:quantity_mandatory` | Preserved | Proof retained and streamlined. |
| Proposition `prop:capacity_mandatory` | Proposition `prop:capacity_mandatory` | Preserved | Proof retained and streamlined. |
| Proposition `prop:marginal` | Proposition `prop:marginal_recoverability` | Preserved | Exact marginal condition retained. |
| Original final implications for RG-RHO-LNS | Section `sec:recoverability_implications` | Preserved with updated positioning | Rewritten so RG indicators provide candidate diversity; no claim that RG necessarily improves every schedule. |

## Deliberate Edits

The following changes are intentional and should not be treated as missing proof
content:

- The original statement that `\gamma=\beta/\alpha` is a service-pressure ratio
  was not retained. The manuscript now follows the user's instruction and calls
  it the relative objective emphasis on service shortfall versus tardiness.
- The original `zone` wording was normalized to `service entity`.
- The original proof-local selector `z_j` in the knapsack relaxation was changed
  to `x_j` so it does not conflict with the model's on-time indicator `z_j`.
- The original `\overline Q` and `\underline U` symbols were removed in favor of
  the manuscript's final recoverability notation.
- Some explanatory paragraphs were tightened to match SCI journal style, but the
  formal statements and proof logic were retained.

## Appendix Recommendation

Current recommendation: keep the proof chain in the main manuscript for now.

Reason: the recoverability results are central to the algorithmic contribution,
and the user explicitly requested that the original `test_sec3` proof content be
preserved. If the target journal later imposes a strict page limit, the following
items can be moved to an appendix with minimal loss of narrative continuity:

- Full NP-completeness reduction proof.
- The second direction of the dual-knapsack proof.
- Detailed algebra in the recoverability erosion proof.
- Proofs of the quantity-mandatory and capacity-mandatory propositions.

