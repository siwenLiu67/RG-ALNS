# Symbol Consistency Report

Target manuscript: `paper/0522.tex`

## Summary

- The proposed algorithm is consistently named `NR-RG-RHO-LNS` in the manuscript.
- The full expansion, `No-Regret Recoverability-Guided Rolling-Horizon Large Neighborhood Search`, appears at first use.
- The obsolete name `InitEnhanced-v1.3` does not appear.
- The old proposed-method label `RG-RHO-LNS-Fast` does not appear.
- The MILP is explicitly positioned as an offline small-instance benchmark and formal reference model, not as the large-scale solution method.
- Result claims are intentionally deferred; performance, significance, and improvement statements remain marked as pending placeholders.
- The recoverability proof chain has been restored from the original `test_sec3.tex` source path, which inputs `paper/sec3_problem_theory.tex`, and rewritten with the unified SL-ISP notation.

## Notation Normalization

Implemented normalization choices:

- Big-M and scheduling horizon are unified as `H`; `\mathcal V` is not used.
- Secured on-time quantity is unified as `Q_r^{sec}(t)`; `Q_r^{del}(t)` is not used.
- The manuscript uses `service entity` after the initial problem framing; it does not mix zone, region, batch, or vehicle-routing decision terminology.
- Transportation delay `\tau_r` is described as a deterministic entity-level lead-time abstraction, not an explicit routing or batching model.
- `\beta/\alpha` is described as the relative objective emphasis on service shortfall versus tardiness, not as a service-pressure ratio.
- Algorithm operator names are not included in the main notation table.
- Additional proof-local symbols needed by the restored structural results are defined inline rather than promoted to the main notation table.

## Main Symbols Checked

The following notation-table symbols appear in the main text:

- Sets: `\mathcal J`, `\mathcal M`, `\mathcal R`, `\mathcal O_j`, `\mathcal M_{jo}`, `\mathcal A`, `\mathcal P_h`.
- Parameters: `r_j`, `p_{joh}`, `q_j`, `g(j)`, `d_r`, `\tau_r`, `\rho_r`, `w_r`, `Q_r`, `Q_r^{\min}`, `\alpha`, `\beta`, `H`.
- Schedule variables and derived quantities: `S_{jo}`, `C_j`, `D_j`, `T_j`, `z_j`, `Q_r^{on}`, `U_r`, `X_{joh}`, `Y_{jo,iqh}`.
- Recoverability terms: `t`, `Q_r^{sec}(t)`, `Q_r^{rem}(t)`, `\underline D_j(t)`, `\mathcal E_r(t)`, `\mathcal B`, `\mathrm{Cap}_{\mathcal B}(t,d_r)`, `Q_{r,\mathcal B}^{rec}(t)`, `U_{r,\mathcal B}(t)`, `S_{r,\mathcal B}^{rec}(t)`, `\Delta_{j,r,\mathcal B}^{rec}(t)`.

Local proof or relaxation symbols, such as the knapsack selectors `x_j` and `y_j`, minimum bottleneck workload `\underline w_{j,\mathcal B}(t)`, minimum workload target `W_{r,\mathcal B}^{\min}(t)`, continuation schedule `\pi`, common cutoff `d` in the hardness proof, and exclusion quantity `Q_{r,\mathcal B}^{rec,-j}(t)`, are defined inline and intentionally kept out of the main notation table.

## Restored Proof-Specific Symbols

The following symbols were retained because they are required by the original structural proofs:

- `\underline w_{j,\mathcal B}(t)`: minimum bottleneck workload used in the optimistic recovery relaxation.
- `W_{r,\mathcal B}^{\min}(t)`: minimum workload needed to recover the remaining required quantity.
- `x_j`, `y_j`: local binary selectors for the maximum-quantity and minimum-workload knapsack views.
- `Q_{r,\mathcal B}^{rec,-j}(t)`: recoverable quantity after excluding job `j`, used to define mandatory rescue jobs.

These symbols are not algorithm operator names and are not experiment metrics. They appear only where the proofs require them.

## Abbreviation Check

The abbreviation table includes:

- SL-ISP
- NR-RG-RHO-LNS
- RHO
- LNS
- RG
- EDF
- EDD
- SPT
- WSPT
- ATC
- ILS
- VNS
- TS
- TT
- WSF
- ZSR
- MILP

First-use expansions are present for the main text abbreviations. Abbreviations that only appear in tables are expanded in Table `tab:abbreviations`.

## Label and Reference Check

- Table, figure, algorithm, section, theorem, proposition, corollary, and equation labels are unique.
- Figure labels generated through the placeholder macro are present in `paper/0522.aux`.
- Final LaTeX compilation resolved citations and cross-references.
- The original labels `cor:zero_unattainable`, `def:mandatory`, and `prop:marginal` were deliberately renamed to `cor:unattainable`, `def:mandatory_rescue`, and `prop:marginal_recoverability` in the manuscript. The corresponding proof content is preserved.

## Result-Claim Control

The manuscript does not state that NR-RG-RHO-LNS outperforms baselines, has statistically significant advantages, or achieves any numerical improvement. All result-dependent locations are marked with `\todoresult{pending}` or explicit pending-result text.

The new result-autofill interface writes LaTeX row files only from available CSV
files. If a required CSV or column is missing, `0522.tex` continues to show the
pending placeholders.
