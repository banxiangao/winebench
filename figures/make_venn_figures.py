#!/usr/bin/env python3
"""make_venn_figures.py - which tasks do the models pass in common?  Venn diagrams from results/metrics_tasks.csv.

    python3 figures/make_venn_figures.py       (needs matplotlib; on Vulcan: sbatch figures/make_figures.sbatch)

One diagram per scenario, mode and group of three models (three local, three API); a set is the tasks a model passed.
  figures/venn_oneshot    scenarios 1.1 and 1.2.  Local models: tasks with at least one passing reply among the 100
                          samples.  API models: tasks whose single reply passes.
  figures/venn_agent      scenarios 2.1 (local models) and 2.2 (local and API models), mini-SWE-agent and OpenHands
each as .pdf, .png (300 dpi) and .svg.  The circles have a fixed size (the areas are not to scale); the numbers are
the tasks in each region.  The same counts are written to results/pass_overlap.csv, together with, for scenario 2.2,
the number of tasks passed by exactly k of the six models.  Style as in make_figures.py.
"""
import os, csv, glob, itertools
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Circle

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for d in ('/cvmfs/soft.computecanada.ca/gentoo/2023/x86-64-v3/usr/share/fonts/liberation-fonts', '/usr/share/fonts/truetype/liberation',
          '/usr/share/fonts/liberation-serif', '/usr/share/fonts/truetype/msttcorefonts'):
    for f in glob.glob(os.path.join(d, '*.ttf')):
        try: font_manager.fontManager.addfont(f)
        except Exception: pass
SERIF = ['Times New Roman', 'Liberation Serif', 'Nimbus Roman', 'Nimbus Roman No9 L', 'TeX Gyre Termes', 'Times', 'STIXGeneral']
INK, INK2 = '#1a1a1a', '#4d4d4d'
plt.rcParams.update({'font.family': 'serif', 'font.serif': SERIF, 'mathtext.fontset': 'stix', 'font.size': 9, 'pdf.fonttype': 42, 'svg.fonttype': 'none'})
NAMES = {'claude-haiku-5-5': 'Claude Haiku 5.5', 'openai-gpt-6-luna': 'GPT-6 Luna', 'deepseek-v4-flash': 'DeepSeek V4 Flash',
         'qwen3.8-27b': 'Qwen3.8-27B', 'gpt-oss-20b': 'gpt-oss-20b', 'glm-4.7-flash': 'GLM-4.7-Flash'}
COLOR = {'qwen3.8-27b': '#4C72B0', 'gpt-oss-20b': '#DD8452', 'glm-4.7-flash': '#55A868',
         'claude-haiku-5-5': '#C44E52', 'openai-gpt-6-luna': '#8172B3', 'deepseek-v4-flash': '#937860'}
LOCAL = ['qwen3.8-27b', 'gpt-oss-20b', 'glm-4.7-flash']; API = ['claude-haiku-5-5', 'openai-gpt-6-luna', 'deepseek-v4-flash']
HNAME = {'mini_swe': 'mini-SWE-agent', 'openhands': 'OpenHands', 'oneshot': 'one-shot, 100 samples', 'oneshot1': 'one-shot, single reply'}

rows = list(csv.DictReader(open(os.path.join(ROOT, 'results', 'metrics_tasks.csv'), encoding='utf-8')))
IDS = sorted({r['id'] for r in rows})
def passed(scenario, harness, model):
    """the ids of the tasks the model passed in this setting (local one-shot: at least one of the samples passes)"""
    m = model + '-n100' if harness == 'oneshot' else model
    mine = [r for r in rows if r['scenario'] == scenario and r['harness'] == harness and r['model'] == m]
    assert len(mine) == len(IDS), (scenario, harness, model, len(mine))
    return {r['id'] for r in mine if (int(r['passed'] or 0) > 0 if harness == 'oneshot' else r['status'] == 'pass')}

OUT = []                                                                 # lines of results/pass_overlap.csv
def venn(ax, scenario, harness, models, title):
    S = [passed(scenario, harness, m) for m in models]; A, B, C = S
    reg = {'100': A - B - C, '010': B - A - C, '001': C - A - B, '110': (A & B) - C, '101': (A & C) - B, '011': (B & C) - A, '111': A & B & C}
    union = A | B | C
    cen = [(-0.58, 0.34), (0.58, 0.34), (0.0, -0.67)]
    for (x, y), m in zip(cen, models):
        ax.add_patch(Circle((x, y), 1.0, facecolor=COLOR[m], alpha=0.30, edgecolor='none', zorder=1))
        ax.add_patch(Circle((x, y), 1.0, facecolor='none', edgecolor=COLOR[m], lw=1.1, zorder=2))
    pos = {'100': (-1.08, 0.66), '010': (1.08, 0.66), '001': (0.0, -1.22), '110': (0.0, 0.86), '101': (-0.68, -0.36), '011': (0.68, -0.36), '111': (0.0, 0.02)}
    for k, (x, y) in pos.items():
        ax.text(x, y, str(len(reg[k])), ha='center', va='center', fontsize=10 if k == '111' else 9, fontweight='bold' if k == '111' else 'normal', color=INK, zorder=3)
    lab = [(-1.0, 1.50, 'center'), (1.0, 1.50, 'center'), (0.0, -1.86, 'center')]
    for (x, y, ha), m, s in zip(lab, models, S):
        ax.text(x, y, f'{NAMES[m]} ({len(s)})', ha=ha, va='center', fontsize=8.5, color=COLOR[m], fontweight='bold')
    ax.text(0, 2.02, title, ha='center', va='center', fontsize=9.5, fontweight='bold', color=INK)
    ax.text(0, -2.22, f'passed by at least one: {len(union)} of {len(IDS)}', ha='center', va='center', fontsize=8, color=INK2)
    ax.set_xlim(-2.0, 2.0); ax.set_ylim(-2.42, 2.22); ax.set_aspect('equal'); ax.axis('off')
    OUT.append(dict(scenario=scenario, mode=HNAME[harness], group='local' if models[0] in LOCAL else 'API', model_a=models[0], model_b=models[1], model_c=models[2],
                    a=len(A), b=len(B), c=len(C), only_a=len(reg['100']), only_b=len(reg['010']), only_c=len(reg['001']), a_b_not_c=len(reg['110']), a_c_not_b=len(reg['101']),
                    b_c_not_a=len(reg['011']), all_three=len(reg['111']), union=len(union), none=len(IDS) - len(union)))

def save(fig, name):
    for ext in ('pdf', 'png', 'svg'): fig.savefig(os.path.join(ROOT, 'figures', f'{name}.{ext}'), dpi=300, bbox_inches='tight', pad_inches=0.05)
    plt.close(fig); print('wrote', name)

# ---------------------------------------------------------------- one-shot
fig, ax = plt.subplots(2, 2, figsize=(6.6, 7.2), gridspec_kw={'wspace': 0.02, 'hspace': 0.04})
for i, s in enumerate(('1.1', '1.2')):
    venn(ax[i][0], s, 'oneshot', LOCAL, f'Scenario {s}, local models\n(a passing reply among 100 samples)')
    venn(ax[i][1], s, 'oneshot1', API, f'Scenario {s}, API models\n(the single reply passes)')
save(fig, 'venn_oneshot')

# ---------------------------------------------------------------- agent
fig, ax = plt.subplots(2, 3, figsize=(9.9, 7.2), gridspec_kw={'wspace': 0.02, 'hspace': 0.04})
for i, h in enumerate(('mini_swe', 'openhands')):
    venn(ax[i][0], '2.1', h, LOCAL, f'Scenario 2.1, {HNAME[h]}\nlocal models')
    venn(ax[i][1], '2.2', h, LOCAL, f'Scenario 2.2, {HNAME[h]}\nlocal models')
    venn(ax[i][2], '2.2', h, API, f'Scenario 2.2, {HNAME[h]}\nAPI models')
save(fig, 'venn_agent')

# ---------------------------------------------------------------- counts
cols = list(OUT[0])
with open(os.path.join(ROOT, 'results', 'pass_overlap.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(OUT)
    f.write('\n# scenario 2.2: tasks passed by exactly k of the six models\n'); f.write('scenario,mode,' + ','.join(f'k={k}' for k in range(7)) + ',union\n')
    for h in ('mini_swe', 'openhands'):
        S = [passed('2.2', h, m) for m in LOCAL + API]; n = [sum(i in s for s in S) for i in IDS]
        f.write(f'2.2,{HNAME[h]},' + ','.join(str(n.count(k)) for k in range(7)) + f',{sum(1 for x in n if x)}\n')
        print(f'scenario 2.2, {HNAME[h]}: tasks passed by exactly k of the six models:', {k: n.count(k) for k in range(7)})
for o in OUT:
    print(f"{o['scenario']} {o['mode']:24s} {o['group']:5s}  sets {o['a']:3d} {o['b']:3d} {o['c']:3d}  only {o['only_a']:3d} {o['only_b']:3d} {o['only_c']:3d}  "
          f"pairs {o['a_b_not_c']:3d} {o['a_c_not_b']:3d} {o['b_c_not_a']:3d}  all {o['all_three']:3d}  union {o['union']:3d}")
print('wrote results/pass_overlap.csv')
