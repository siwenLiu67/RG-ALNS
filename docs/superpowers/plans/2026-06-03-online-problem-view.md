# Online Problem View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an online information boundary where algorithms see only released jobs while entity-level service commitments remain known.

**Architecture:** Keep `SLISPInstance` as the complete experimental ground truth and add `OnlineProblemView` as the algorithm-facing view. The simulator will optionally construct this view at each dispatch epoch while preserving the existing offline/full-information mode by default.

**Tech Stack:** Python dataclasses, existing event-driven simulator, pytest.

---

### Task 1: Online View Dataclass

**Files:**
- Create: `sl_isp_rg_rho_lns/src/core/online.py`
- Test: `sl_isp_rg_rho_lns/tests/test_online_simulator.py`

- [ ] Write tests that create an `OnlineProblemView`, verify it exposes `num_jobs`, `get_job`, `get_entity`, `jobs_of_entity`, and immutable copied `entity_future_quantity`.
- [ ] Run the targeted test and verify it fails because `src.core.online` is missing.
- [ ] Implement `OnlineProblemView` with an `SLISPInstance`-like read API.
- [ ] Re-run the targeted test and verify it passes.

### Task 2: Simulator Online Visibility

**Files:**
- Modify: `sl_isp_rg_rho_lns/src/core/simulator.py`
- Test: `sl_isp_rg_rho_lns/tests/test_online_simulator.py`

- [ ] Write tests proving `run_simulation(..., online_visibility=True)` hides unreleased jobs from the algorithm and decrements `entity_future_quantity` as jobs arrive.
- [ ] Run the targeted test and verify it fails because `online_visibility` is not supported.
- [ ] Add an online mode to `run_simulation` that maintains visible job ids and builds `OnlineProblemView` before every algorithm call.
- [ ] Re-run the targeted test and verify it passes.

### Task 3: Compatibility Check

**Files:**
- Modify only if needed: `sl_isp_rg_rho_lns/src/core/simulator.py`
- Test: existing simulator and RG tests

- [ ] Run existing simulator tests to verify default full-information behavior remains unchanged.
- [ ] Run a focused RG-ALNS test to verify the algorithm accepts `OnlineProblemView` through its existing `SLISPInstance`-like interface.
- [ ] Fix only compatibility issues introduced by the online view boundary.

### Task 4: Known Future Quantity in Recoverability

**Files:**
- Modify: `sl_isp_rg_rho_lns/src/recoverability/shortfall_bounds.py`
- Modify: `sl_isp_rg_rho_lns/src/algorithms/rg_rho_lns_fast.py`
- Test: `sl_isp_rg_rho_lns/tests/test_online_simulator.py`

- [ ] Write tests proving known future aggregate quantity reduces current-information shortfall risk.
- [ ] Write tests proving entity classification uses an `arrival_dependent_recoverable` class when visible jobs are insufficient but known future quantity covers the remaining requirement.
- [ ] Write tests proving RG-ALNS projected WSF uses known future quantity as an online buffer.
- [ ] Implement `current_information_shortfall_risk` and route RG-ALNS service-risk logic through it.
- [ ] Re-run online and recoverability tests.

### Task 5: Final Verification

**Files:**
- No new files expected.

- [ ] Run `python3 -m pytest tests/test_online_simulator.py tests/test_simulator.py -q`.
- [ ] Run a broader targeted suite if quick enough: `python3 -m pytest tests/test_rho_projection.py tests/test_recoverability.py -q`.
- [ ] Report the exact test commands and results.

## Self-Review

- Spec coverage: The plan adds a hard algorithm-facing online boundary, preserves entity-level `rho * total_quantity` commitments, and keeps final objective evaluation on the full instance.
- Placeholder scan: No implementation placeholder remains in the actionable tasks.
- Type consistency: `OnlineProblemView` intentionally mirrors the subset of `SLISPInstance` used by scheduling and recoverability code.
