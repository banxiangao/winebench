#!/usr/bin/env python3
"""make_figures.py - the cost figures of the paper, drawn from results/metrics_settings.csv.

    python3 figures/make_figures.py            (needs matplotlib; on Vulcan: sbatch figures/make_figures.sbatch)

Writes, each as .pdf (vector), .png (300 dpi) and .svg:
  figures/cost_agent      agent settings: wall time, input tokens, output tokens and steps per task,
                          scenario 2.2 (six models) and 2.1 (three local models), both harnesses
  figures/cost_oneshot    one-shot settings: time per reply, prompt tokens and output tokens per reply,
                          scenarios 1.1 and 1.2, six models
Every bar is a mean over the 205 tasks of one setting.  Nothing is computed here that is not in the csv.

Font: Times New Roman where it is installed; otherwise Liberation Serif (same metrics, free) or Nimbus Roman.
"""
import os, csv, glob
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'figures')

# ---------------------------------------------------------------- style
for d in ('/cvmfs/soft.computecanada.ca/gentoo/2023/x86-64-v3/usr/share/fonts/liberation-fonts', '/usr/share/fonts/truetype/liberation',
          '/usr/share/fonts/liberation-serif', '/usr/share/fonts/truetype/msttcorefonts'):
    for f in glob.glob(os.path.join(d, '*.ttf')):
        try: font_manager.fontManager.addfont(f)
        except Exception: pass
SERIF = ['Times New Roman', 'Liberation Serif', 'Nimbus Roman', 'Nimbus Roman No9 L', 'TeX Gyre Termes', 'Times', 'STIXGeneral']
have = {f.name for f in font_manager.fontManager.ttflist}
print('font used:', next((n for n in SERIF if n in have), 'matplotlib default serif'))
INK, INK2, GRID, AXIS = '#1a1a1a', '#4d4d4d', '#e6e6e6', '#b3b3b3'
plt.rcParams.update({'font.family': 'serif', 'font.serif': SERIF, 'mathtext.fontset': 'stix', 'font.size': 9, 'axes.edgecolor': AXIS,
                     'axes.labelcolor': INK2, 'xtick.color': INK2, 'ytick.color': INK, 'axes.titlesize': 9.5, 'axes.titleweight': 'bold',
                     'axes.linewidth': 0.7, 'pdf.fonttype': 42, 'svg.fonttype': 'none'})
NAMES = {'claude-haiku-5-5': 'Claude Haiku 5.5', 'openai-gpt-6-luna': 'GPT-6 Luna', 'deepseek-v4-flash': 'DeepSeek V4 Flash',
         'qwen3.8-27b': 'Qwen3.8-27B', 'gpt-oss-20b': 'gpt-oss-20b', 'glm-4.7-flash': 'GLM-4.7-Flash'}

rows = list(csv.DictReader(open(os.path.join(ROOT, 'results', 'metrics_settings.csv'), encoding='utf-8')))
def num(r, k): return float(r[k]) if r.get(k) not in ('', None) else None
def get(scenario, harness, model): return next((r for r in rows if r['scenario'] == scenario and r['harness'] == harness and r['model'] == model), None)

def fmt(v):
    if v >= 100: return f'{v:.0f}'
    return f'{v:.1f}'

def panel(ax, models, values, colors, first_col, top=None):
    """horizontal grouped bars: one group per model, one bar per series; the value at the end of every bar"""
    h = 0.34; n = len(values); top = top or max(v for vs in values for v in vs if v is not None)
    for k in range(n):
        ys = [i + (k - (n - 1) / 2) * (h + 0.05) for i in range(len(models))]
        ax.barh(ys, [v if v is not None else 0 for v in values[k]], height=h, color=colors[k], linewidth=0, zorder=3)
        for y, v in zip(ys, values[k]):
            if v is not None: ax.text(v + top * 0.018, y, fmt(v), va='center', ha='left', fontsize=7.2, color=INK, zorder=4)
    ax.set_ylim(len(models) - 0.5, -0.5); ax.set_xlim(0, top * 1.22)
    ax.set_yticks(range(len(models))); ax.set_yticklabels([NAMES[m] for m in models] if first_col else [])
    ax.tick_params(axis='y', length=0, pad=5); ax.tick_params(axis='x', length=0, labelsize=8)
    ax.xaxis.grid(True, color=GRID, linewidth=0.6, zorder=0); ax.set_axisbelow(True)
    for s in ('top', 'right', 'bottom'): ax.spines[s].set_visible(False)
    ax.locator_params(axis='x', nbins=4)

def legend(fig, entries, y, title=None):
    fig.legend(handles=[Patch(facecolor=c, linewidth=0, label=l) for l, c in entries], loc='upper center', bbox_to_anchor=(0.5, y), ncol=len(entries),
               frameon=False, fontsize=8.5, handlelength=1.3, handleheight=0.9, columnspacing=2.2, title=title, title_fontsize=8.5)

def save(fig, name):
    for ext in ('pdf', 'png', 'svg'): fig.savefig(os.path.join(OUT, f'{name}.{ext}'), dpi=300, bbox_inches='tight', pad_inches=0.04)
    plt.close(fig); print('wrote', name)

# ---------------------------------------------------------------- agent settings
HARNESS = [('mini_swe', 'mini-SWE-agent', '#4C72B0'), ('openhands', 'OpenHands', '#C44E52')]
METRICS = [('seconds_mean', 1, 'Wall time (s)'), ('prompt_tokens_mean', 1e-3, 'Input tokens (k)'),
           ('completion_tokens_mean', 1e-3, 'Output tokens (k)'), ('steps_mean', 1, 'Agent steps (max. 40)')]          # all per task
SCEN = [('2.2', 'Scenario 2.2\nname + docs', ['claude-haiku-5-5', 'openai-gpt-6-luna', 'deepseek-v4-flash', 'qwen3.8-27b', 'gpt-oss-20b', 'glm-4.7-flash']),
        ('2.1', 'Scenario 2.1\nname only', ['qwen3.8-27b', 'gpt-oss-20b', 'glm-4.7-flash'])]
def agent_value(scen, h, m, key, scale):
    r = get(scen, h, m)
    return num(r, key) * scale if r and num(r, key) is not None else None
fig, axes = plt.subplots(2, 4, figsize=(7.4, 4.3), sharex='col', gridspec_kw=dict(height_ratios=[6, 3], hspace=0.13, wspace=0.10))
for c, (key, scale, title) in enumerate(METRICS):
    top = max(v for scen, _, models in SCEN for h, *_ in HARNESS for m in models for v in [agent_value(scen, h, m, key, scale)] if v is not None)
    for r, (scen, label, models) in enumerate(SCEN):                     # one x scale per column, for both scenarios
        panel(axes[r][c], models, [[agent_value(scen, h, m, key, scale) for m in models] for h, *_ in HARNESS], [h[2] for h in HARNESS], c == 0, top)
    axes[0][c].set_title(title, color=INK, pad=7)
for r, (scen, label, models) in enumerate(SCEN):
    axes[r][0].annotate(label, xy=(0, 0.5), xycoords='axes fraction', xytext=(-104, 0), textcoords='offset points', ha='center', va='center',
                        fontsize=8.5, color=INK2, rotation=90, linespacing=1.3)
legend(fig, [(h[1], h[2]) for h in HARNESS], 1.03)
save(fig, 'cost_agent')

# ---------------------------------------------------------------- one-shot settings
SCEN1 = [('1.1', 'Scenario 1.1: name only', '#8CC5BC'), ('1.2', 'Scenario 1.2: name + docs', '#1F7A6E')]     # one hue: without / with the documentation
MODELS1 = ['claude-haiku-5-5', 'openai-gpt-6-luna', 'deepseek-v4-flash', 'qwen3.8-27b', 'gpt-oss-20b', 'glm-4.7-flash']
LOCAL = {'qwen3.8-27b', 'gpt-oss-20b', 'glm-4.7-flash'}
def one(scen, model):
    """(seconds per reply, prompt tokens, output tokens per reply) of a one-shot setting"""
    if model in LOCAL:                                  # 100 replies per task: harness "oneshot", model folder <model>-n100
        r = get(scen, 'oneshot', model + '-n100'); n = num(r, 'replies') / num(r, 'tasks')
        return num(r, 'seconds_mean') / n, num(r, 'prompt_tokens_mean'), num(r, 'completion_tokens_per_reply')
    r = get(scen, 'oneshot1', model)
    return num(r, 'seconds_mean'), num(r, 'prompt_tokens_mean'), num(r, 'completion_tokens_mean')
TITLES = ['Time per reply (s)', 'Prompt tokens', 'Output tokens per reply']
fig, axes = plt.subplots(1, 3, figsize=(7.4, 2.9), gridspec_kw=dict(wspace=0.10))
data = {s[0]: [one(s[0], m) for m in MODELS1] for s in SCEN1}
for c in range(3):
    panel(axes[c], MODELS1, [[data[s[0]][i][c] for i in range(len(MODELS1))] for s in SCEN1], [s[2] for s in SCEN1], c == 0)
    axes[c].set_title(TITLES[c], color=INK, pad=7)
axes[0].set_yticklabels([NAMES[m] + (r'$^\dagger$' if m in LOCAL else '') for m in MODELS1])
legend(fig, [(s[1], s[2]) for s in SCEN1], 1.06)
fig.text(0.5, -0.02, r'$^\dagger$ Local models: 100 replies per task, generated in batches on two L40S GPUs; time = wall time of the task / 100.  '
         'API models: one reply per task.', ha='center', va='top', fontsize=7.5, color=INK2)
save(fig, 'cost_oneshot')
