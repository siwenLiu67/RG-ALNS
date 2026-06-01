"""SCI-style figures for RG-RHO-LNS-Fast v1.0 paper experiments.

Requires: matplotlib (pip install matplotlib)
"""

import csv
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker
    _HAS_MPL = True
except ImportError:
    _HAS_MPL = False
    print("WARNING: matplotlib not available. Install with: pip install matplotlib")


SCI_COLORS = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
              '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
              '#aec7e8', '#ffbb78', '#98df8a']
ALGO_ORDER = ["EDD", "SPT", "WSPT", "ATC", "Service-Weighted", "Shortfall-Greedy",
              "Plain-RHO-Fast", "RG-RHO-Fast", "RHO-LNS-Fast",
              "ILS-Fast", "VNS-Fast", "TS-Fast", "RG-RHO-LNS-Fast"]
ALGO_SHORT = {"Service-Weighted": "SWD", "Shortfall-Greedy": "SFG",
              "Plain-RHO-Fast": "Plain-RHO", "RG-RHO-Fast": "RG-RHO",
              "RHO-LNS-Fast": "RHO-LNS", "ILS-Fast": "ILS",
              "VNS-Fast": "VNS", "TS-Fast": "TS",
              "RG-RHO-LNS-Fast": "RG-LNS"}

DPI = 300
OUTPUT_DIR = "outputs/paper_experiments/figures"


def setup_style():
    plt.rcParams.update({
        'font.size': 9, 'axes.titlesize': 10, 'axes.labelsize': 9,
        'xtick.labelsize': 8, 'ytick.labelsize': 8, 'legend.fontsize': 7,
        'figure.dpi': DPI, 'savefig.dpi': DPI,
        'font.family': 'sans-serif',
    })


def short_label(name):
    return ALGO_SHORT.get(name, name)


def get_algo_color(algo):
    if algo in ALGO_ORDER:
        return SCI_COLORS[ALGO_ORDER.index(algo) % len(SCI_COLORS)]
    return '#333333'


def read_csv(path):
    with open(path, "r", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def fig1_overall_z(ok_rows, output_dir):
    """Overall Z comparison across all algorithms (bar chart)."""
    if not _HAS_MPL:
        return
    by_algo = defaultdict(list)
    for r in ok_rows:
        by_algo[r["algorithm_label"]].append(float(r["Z"]))

    algos = [a for a in ALGO_ORDER if a in by_algo]
    means = [sum(by_algo[a]) / len(by_algo[a]) for a in algos]
    sds = [math.sqrt(sum((v - means[i])**2 for v in by_algo[a]) / max(1, len(by_algo[a]) - 1))
           for i, a in enumerate(algos)]
    colors = [get_algo_color(a) for a in algos]
    labels = [short_label(a) for a in algos]

    fig, ax = plt.subplots(figsize=(10, 4))
    bars = ax.bar(range(len(algos)), means, yerr=sds, color=colors, capsize=3, edgecolor='white')
    ax.set_xticks(range(len(algos)))
    ax.set_xticklabels(labels, rotation=45, ha='right')
    ax.set_ylabel('Mean Z (lower is better)')
    ax.set_title('Overall Z Comparison')

    # Highlight proposed
    if "RG-RHO-LNS-Fast" in algos:
        idx = algos.index("RG-RHO-LNS-Fast")
        bars[idx].set_edgecolor('black')
        bars[idx].set_linewidth(2)

    fig.tight_layout()
    for ext in ['png', 'pdf']:
        fig.savefig(f"{output_dir}/fig1_overall_Z.{ext}", bbox_inches='tight')
    plt.close(fig)


def fig2_tt_wsf_bars(ok_rows, output_dir):
    """Stacked bar: TT + WSF per algorithm."""
    if not _HAS_MPL:
        return
    by_algo = defaultdict(lambda: defaultdict(list))
    for r in ok_rows:
        a = r["algorithm_label"]
        by_algo[a]["TT"].append(float(r["TT"]))
        by_algo[a]["WSF"].append(float(r["WSF"]))

    algos = [a for a in ALGO_ORDER if a in by_algo]
    tt_means = [sum(by_algo[a]["TT"]) / len(by_algo[a]["TT"]) for a in algos]
    wsf_means = [sum(by_algo[a]["WSF"]) / len(by_algo[a]["WSF"]) for a in algos]

    fig, ax = plt.subplots(figsize=(10, 4))
    x = range(len(algos))
    ax.bar(x, tt_means, label='TT (Tardiness)', color='#d62728', edgecolor='white')
    ax.bar(x, wsf_means, bottom=tt_means, label='WSF (Service Shortfall)', color='#1f77b4', edgecolor='white')
    ax.set_xticks(x)
    ax.set_xticklabels([short_label(a) for a in algos], rotation=45, ha='right')
    ax.set_ylabel('Mean Value')
    ax.set_title('Objective Decomposition: TT + WSF')
    ax.legend()
    fig.tight_layout()
    for ext in ['png', 'pdf']:
        fig.savefig(f"{output_dir}/fig2_tt_wsf_decomposition.{ext}", bbox_inches="tight")
    plt.close(fig)


def fig3_pressure_z(ok_rows, output_dir):
    """Pressure-level Z comparison (grouped bar)."""
    if not _HAS_MPL:
        return
    pressures = ["medium", "high", "very_high"]
    by_pa = defaultdict(lambda: defaultdict(list))
    for r in ok_rows:
        by_pa[(r["pressure_level"], r["algorithm_label"])]["Z"].append(float(r["Z"]))

    algos = [a for a in ALGO_ORDER if any((p, a) in by_pa for p in pressures)]
    x = range(len(algos))
    width = 0.25

    fig, ax = plt.subplots(figsize=(10, 4))
    for i, pressure in enumerate(pressures):
        means = []
        for a in algos:
            vals = by_pa.get((pressure, a), {}).get("Z", [0])
            means.append(sum(vals) / len(vals) if vals else 0)
        ax.bar([xi + i * width for xi in x], means, width, label=pressure.capitalize())

    ax.set_xticks([xi + width for xi in x])
    ax.set_xticklabels([short_label(a) for a in algos], rotation=45, ha='right')
    ax.set_ylabel('Mean Z')
    ax.set_title('Pressure-Level Z Comparison')
    ax.legend()
    fig.tight_layout()
    for ext in ['png', 'pdf']:
        fig.savefig(f"{output_dir}/fig3_pressure_Z.{ext}", bbox_inches="tight")
    plt.close(fig)


def fig5_ablation(ok_rows, output_dir):
    """Ablation study Z comparison."""
    if not _HAS_MPL:
        return
    variants = ["Plain-RHO-Fast", "RG-RHO-Fast", "RHO-LNS-Fast", "RG-RHO-LNS-Fast"]
    by_algo = defaultdict(list)
    for r in ok_rows:
        if r["algorithm_label"] in variants:
            by_algo[r["algorithm_label"]].append(float(r["Z"]))

    means = [sum(by_algo[v]) / len(by_algo[v]) for v in variants if v in by_algo]
    labels = [short_label(v) for v in variants if v in by_algo]

    fig, ax = plt.subplots(figsize=(5, 3.5))
    colors = ['#7f7f7f', '#ff7f0e', '#1f77b4', '#2ca02c']
    ax.bar(range(len(labels)), means, color=colors[:len(labels)], edgecolor='white')
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels)
    ax.set_ylabel('Mean Z')
    ax.set_title('Ablation Study')
    fig.tight_layout()
    for ext in ['png', 'pdf']:
        fig.savefig(f"{output_dir}/fig5_ablation.{ext}", bbox_inches="tight")
    plt.close(fig)


def fig6_convergence(conv_path, output_dir):
    """Convergence curve: best-so-far Z vs iteration."""
    if not _HAS_MPL or not os.path.exists(conv_path):
        return
    rows = read_csv(conv_path)

    # Aggregate by algorithm and iteration
    by_algo_iter = defaultdict(lambda: defaultdict(list))
    for r in rows:
        try:
            it = int(r["iteration"])
            z = float(r["best_so_far_Z"])
            by_algo_iter[r["algorithm_label"]][it].append(z)
        except (ValueError, KeyError):
            continue

    fig, ax = plt.subplots(figsize=(6, 4))
    for algo in ["RHO-LNS-Fast", "RG-RHO-LNS-Fast", "ILS-Fast", "VNS-Fast", "TS-Fast"]:
        iter_data = by_algo_iter.get(algo, {})
        if not iter_data:
            continue
        iters = sorted(iter_data.keys())[:30]  # cap at 30
        means = [sum(iter_data[i]) / len(iter_data[i]) for i in iters]
        ax.plot(iters, means, label=short_label(algo), color=get_algo_color(algo), linewidth=1.5)

    ax.set_xlabel('Iteration')
    ax.set_ylabel('Best-so-far Z')
    ax.set_title('Convergence: Best-so-far Z vs Iteration')
    ax.legend()
    fig.tight_layout()
    for ext in ['png', 'pdf']:
        fig.savefig(f"{output_dir}/fig6_convergence.{ext}", bbox_inches="tight")
    plt.close(fig)


def fig8_operator_contribution(op_path, output_dir):
    """Operator contribution: success rate and mean improvement."""
    if not _HAS_MPL or not os.path.exists(op_path):
        return
    rows = read_csv(op_path)
    by_op = defaultdict(lambda: {"usage": 0, "improvements": 0, "total_mag": 0.0, "count_mag": 0})
    for r in rows:
        name = r["operator_name"]
        by_op[name]["usage"] += int(r["usage_count"])
        by_op[name]["improvements"] += int(r["improvement_count"])
        mag = float(r["total_improvement"])
        cnt = int(r["improvement_count"])
        if cnt > 0:
            by_op[name]["total_mag"] += mag
            by_op[name]["count_mag"] += cnt

    names = sorted(by_op)
    success_rates = [by_op[n]["improvements"] / max(1, by_op[n]["usage"]) for n in names]
    magnitudes = [by_op[n]["total_mag"] / max(1, by_op[n]["count_mag"]) for n in names]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9, 3.5))
    ax1.barh(range(len(names)), success_rates, color='#1f77b4', edgecolor='white')
    ax1.set_yticks(range(len(names)))
    ax1.set_yticklabels(names, fontsize=7)
    ax1.set_xlabel('Success Rate')
    ax1.set_title('Operator Success Rate')

    ax2.barh(range(len(names)), magnitudes, color='#2ca02c', edgecolor='white')
    ax2.set_yticks(range(len(names)))
    ax2.set_yticklabels([])
    ax2.set_xlabel('Mean Improvement Magnitude')
    ax2.set_title('Operator Improvement Magnitude')

    fig.tight_layout()
    for ext in ['png', 'pdf']:
        fig.savefig(f"{output_dir}/fig8_operator_contribution.{ext}", bbox_inches="tight")
    plt.close(fig)


def fig10_runtime(ok_rows, output_dir):
    """Runtime comparison, log scale."""
    if not _HAS_MPL:
        return
    by_algo = defaultdict(list)
    for r in ok_rows:
        by_algo[r["algorithm_label"]].append(float(r["runtime_total_s"]))

    algos = [a for a in ALGO_ORDER if a in by_algo]
    means = [sum(by_algo[a]) / len(by_algo[a]) for a in algos]

    fig, ax = plt.subplots(figsize=(8, 4))
    bars = ax.bar(range(len(algos)), [max(m, 1e-5) for m in means], color=[get_algo_color(a) for a in algos])
    ax.set_yscale('log')
    ax.set_xticks(range(len(algos)))
    ax.set_xticklabels([short_label(a) for a in algos], rotation=45, ha='right')
    ax.set_ylabel('Runtime (s, log scale)')
    ax.set_title('Runtime Comparison')
    fig.tight_layout()
    for ext in ['png', 'pdf']:
        fig.savefig(f"{output_dir}/fig10_runtime.{ext}", bbox_inches="tight")
    plt.close(fig)


def fig_sensitivity(sensitivity_path, output_dir):
    """Parameter sensitivity curves."""
    if not _HAS_MPL or not os.path.exists(sensitivity_path):
        return
    rows = read_csv(sensitivity_path)
    params = ["rg_repair_prob", "rg_destroy_prob", "lns_iterations", "destroy_fraction"]
    param_labels = {
        "rg_repair_prob": "RG-priority repair probability",
        "rg_destroy_prob": "RG-biased destroy probability",
        "lns_iterations": "LNS iterations",
        "destroy_fraction": "Destroy fraction",
    }

    fig, axes = plt.subplots(2, 2, figsize=(8, 6))
    for ax, param in zip(axes.flat, params):
        by_val = defaultdict(list)
        for r in rows:
            if r["parameter"] == param:
                by_val[float(r["value"])].append(float(r["Z"]))
        x = sorted(by_val.keys())
        y = [sum(by_val[v]) / len(by_val[v]) for v in x]
        ax.plot(x, y, 'o-', color='#1f77b4', markersize=6)
        ax.set_xlabel(param_labels.get(param, param))
        ax.set_ylabel('Mean Z')
        ax.grid(True, alpha=0.3)

    fig.suptitle('Parameter Sensitivity Analysis')
    fig.tight_layout()
    for ext in ['png', 'pdf']:
        fig.savefig(f"{output_dir}/fig_sensitivity.{ext}", bbox_inches="tight")
    plt.close(fig)


# ═══════════════════════════════════════════════════════════════════════════════

def main(input_path, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    ok_rows = read_csv(input_path)
    ok_rows = [r for r in ok_rows if r["status"] == "OK"]

    if not _HAS_MPL:
        print("matplotlib not installed. Skipping figures.")
        return

    setup_style()
    print("Generating figures...")

    fig1_overall_z(ok_rows, output_dir)
    print("  fig1: Overall Z comparison")

    fig2_tt_wsf_bars(ok_rows, output_dir)
    print("  fig2: TT+WSF decomposition")

    fig3_pressure_z(ok_rows, output_dir)
    print("  fig3: Pressure-level Z")

    fig5_ablation(ok_rows, output_dir)
    print("  fig5: Ablation study")

    conv_path = os.path.join(os.path.dirname(output_dir), "convergence_raw.csv")
    if not os.path.exists(conv_path):
        conv_path = os.path.join(os.path.dirname(output_dir) if os.path.dirname(output_dir) != 'outputs/paper_experiments/figures' else 'outputs/paper_experiments', "convergence_raw.csv")
    # Fix path
    paper_dir = output_dir.replace("/figures", "").replace("\\figures", "")
    conv_path = os.path.join(paper_dir, "convergence_raw.csv")

    fig6_convergence(conv_path, output_dir)
    print("  fig6: Convergence curves")

    op_path = os.path.join(paper_dir, "diagnostics_operator_success.csv")
    fig8_operator_contribution(op_path, output_dir)
    print("  fig8: Operator contribution")

    fig10_runtime(ok_rows, output_dir)
    print("  fig10: Runtime comparison")

    sens_path = os.path.join(paper_dir, "sensitivity_raw.csv")
    fig_sensitivity(sens_path, output_dir)
    print("  fig_sensitivity: Parameter sensitivity")

    print(f"\nAll figures saved to {output_dir}/")


if __name__ == "__main__":
    input_path = sys.argv[1] if len(sys.argv) > 1 else "outputs/paper_experiments/expanded_sota_raw.csv"
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "outputs/paper_experiments/figures"
    main(input_path, output_dir)
