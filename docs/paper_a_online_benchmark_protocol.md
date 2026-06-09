# Paper A Online Benchmark Protocol

All algorithms in the main comparison are evaluated under the same online event-driven simulation protocol. At each event time, an algorithm observes only arrived jobs, completed and ongoing operations, current machine states, and entity-level service parameters. Future jobs are not visible at the job level before arrival. Algorithms may generate internal local or rolling schedules, but only operations that are immediately executable at the current event time are committed to the simulator. The final performance is evaluated using the same global objective after the simulation terminates.

The main online table includes only algorithms with `online_visibility: true` and current-time commit validation. Offline or oracle variants, such as `Offline-Legacy-RG-ALNS`, are reported separately as ablation references and are not included in the main fair online comparison.

Example command:

```bash
python scripts/run_paper_a_online_benchmark.py \
  --config configs/paper_a_online.yaml \
  --seeds 0 1 2 \
  --output results/paper_a_online/
```
