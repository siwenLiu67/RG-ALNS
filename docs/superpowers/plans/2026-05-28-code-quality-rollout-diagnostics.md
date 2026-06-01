# Code Quality Rollout Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve today's development baseline by removing the pytest warning, adding rollout portfolio diagnostics, and reducing duplicated NR-RG-RHO-LNS factory parameter wiring.

**Architecture:** Keep algorithm behavior unchanged in this pass. Add one focused analysis module for portfolio CSV diagnostics, add tests around its pure functions and CLI wrapper, and refactor benchmark factory wiring through one kwargs helper so future tuning parameters are less error-prone.

**Tech Stack:** Python 3.13, pytest, pandas, PyYAML, existing SL-ISP package layout.

---

### Task 1: Fix Pytest Timeout Warning

**Files:**
- Modify: `sl_isp_rg_rho_lns/requirements.txt`

- [ ] **Step 1: Reproduce warning**

Run:

```bash
cd /Volumes/siwen_硬盘/论文/0326/paper0520/sl_isp_rg_rho_lns
python3 -m pytest
```

Expected: tests pass with `PytestConfigWarning: Unknown config option: timeout`.

- [ ] **Step 2: Add missing plugin dependency**

Add this line to `sl_isp_rg_rho_lns/requirements.txt`:

```text
pytest-timeout>=2.3.0
```

- [ ] **Step 3: Verify warning status**

Run:

```bash
cd /Volumes/siwen_硬盘/论文/0326/paper0520/sl_isp_rg_rho_lns
python3 -m pytest
```

Expected: tests pass. If the current environment has not installed `pytest-timeout`, the warning may remain locally; the dependency file should still be correct for reproducible setup.

### Task 2: Add Rollout Portfolio Diagnostics

**Files:**
- Create: `sl_isp_rg_rho_lns/src/analysis/rollout_portfolio_diagnostics.py`
- Create: `sl_isp_rg_rho_lns/tests/test_rollout_portfolio_diagnostics.py`

- [ ] **Step 1: Write failing tests**

Create tests that build a small portfolio dataframe and verify:

```python
def test_candidate_summary_marks_slow_never_selected_candidates():
    rows = [
        {"instance_index": 0, "algorithm": "NR", "candidate": "EDD", "Z": 10.0, "runtime_s": 0.1, "selected": True},
        {"instance_index": 0, "algorithm": "NR", "candidate": "Sequence", "Z": 100.0, "runtime_s": 8.0, "selected": False},
        {"instance_index": 1, "algorithm": "NR", "candidate": "EDD", "Z": 12.0, "runtime_s": 0.1, "selected": True},
        {"instance_index": 1, "algorithm": "NR", "candidate": "Sequence", "Z": 90.0, "runtime_s": 9.0, "selected": False},
    ]
    summary = summarize_rollout_portfolio(pd.DataFrame(rows), slow_runtime_s=1.0)
    sequence = summary.loc[summary["candidate"] == "Sequence"].iloc[0]
    assert sequence["selected_count"] == 0
    assert sequence["slow_never_selected"] is True
```

and:

```python
def test_load_and_write_summary_round_trip(tmp_path):
    source = tmp_path / "portfolio.csv"
    output = tmp_path / "summary.csv"
    pd.DataFrame([...]).to_csv(source, index=False)
    written = write_rollout_diagnostics(source, output)
    assert written == output
    assert output.exists()
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
cd /Volumes/siwen_硬盘/论文/0326/paper0520/sl_isp_rg_rho_lns
python3 -m pytest tests/test_rollout_portfolio_diagnostics.py -q
```

Expected: import failure because the new module does not exist.

- [ ] **Step 3: Implement diagnostics module**

Implement:

```python
REQUIRED_COLUMNS = {"instance_index", "algorithm", "candidate", "Z", "runtime_s", "selected"}

def summarize_rollout_portfolio(df: pd.DataFrame, slow_runtime_s: float = 30.0) -> pd.DataFrame:
    ...

def write_rollout_diagnostics(input_csv: str | Path, output_csv: str | Path, slow_runtime_s: float = 30.0) -> Path:
    ...
```

Summary rows should include `candidate`, `runs`, `selected_count`, `selection_rate`, `mean_Z`, `mean_runtime_s`, `mean_regret_vs_instance_best`, and `slow_never_selected`.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
cd /Volumes/siwen_硬盘/论文/0326/paper0520/sl_isp_rg_rho_lns
python3 -m pytest tests/test_rollout_portfolio_diagnostics.py -q
```

Expected: tests pass.

### Task 3: Refactor NR Factory Kwargs

**Files:**
- Modify: `sl_isp_rg_rho_lns/src/experiments/run_pilot_benchmark.py`
- Modify: `sl_isp_rg_rho_lns/tests/test_rho_projection.py`

- [ ] **Step 1: Write failing test**

Add a test that imports `_nr_rg_rho_lns_kwargs` and verifies all shared rollout, sequence, exact-local, and intensified parameters are mapped from config with defaults.

- [ ] **Step 2: Run targeted test to verify RED**

Run:

```bash
cd /Volumes/siwen_硬盘/论文/0326/paper0520/sl_isp_rg_rho_lns
python3 -m pytest tests/test_rho_projection.py::test_nr_rg_rho_lns_kwargs_maps_shared_parameters -q
```

Expected: import or attribute failure because helper does not exist.

- [ ] **Step 3: Implement helper and use it**

Add:

```python
def _nr_rg_rho_lns_kwargs(algo_cfg: dict, seed: int, default_lns_iterations: int = 20) -> dict:
    return {...}
```

Then replace repeated kwargs blocks in `init_enhanced_rg_rho_lns_fast`, `nr_rg_rho_lns`, and `nr_rg_rho_lns_small_oracle` with the helper.

- [ ] **Step 4: Verify targeted tests**

Run:

```bash
cd /Volumes/siwen_硬盘/论文/0326/paper0520/sl_isp_rg_rho_lns
python3 -m pytest tests/test_rho_projection.py::test_nr_rg_rho_lns_kwargs_maps_shared_parameters tests/test_rho_projection.py::test_pilot_factory_passes_rollout_portfolio_limits -q
```

Expected: tests pass.

### Task 4: Full Verification And Diagnostics

**Files:**
- Generated: `sl_isp_rg_rho_lns/outputs/medium40_comparison_20260527/rollout_candidate_diagnostics.csv`
- Generated: `sl_isp_rg_rho_lns/outputs/medium80_comparison_20260527/rollout_candidate_diagnostics.csv`

- [ ] **Step 1: Run full tests**

Run:

```bash
cd /Volumes/siwen_硬盘/论文/0326/paper0520/sl_isp_rg_rho_lns
python3 -m pytest
```

Expected: all tests pass.

- [ ] **Step 2: Generate rollout diagnostics**

Run:

```bash
cd /Volumes/siwen_硬盘/论文/0326/paper0520/sl_isp_rg_rho_lns
python3 -m src.analysis.rollout_portfolio_diagnostics outputs/medium40_comparison_20260527/nr_rollout_portfolio.csv outputs/medium40_comparison_20260527/rollout_candidate_diagnostics.csv
python3 -m src.analysis.rollout_portfolio_diagnostics outputs/medium80_comparison_20260527/nr_rollout_portfolio.csv outputs/medium80_comparison_20260527/rollout_candidate_diagnostics.csv
```

Expected: both CSVs are written with per-candidate diagnostic rows.
