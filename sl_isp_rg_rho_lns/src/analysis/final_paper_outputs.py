"""Generate all paper-ready tables and figures for NR-RG-RHO-LNS final validation.

Usage: python -m src.analysis.final_paper_outputs [input_dir]

Input: outputs/final_v13_validation/final_raw.csv (and optional diagnostics CSVs)
Output: outputs/final_v13_validation/tables/ and outputs/final_v13_validation/figures/
"""

import csv, math, os, sys, json, time
from collections import defaultdict, Counter
from pathlib import Path

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

try:
    from scipy.stats import wilcoxon
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

# ── Config ──────────────────────────────────────────────────────────────────

DPI = 300
SCI_COLORS = ['#1f77b4','#ff7f0e','#2ca02c','#d62728','#9467bd','#8c564b',
              '#e377c2','#7f7f7f','#bcbd22','#17becf','#aec7e8','#ffbb78','#98df8a']
ALGOS = ["EDD","SPT","WSPT","ATC","Service-Weighted","Shortfall-Greedy",
         "Plain-RHO-Fast","RHO-LNS-Fast","Adaptive-RG-v1.2",
         "ILS-Fast","VNS-Fast","TS-Fast","NR-RG-RHO-LNS"]
SHORT = {"Service-Weighted":"SWD","Shortfall-Greedy":"SFG",
         "Plain-RHO-Fast":"Plain-RHO","RHO-LNS-Fast":"RHO-LNS",
         "Adaptive-RG-v1.2":"Adap-RG","ILS-Fast":"ILS",
         "VNS-Fast":"VNS","TS-Fast":"TS","NR-RG-RHO-LNS":"NR-RG-LNS"}
CATEGORY = {"EDD":"Disp.","SPT":"Disp.","WSPT":"Disp.","ATC":"Disp.",
            "Service-Weighted":"Service","Shortfall-Greedy":"Service",
            "Plain-RHO-Fast":"RH","RHO-LNS-Fast":"LNS",
            "Adaptive-RG-v1.2":"RG","ILS-Fast":"Meta.","VNS-Fast":"Meta.",
            "TS-Fast":"Meta.","NR-RG-RHO-LNS":"Prop."}
REPR_ALGOS = ["SPT","RHO-LNS-Fast","VNS-Fast","TS-Fast","NR-RG-RHO-LNS"]


# ── Helpers ─────────────────────────────────────────────────────────────────

def read_csv(p): return list(csv.DictReader(open(p, encoding='utf-8')))

def write_csv(p, rows):
    if not rows: return
    os.makedirs(Path(p).parent, exist_ok=True)
    keys = list(rows[0].keys())
    with open(p,'w',newline='',encoding='utf-8') as f:
        w = csv.DictWriter(f, keys); w.writeheader(); w.writerows(rows)

def write_md(p, title, rows):
    if not rows: return
    keys = list(rows[0].keys())
    lines = [title, "", "| " + " | ".join(keys) + " |",
             "|" + "|".join(["---"]*len(keys)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(k,"")) for k in keys) + " |")
    with open(p,'w',encoding='utf-8') as f: f.write("\n".join(lines))

def std(vals):
    n=len(vals)
    if n<2: return 0.0
    m=sum(vals)/n; return math.sqrt(sum((v-m)**2 for v in vals)/(n-1))

def wilcoxon_p(x,y):
    if not HAS_SCIPY or len(x)<3: return None
    try: return float(wilcoxon(x,y,zero_method='zsplit')[1])
    except: return None

def cohens_d(x,y):
    n=len(x)
    if n<2: return 0.0
    diffs=[x[i]-y[i] for i in range(n)]
    md=sum(diffs)/n
    vd=sum((d-md)**2 for d in diffs)/max(1,n-1)
    return md/math.sqrt(max(vd,1e-9))

def setup_style():
    if not HAS_MPL: return
    plt.rcParams.update({'font.size':8,'axes.titlesize':9,'axes.labelsize':8,
        'xtick.labelsize':7,'ytick.labelsize':7,'legend.fontsize':6,
        'figure.dpi':DPI,'savefig.dpi':DPI})

def savefig(fig, name, out_dir):
    for ext in ['png','pdf']:
        fig.savefig(f'{out_dir}/{name}.{ext}', bbox_inches='tight')
    plt.close(fig)

def get_color(algo):
    if algo in ALGOS: return SCI_COLORS[ALGOS.index(algo)%len(SCI_COLORS)]
    return '#333333'


# ── Paired test helper ──────────────────────────────────────────────────────

def paired_test(rows, a, b, metric='Z'):
    ad,bd={},{}
    for r in rows:
        if r['status']!='OK': continue
        k=(r['pressure_level'],r['instance_index'],r['seed_index'])
        if r['algorithm_label']==a: ad[k]=float(r[metric])
        elif r['algorithm_label']==b: bd[k]=float(r[metric])
    common=sorted(set(ad)&set(bd))
    av=[ad[k] for k in common]; bv=[bd[k] for k in common]
    n=len(common)
    if n<2: return {'n':n}
    deltas=[av[i]-bv[i] for i in range(n)]
    md=sum(deltas)/n; sd=sorted(deltas)
    return {'n':n,'mean_a':sum(av)/n,'mean_b':sum(bv)/n,
            'mean_delta':md,'median_delta':sd[n//2],
            'win_rate':sum(1 for d in deltas if d<0)/n,
            'tie_rate':sum(1 for d in deltas if abs(d)<1e-9)/n,
            'cohens_d':cohens_d(av,bv),'wilcoxon_p':wilcoxon_p(av,bv)}


# ═══════════════════════════════════════════════════════════════════════════════
# TABLES
# ═══════════════════════════════════════════════════════════════════════════════

def gen_all_tables(ok_rows, out_dir):
    tables_dir = os.path.join(out_dir, 'tables')
    os.makedirs(tables_dir, exist_ok=True)
    gen_t1(tables_dir)
    gen_t2(tables_dir)
    gen_t3(ok_rows, tables_dir)
    gen_t4(ok_rows, tables_dir)
    gen_t5(ok_rows, tables_dir)
    gen_t6(ok_rows, tables_dir)
    gen_t7(ok_rows, tables_dir)
    gen_t8(out_dir, tables_dir)
    gen_t9(ok_rows, tables_dir)
    print(f"All tables → {tables_dir}/")

def gen_t1(out_dir):
    rows = [
        {"Parameter":"Instances","Value":"36 (3 pressure × 3 machine × 4 job levels)"},
        {"Parameter":"Jobs per instance","Value":"40, 80, 120, 160"},
        {"Parameter":"Machines per instance","Value":"5, 10, 15"},
        {"Parameter":"Service entities","Value":"3–10 (scales with job count)"},
        {"Parameter":"Operations per job","Value":"2–4 (uniform random)"},
        {"Parameter":"Processing time","Value":"[10, 50]"},
        {"Parameter":"Transport delay","Value":"[10, 40]"},
        {"Parameter":"Pressure levels (ρ)","Value":"Medium [0.75,0.85], High [0.85,0.95], Very-High [0.95,0.99]"},
        {"Parameter":"Deadline tightness","Value":"1.0 / 0.5 / 0.25"},
        {"Parameter":"Arrival pattern","Value":"Dynamic (medium intensity: 50% at t=0, 50% spread)"},
        {"Parameter":"Weight pattern","Value":"mild"},
        {"Parameter":"Objective","Value":"Z = α·TT + β·WSF, α=1.0, β=1.0"},
        {"Parameter":"Seeds per instance","Value":"3 (matched)"},
        {"Parameter":"Algorithms","Value":"13"},
        {"Parameter":"Total runs","Value":"1404"},
        {"Parameter":"Implementation","Value":"Solver-free (no CP-SAT, OR-Tools, MILP)"},
    ]
    write_csv(f"{out_dir}/table1_experimental_settings.csv", rows)
    write_md(f"{out_dir}/table1_experimental_settings.md","Table 1: Experimental settings.", rows)

def gen_t2(out_dir):
    main_idea = {
        "EDD":"Earliest deadline first","SPT":"Shortest processing time first",
        "WSPT":"Weighted shortest processing time",
        "ATC":"Apparent tardiness cost with look-ahead",
        "Service-Weighted":"Service-weight-based priority",
        "Shortfall-Greedy":"Direct shortfall-driven greedy dispatch",
        "Plain-RHO-Fast":"EDF greedy construction only, no LNS",
        "RHO-LNS-Fast":"EDF construction + unbiased LNS + local search",
        "Adaptive-RG-v1.2":"EDF construction + adaptive RG LNS",
        "ILS-Fast":"Iterated local search with perturbation + LS",
        "VNS-Fast":"Variable neighborhood search with VND",
        "TS-Fast":"Tabu search with swap neighborhood + aspiration",
        "NR-RG-RHO-LNS":"No-regret multi-start init + adaptive RG LNS + tabu",
    }
    rows = []
    for a in ALGOS:
        has_rh = "No" if a in ["EDD","SPT","WSPT","ATC","Service-Weighted","Shortfall-Greedy"] else "Yes"
        has_meta = "Yes" if a in ["ILS-Fast","VNS-Fast","TS-Fast"] else ("Yes" if "LNS" in a else "No")
        has_rg = "Yes" if "RG" in a else "No"
        rows.append({"Algorithm":a,"Category":CATEGORY[a],"Main mechanism":main_idea.get(a,""),
                     "RH":has_rh,"Meta/LNS":has_meta,"RG":has_rg,"Solver-free":"Yes"})
    write_csv(f"{out_dir}/table2_algorithm_classification.csv", rows)
    write_md(f"{out_dir}/table2_algorithm_classification.md","Table 2: Algorithm classification.", rows)

def gen_t3(ok, out_dir):
    """Split overall comparison into 3 sub-tables by algorithm category.

    T3a: Dispatching rules (EDD, SPT, WSPT, ATC, SWD, SFG)
    T3b: LNS ablation chain (Plain-RHO, RHO-LNS, Adaptive-RG, NR-RG-RHO-LNS)
    T3c: Adapted metaheuristic baselines (ILS, VNS, TS)
    """
    by_a = defaultdict(lambda: defaultdict(list))
    for r in ok:
        for m in ['Z','TT','WSF','ZSR','runtime_total_s']:
            by_a[r['algorithm_label']][m].append(float(r[m]))

    def _rows(algo_list):
        out = []
        for a in algo_list:
            d = by_a[a]; n = len(d['Z'])
            if n==0: continue
            out.append({"Algorithm":a,"N":n,
                "Z_mean":f"{sum(d['Z'])/n:.1f}","Z_sd":f"{std(d['Z']):.1f}",
                "TT_mean":f"{sum(d['TT'])/n:.1f}","WSF_mean":f"{sum(d['WSF'])/n:.1f}",
                "ZSR_mean":f"{sum(d['ZSR'])/n:.3f}","Runtime_s":f"{sum(d['runtime_total_s'])/n:.4f}"})
        return out

    # T3a
    r3a = _rows(["EDD","SPT","WSPT","ATC","Service-Weighted","Shortfall-Greedy"])
    write_csv(f"{out_dir}/table3a_dispatching_rules.csv", r3a)
    write_md(f"{out_dir}/table3a_dispatching_rules.md",
             "Table 3a: Overall comparison — dispatching & service-oriented rules.", r3a)

    # T3b
    r3b = _rows(["Plain-RHO-Fast","RHO-LNS-Fast","Adaptive-RG-v1.2","NR-RG-RHO-LNS"])
    write_csv(f"{out_dir}/table3b_lns_ablation.csv", r3b)
    write_md(f"{out_dir}/table3b_lns_ablation.md",
             "Table 3b: Overall comparison — LNS ablation chain.", r3b)

    # T3c
    r3c = _rows(["ILS-Fast","VNS-Fast","TS-Fast"])
    write_csv(f"{out_dir}/table3c_metaheuristics.csv", r3c)
    write_md(f"{out_dir}/table3c_metaheuristics.md",
             "Table 3c: Overall comparison — adapted representative metaheuristic baselines.", r3c)

def gen_t4(ok, out_dir):
    by_pa = defaultdict(lambda: defaultdict(list))
    for r in ok:
        key = (r['pressure_level'], r['algorithm_label'])
        for m in ['Z','TT','WSF','ZSR']: by_pa[key][m].append(float(r[m]))
    rows = []
    for pressure in ['medium','high','very_high']:
        for a in ALGOS:
            d = by_pa[(pressure,a)]
            if not d['Z']: continue
            n = len(d['Z'])
            rows.append({"Pressure":pressure,"Algorithm":a,
                "Z_mean":f"{sum(d['Z'])/n:.1f}","TT_mean":f"{sum(d['TT'])/n:.1f}",
                "WSF_mean":f"{sum(d['WSF'])/n:.1f}","ZSR_mean":f"{sum(d['ZSR'])/n:.3f}"})
    write_csv(f"{out_dir}/table4_pressure.csv", rows)
    write_md(f"{out_dir}/table4_pressure.md","Table 4: Pressure-level comparison.", rows)

def gen_t5(ok, out_dir):
    baselines = [a for a in ALGOS if a != "NR-RG-RHO-LNS"]
    rows = []
    for bl in baselines:
        pc = paired_test(ok, "NR-RG-RHO-LNS", bl)
        if pc.get('n',0)<2: continue
        p = pc.get('wilcoxon_p')
        rows.append({"Baseline":bl,"N":pc['n'],
            "Mean_ΔZ":f"{pc['mean_delta']:.2f}","Median_ΔZ":f"{pc['median_delta']:.2f}",
            "Win_rate":f"{pc['win_rate']:.3f}",
            "p-value":f"{p:.4f}" if p is not None else "N/A",
            "Cohen's_d":f"{pc['cohens_d']:.3f}"})
    write_csv(f"{out_dir}/table5_paired_tests.csv", rows)
    write_md(f"{out_dir}/table5_paired_tests.md","Table 5: Paired statistical tests (NR-RG-RHO-LNS vs baselines).", rows)

    # T5b: by pressure
    pp_rows = []
    for pressure in ['medium','high','very_high']:
        pr = [r for r in ok if r['pressure_level']==pressure]
        for bl in baselines:
            pc = paired_test(pr, "NR-RG-RHO-LNS", bl)
            if pc.get('n',0)<2: continue
            p = pc.get('wilcoxon_p')
            pp_rows.append({"Pressure":pressure,"Baseline":bl,
                "Mean_ΔZ":f"{pc['mean_delta']:.2f}","Win_rate":f"{pc['win_rate']:.3f}",
                "p-value":f"{p:.4f}" if p is not None else "N/A"})
    write_csv(f"{out_dir}/table5b_paired_by_pressure.csv", pp_rows)
    write_md(f"{out_dir}/table5b_paired_by_pressure.md","Table 5b: Paired tests by pressure.", pp_rows)

def gen_t6(ok, out_dir):
    """Ablation: estimated from Plain-RHO-Fast, RHO-LNS-Fast, Adaptive-RG-v1.2, NR-RG-RHO-LNS."""
    variants = {
        "EDF-only":"Plain-RHO-Fast",
        "EDF + unbiased LNS":"RHO-LNS-Fast",
        "Adaptive RG":"Adaptive-RG-v1.2",
        "Multi-start + adaptive RG + tabu + tol":"NR-RG-RHO-LNS",
    }
    by_a = defaultdict(lambda: defaultdict(list))
    for r in ok:
        a = r['algorithm_label']
        for m in ['Z','TT','WSF']: by_a[a][m].append(float(r[m]))
    base_z = sum(by_a["Plain-RHO-Fast"]['Z'])/max(1,len(by_a["Plain-RHO-Fast"]['Z']))
    rows = []
    for desc, label in variants.items():
        d = by_a[label]; n = len(d['Z'])
        if n==0: continue
        z = sum(d['Z'])/n
        rows.append({"Variant":desc,"Label":label,"Z_mean":f"{z:.1f}",
            "TT_mean":f"{sum(d['TT'])/n:.1f}","WSF_mean":f"{sum(d['WSF'])/n:.1f}",
            "Δ_vs_EDF":f"{(base_z-z)/max(1,base_z)*100:.1f}%"})
    write_csv(f"{out_dir}/table6_ablation.csv", rows)
    write_md(f"{out_dir}/table6_ablation.md","Table 6: Ablation study.", rows)

def gen_t7(ok, out_dir):
    """Scalability: relative gap to best per instance."""
    by_inst = defaultdict(lambda: defaultdict(dict))
    for r in ok:
        k = (r['pressure_level'], r['instance_index'], r['seed_index'])
        by_inst[k][r['algorithm_label']] = float(r['Z'])
    # For each instance, find best Z
    scal_data = defaultdict(lambda: defaultdict(list))
    for k, algos_z in by_inst.items():
        best_z = min(algos_z.values())
        for a, z in algos_z.items():
            scal_data[a]['gap_to_best'].append(z - best_z)
            scal_data[a]['raw_z'].append(z)
    rows = []
    for a in ALGOS:
        d = scal_data[a]
        if not d['raw_z']: continue
        n = len(d['raw_z'])
        rows.append({"Algorithm":a,"N":n,
            "Mean_gap_to_best":f"{sum(d['gap_to_best'])/n:.1f}",
            "Mean_Z":f"{sum(d['raw_z'])/n:.1f}"})
    write_csv(f"{out_dir}/table7_scalability.csv", rows)
    write_md(f"{out_dir}/table7_scalability.md","Table 7: Scalability analysis (relative gap to best).", rows)

def gen_t8(base_dir, out_dir):
    op_path = os.path.join(base_dir, "diagnostics_operator_success.csv")
    if not os.path.exists(op_path): return
    rows = read_csv(op_path)
    by_op = defaultdict(lambda: {"usage":0,"impr":0,"mag":0.0,"cnt":0})
    for r in rows:
        n = r['operator_name']; by_op[n]["usage"] += int(r['usage_count'])
        by_op[n]["impr"] += int(r['improvement_count'])
        m = float(r['total_improvement']); c = int(r['improvement_count'])
        if c>0: by_op[n]["mag"]+=m; by_op[n]["cnt"]+=c
    out_rows = []
    for n in sorted(by_op):
        d = by_op[n]; u = d['usage']
        out_rows.append({"Operator":n,"Usage":u,
            "Success_rate":f"{d['impr']/max(1,u):.3f}",
            "Mean_ΔZ":f"{d['mag']/max(1,d['cnt']):.1f}"})
    write_csv(f"{out_dir}/table8_operator_contribution.csv", out_rows)
    write_md(f"{out_dir}/table8_operator_contribution.md","Table 8: Operator contribution.", out_rows)

def gen_t9(ok, out_dir):
    by_a = defaultdict(list)
    for r in ok: by_a[r['algorithm_label']].append(float(r['runtime_total_s']))
    rows = []
    for a in ALGOS:
        rts = by_a[a]
        if not rts: continue
        rows.append({"Algorithm":a,
            "Mean_runtime_s":f"{sum(rts)/len(rts):.4f}",
            "Max_runtime_s":f"{max(rts):.4f}"})
    write_csv(f"{out_dir}/table9_runtime.csv", rows)
    write_md(f"{out_dir}/table9_runtime.md","Table 9: Runtime / budget.", rows)


# ═══════════════════════════════════════════════════════════════════════════════
# FIGURES
# ═══════════════════════════════════════════════════════════════════════════════

def gen_all_figures(ok_rows, base_dir, out_dir):
    if not HAS_MPL:
        print("matplotlib not installed. Skipping figures.")
        return
    setup_style()
    figs_dir = os.path.join(out_dir, 'figures')
    os.makedirs(figs_dir, exist_ok=True)
    fig1(ok_rows, figs_dir)
    fig2(ok_rows, figs_dir)
    fig3(ok_rows, figs_dir)
    fig4(ok_rows, figs_dir)
    fig5(ok_rows, figs_dir)
    fig6(base_dir, figs_dir)
    fig7(base_dir, figs_dir)
    fig8(ok_rows, figs_dir)
    fig9(ok_rows, figs_dir)
    fig10(base_dir, figs_dir)
    fig11(figs_dir)
    print(f"All figures → {figs_dir}/")

def by_algo_metric(ok):
    b = defaultdict(lambda: defaultdict(list))
    for r in ok:
        for m in ['Z','TT','WSF']: b[r['algorithm_label']][m].append(float(r[m]))
    return b

def fig1(ok, out_dir):
    b = by_algo_metric(ok)
    existing = [a for a in ALGOS if a in b]
    means = [sum(b[a]['Z'])/len(b[a]['Z']) for a in existing]
    sds = [std(b[a]['Z']) for a in existing]
    fig, ax = plt.subplots(figsize=(11,4.5))
    bars = ax.bar(range(len(existing)), means, yerr=sds,
                  color=[get_color(a) for a in existing], capsize=2, edgecolor='white')
    ax.set_xticks(range(len(existing)))
    ax.set_xticklabels([SHORT.get(a,a) for a in existing], rotation=40, ha='right')
    ax.set_ylabel('Mean Z'); ax.set_title('Overall Z Comparison')
    if 'NR-RG-RHO-LNS' in existing:
        idx = existing.index('NR-RG-RHO-LNS')
        bars[idx].set_edgecolor('black'); bars[idx].set_linewidth(2)
    fig.tight_layout(); savefig(fig,'fig1_overall_Z',out_dir)

def fig2(ok, out_dir):
    b = by_algo_metric(ok)
    existing = [a for a in ALGOS if a in b]
    tt = [sum(b[a]['TT'])/len(b[a]['TT']) for a in existing]
    wsf = [sum(b[a]['WSF'])/len(b[a]['WSF']) for a in existing]
    fig, ax = plt.subplots(figsize=(11,4.5))
    x = range(len(existing))
    ax.bar(x, tt, label='TT (Tardiness)', color='#d62728', edgecolor='white')
    ax.bar(x, wsf, bottom=tt, label='WSF (Service Shortfall)', color='#1f77b4', edgecolor='white')
    ax.set_xticks(x); ax.set_xticklabels([SHORT.get(a,a) for a in existing], rotation=40, ha='right')
    ax.set_ylabel('Mean Value'); ax.legend(); ax.set_title('Objective Decomposition: TT + WSF')
    fig.tight_layout(); savefig(fig,'fig2_tt_wsf',out_dir)

def fig3(ok, out_dir):
    by_pa = defaultdict(lambda: defaultdict(list))
    for r in ok: by_pa[(r['pressure_level'],r['algorithm_label'])]['Z'].append(float(r['Z']))
    pressures = ['medium','high','very_high']
    fig, ax = plt.subplots(figsize=(8,3.5))
    x = range(len(REPR_ALGOS)); width = 0.25
    for i, p in enumerate(pressures):
        m = [sum(by_pa.get((p,a),{}).get('Z',[0]))/max(1,len(by_pa.get((p,a),{}).get('Z',[]))) for a in REPR_ALGOS]
        ax.bar([xi+i*width for xi in x], m, width, label=p.capitalize())
    ax.set_xticks([xi+width for xi in x])
    ax.set_xticklabels([SHORT.get(a,a) for a in REPR_ALGOS], rotation=20, ha='right')
    ax.set_ylabel('Mean Z'); ax.legend(); ax.set_title('Pressure-Level Z Comparison')
    fig.tight_layout(); savefig(fig,'fig3_pressure_Z',out_dir)

def fig4(ok, out_dir):
    by_pa = defaultdict(lambda: defaultdict(list))
    for r in ok: by_pa[(r['pressure_level'],r['algorithm_label'])]['WSF'].append(float(r['WSF']))
    pressures = ['medium','high','very_high']
    fig, ax = plt.subplots(figsize=(8,3.5))
    x = range(len(REPR_ALGOS)); width = 0.25
    for i, p in enumerate(pressures):
        m = [sum(by_pa.get((p,a),{}).get('WSF',[0]))/max(1,len(by_pa.get((p,a),{}).get('WSF',[]))) for a in REPR_ALGOS]
        ax.bar([xi+i*width for xi in x], m, width, label=p.capitalize())
    ax.set_xticks([xi+width for xi in x])
    ax.set_xticklabels([SHORT.get(a,a) for a in REPR_ALGOS], rotation=20, ha='right')
    ax.set_ylabel('Mean WSF'); ax.legend(); ax.set_title('Pressure-Level WSF Comparison')
    fig.tight_layout(); savefig(fig,'fig4_pressure_WSF',out_dir)

def fig5(ok, out_dir):
    b = by_algo_metric(ok)
    variants = {"EDF-only":"Plain-RHO-Fast","+unbiased LNS":"RHO-LNS-Fast",
                "+adaptive RG":"Adaptive-RG-v1.2","Full NR-RG":"NR-RG-RHO-LNS"}
    # Only use variants present in data
    present_variants = {k: v for k, v in variants.items() if v in b}
    if len(present_variants) < 2: return
    labels = list(present_variants.keys())
    zs = [sum(b[v]['Z'])/len(b[v]['Z']) for v in present_variants.values()]
    colors = ['#7f7f7f','#1f77b4','#ff7f0e','#2ca02c'][:len(labels)]
    fig, ax = plt.subplots(figsize=(5.5,3.5))
    ax.bar(range(len(labels)), zs, color=colors, edgecolor='white')
    ax.set_xticks(range(len(labels))); ax.set_xticklabels(labels)
    ax.set_ylabel('Mean Z'); ax.set_title('Ablation Study')
    fig.tight_layout(); savefig(fig,'fig5_ablation',out_dir)

def fig6(base_dir, out_dir):
    cand_path = os.path.join(base_dir, 'initial_candidate_performance.csv')
    if not os.path.exists(cand_path): return
    rows = read_csv(cand_path)
    sel = [r for r in rows if r.get('selected')=='True']
    counts = Counter(r['candidate'] for r in sel)
    names = [n for n,_ in counts.most_common(15)]
    vals = [counts[n] for n in names]
    fig, ax = plt.subplots(figsize=(7,4))
    ax.barh(range(len(names)), vals, color='#1f77b4', edgecolor='white')
    ax.set_yticks(range(len(names))); ax.set_yticklabels(names, fontsize=7)
    ax.set_xlabel('Times Selected'); ax.set_title('Initial Candidate Selection Frequency')
    ax.invert_yaxis()
    fig.tight_layout(); savefig(fig,'fig6_candidate_selection',out_dir)

def fig7(base_dir, out_dir):
    conv_path = os.path.join(base_dir, 'convergence_raw.csv')
    if not os.path.exists(conv_path): return
    rows = read_csv(conv_path)
    conv_algos = ["RHO-LNS-Fast","Adaptive-RG-v1.2","VNS-Fast","TS-Fast","NR-RG-RHO-LNS"]
    by_algo_iter = defaultdict(lambda: defaultdict(list))
    for r in rows:
        try:
            a = r['algorithm_label']; it = int(r['iteration'])
            z = float(r['best_so_far_Z']); p = r.get('pressure_level','')
            by_algo_iter[(p,a)][it].append(z)
        except: continue
    fig, axes = plt.subplots(1, 3, figsize=(14,4))
    for ax, pressure in zip(axes, ['medium','high','very_high']):
        for a in conv_algos:
            data = by_algo_iter.get((pressure,a), {})
            if not data: continue
            iters = sorted(data.keys())[:30]
            means = [sum(data[i])/len(data[i]) for i in iters]
            ax.plot(iters, means, label=SHORT.get(a,a), color=get_color(a), linewidth=1.2)
        ax.set_xlabel('Iteration'); ax.set_ylabel('Best-so-far Z')
        ax.set_title(pressure.capitalize()); ax.legend(fontsize=5); ax.grid(True, alpha=0.3)
    fig.suptitle('Convergence: Best-so-far Z vs Iteration')
    fig.tight_layout(); savefig(fig,'fig7_convergence',out_dir)

def fig8(ok, out_dir):
    b = defaultdict(list)
    for r in ok: b[r['algorithm_label']].append(float(r['runtime_total_s']))
    existing = [a for a in ALGOS if a in b]
    rts = [max(sum(b[a])/len(b[a]), 1e-5) for a in existing]
    fig, ax = plt.subplots(figsize=(9,3.5))
    ax.bar(range(len(existing)), rts, color=[get_color(a) for a in existing], edgecolor='white')
    ax.set_yscale('log'); ax.set_xticks(range(len(existing)))
    ax.set_xticklabels([SHORT.get(a,a) for a in existing], rotation=40, ha='right')
    ax.set_ylabel('Runtime (s, log scale)'); ax.set_title('Runtime Comparison')
    fig.tight_layout(); savefig(fig,'fig8_runtime',out_dir)

def fig9(ok, out_dir):
    """Scalability heatmap: mean gap-to-best by job × machine."""
    by_inst = defaultdict(lambda: defaultdict(dict))
    for r in ok:
        # Estimate job count from instance label or pressure-level grouping
        k = (r['pressure_level'], r['instance_index'], r['seed_index'])
        by_inst[k][r['algorithm_label']] = float(r['Z'])
    # Aggregate by estimated job×machine bins (use instance_index to infer)
    # For now, use a simpler approach: group by pressure and algorithm
    by_pa = defaultdict(lambda: defaultdict(list))
    for r in ok:
        a = r['algorithm_label']
        # Infer job/machine from instance index (0-35): job = (idx%4) mapping, machine = ((idx//4)%3) mapping
        idx = int(r['instance_index'])
        job_levels = [40,80,120,160]; machine_levels = [5,10,15]
        nj = job_levels[min(idx%4, 3)]
        nm = machine_levels[min((idx//4)%3, 2)]
        by_pa[(nj,nm)][a].append(float(r['Z']))

    # Build heatmap data for NR-RG-RHO-LNS vs RHO-LNS-Fast
    job_vals = [40,80,120,160]; mach_vals = [5,10,15]
    data = [[0.0]*len(job_vals) for _ in range(len(mach_vals))]
    for mi, nm in enumerate(mach_vals):
        for ji, nj in enumerate(job_vals):
            nr_z = [sum(by_pa.get((nj,nm),{}).get('NR-RG-RHO-LNS',[0]))]
            rho_z = [sum(by_pa.get((nj,nm),{}).get('RHO-LNS-Fast',[0]))]
            nr_mean = sum(nr_z)/max(1,len(nr_z)) if nr_z else 0
            rho_mean = sum(rho_z)/max(1,len(rho_z)) if rho_z else 1
            if rho_mean > 0:
                data[mi][ji] = (rho_mean - nr_mean) / rho_mean * 100  # % improvement over RHO-LNS

    fig, ax = plt.subplots(figsize=(6,4))
    im = ax.imshow(data, cmap='RdYlGn', aspect='auto', vmin=-10, vmax=20)
    ax.set_xticks(range(len(job_vals))); ax.set_xticklabels(job_vals)
    ax.set_yticks(range(len(mach_vals))); ax.set_yticklabels(mach_vals)
    ax.set_xlabel('Number of Jobs'); ax.set_ylabel('Number of Machines')
    ax.set_title('NR-RG-RHO-LNS Improvement over RHO-LNS-Fast (%)')
    for mi in range(len(mach_vals)):
        for ji in range(len(job_vals)):
            ax.text(ji, mi, f'{data[mi][ji]:.1f}%', ha='center', va='center', fontsize=7)
    plt.colorbar(im, ax=ax)
    fig.tight_layout(); savefig(fig,'fig9_scalability',out_dir)

def fig10(base_dir, out_dir):
    op_path = os.path.join(base_dir, 'diagnostics_operator_success.csv')
    if not os.path.exists(op_path): return
    rows = read_csv(op_path)
    by_op = defaultdict(lambda: {"usage":0,"impr":0,"mag":0.0,"cnt":0})
    for r in rows:
        n = r['operator_name']; by_op[n]["usage"]+=int(r['usage_count'])
        by_op[n]["impr"]+=int(r['improvement_count'])
        m=float(r['total_improvement']); c=int(r['improvement_count'])
        if c>0: by_op[n]["mag"]+=m; by_op[n]["cnt"]+=c
    names = sorted(by_op)
    rates = [by_op[n]["impr"]/max(1,by_op[n]["usage"]) for n in names]
    mags = [by_op[n]["mag"]/max(1,by_op[n]["cnt"]) for n in names]
    fig, (ax1,ax2) = plt.subplots(1,2,figsize=(8,4))
    ax1.barh(range(len(names)),rates,color='#1f77b4',edgecolor='white')
    ax1.set_yticks(range(len(names))); ax1.set_yticklabels(names,fontsize=6)
    ax1.set_xlabel('Success Rate'); ax1.set_title('Operator Success Rate')
    ax2.barh(range(len(names)),mags,color='#2ca02c',edgecolor='white')
    ax2.set_yticks([]); ax2.set_xlabel('Mean ΔZ'); ax2.set_title('Improvement Magnitude')
    fig.tight_layout(); savefig(fig,'fig10_operator_contribution',out_dir)

def fig11(out_dir):
    """Representative Gantt chart: machine schedule + entity fulfillment timeline."""
    if not HAS_MPL: return
    try:
        import logging; logging.basicConfig(level=logging.WARNING)
        from ..generation.instance_generator import InstanceConfig, generate_instance
        from ..algorithms.rg_rho_lns_fast import run_nr_rg_rho_lns
        from ..core.simulator import run_simulation

        # Generate a medium-sized representative instance
        cfg = InstanceConfig(group_name='gantt', num_instances=1, num_jobs=40,
            num_machines=5, num_entities=3, ops_per_job=(2,4),
            rho_range=(0.85,0.95), deadline_tightness=0.5, weight_pattern='mild',
            proc_time_range=(10,50), transport_delay_range=(10,40),
            eligible_machines_range=(2,3), alpha=1.0, beta=1.0)
        inst = generate_instance(cfg, seed=42, instance_index=0)

        algo = run_nr_rg_rho_lns(lns_iterations=10, seed=42)
        state, obj = run_simulation(inst, algo)

        ops = state.scheduled_operations
        if not ops: return

        # ── Panel (a): Machine Gantt ──
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7))
        machine_colors = plt.cm.tab10.colors
        for sop in ops:
            color = machine_colors[sop.machine_id % len(machine_colors)]
            ax1.barh(sop.machine_id, sop.end_time - sop.start_time,
                     left=sop.start_time, height=0.7,
                     color=color, edgecolor='white', linewidth=0.3)
        ax1.set_yticks(range(inst.num_machines))
        ax1.set_yticklabels([f'M{m}' for m in range(inst.num_machines)])
        ax1.set_xlabel('Time'); ax1.set_title('Machine Schedule')

        # ── Panel (b): Entity fulfillment timeline ──
        entity_colors = plt.cm.Set2.colors
        for entity in inst.entities:
            eid = entity.entity_id
            delivered_qty = 0
            times_qty = []
            entity_jobs = sorted(
                [j for j in inst.jobs if j.entity_id == eid and state.is_job_completed(j.job_id)],
                key=lambda j: state.completed_jobs[j.job_id])
            for j in entity_jobs:
                c_time = state.completed_jobs[j.job_id]
                delivery = c_time + entity.transport_delay
                delivered_qty += j.quantity
                times_qty.append((delivery, delivered_qty))
            if times_qty:
                ts, qs = zip(*times_qty)
                ax2.step(ts, qs, where='post',
                         color=entity_colors[eid % len(entity_colors)],
                         label=f'E{eid} (ρ={entity.rho:.2f}, w={entity.weight:.1f})',
                         linewidth=1.5)
            ax2.axhline(y=entity.min_fulfillment, color=entity_colors[eid % len(entity_colors)],
                        linestyle='--', linewidth=0.8, alpha=0.5)
            ax2.axvline(x=entity.deadline, color=entity_colors[eid % len(entity_colors)],
                        linestyle=':', linewidth=0.8, alpha=0.5)
        ax2.set_xlabel('Time'); ax2.set_ylabel('Cumulative Delivered Quantity')
        ax2.set_title('Entity Service Fulfillment'); ax2.legend(fontsize=5)
        fig.suptitle(f'Representative Schedule (Z={obj.Z:.0f}, TT={obj.total_tardiness:.0f}, WSF={obj.weighted_service_shortfall:.0f})')
        fig.tight_layout(); savefig(fig, 'fig11_gantt', out_dir)
    except Exception as e:
        print(f"  Gantt chart skipped: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    input_dir = sys.argv[1] if len(sys.argv)>1 else "outputs/final_v13_validation"
    raw_path = os.path.join(input_dir, "final_raw.csv")
    if not os.path.exists(raw_path):
        print(f"ERROR: {raw_path} not found. Run benchmark first.")
        sys.exit(1)

    rows = read_csv(raw_path)
    ok = [r for r in rows if r['status']=='OK']
    print(f"Loaded {len(ok)} OK runs from {len(rows)} total")

    gen_all_tables(ok, input_dir)
    gen_all_figures(ok, input_dir, input_dir)
    print("\nDone. Outputs in", input_dir)


if __name__ == "__main__":
    main()
