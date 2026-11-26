#!/usr/bin/env python3
"""make_figures.py - the cost figures of the paper, drawn from results/metrics_settings.csv.

    python3 figures/make_figures.py            (needs matplotlib; on Vulcan: sbatch figures/make_figures.sbatch)

Writes, each as .pdf (vector), .png (300 dpi) and .svg:
  figures/cost_agent      agent settings: wall time, input tokens, output tokens and steps per task,
                          scenario 3.2 (five models) and 3.1 (three local models), both harnesses
  figures/cost_oneshot    one-shot settings: time per reply, prompt tokens and output tokens per reply,
                          scenarios 1.3 and 1.4, six models
Every bar is a mean over the 205 tasks of one setting.  Nothing is computed here that is not in the csv.
"""
import os, csv
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'figures')
INK, INK2, GRID, AXIS = '#0b0b0b', '#52514e', '#e1e0d9', '#c3c2b7'
NAMES = {'claude-haiku-5-5': 'Claude Haiku 5.5', 'openai-gpt-6-luna': 'GPT-6 Luna', 'deepseek-v4-flash': 'DeepSeek V4 Flash',
         'qwen3.8-27b': 'Qwen3.8-27B', 'gpt-oss-20b': 'gpt-oss-20b', 'glm-4.7-flash': 'GLM-4.7-Flash'}
plt.rcParams.update({'font.size': 8, 'font.family': 'DejaVu Sans', 'axes.edgecolor': AXIS, 'axes.labelcolor': INK2, 'xtick.color': INK2,
                     'ytick.color': INK, 'axes.titlesize': 8, 'axes.titleweight': 'bold', 'pdf.fonttype': 42, 'svg.fonttype': 'none',
                     'hatch.linewidth': 0.6})

rows = list(csv.DictReader(open(os.path.join(ROOT, 'results', 'metrics_settings.csv'), encoding='utf-8')))
def num(r, k): return float(r[k]) if r.get(k) not in ('', None) else None
def get(scenario, harness, model): return next((r for r in rows if r['scenario'] == scenario and r['harness'] == harness and r['model'] == model), None)

def fmt(v):
    if v >= 100: return f'{v:.0f}'
    if v >= 10: return f'{v:.1f}'
    return f'{v:.2f}'.rstrip('0').rstrip('.') if v < 1 else f'{v:.1f}'

def panel(ax, models, series, values, colors, hatches, first_col, limit=None, has_limit=False):
    """horizontal grouped bars: one group per model, one bar per series; value at the end of every bar"""
    h = 0.36; n = len(series); top = max(v for vs in values for v in vs if v is not None)
    for k in range(n):
        ys = [i + (k - (n - 1) / 2) * (h + 0.04) for i in range(len(models))]
        vs = [v if v is not None else 0 for v in values[k]]
        ax.barh(ys, vs, height=h, color=colors[k], hatch=hatches[k], edgecolor='white', linewidth=0, zorder=3)
        for y, v in zip(ys, values[k]):
            if v is not None: ax.text(v + top * 0.015, y, fmt(v), va='center', ha='left', fontsize=6.3, color=INK, zorder=4,
                                      bbox=dict(facecolor='white', edgecolor='none', pad=0.4) if has_limit else None)
    ax.set_ylim(len(models) - 0.5, -0.5); ax.set_xlim(0, top * 1.24)
    ax.set_yticks(range(len(models))); ax.set_yticklabels([NAMES[m] for m in models] if first_col else [])
    ax.tick_params(axis='y', length=0, pad=4); ax.tick_params(axis='x', length=0, labelsize=7)
    ax.xaxis.grid(True, color=GRID, linewidth=0.6, zorder=0); ax.set_axisbelow(True)
    for s in ('top', 'right', 'bottom'): ax.spines[s].set_visible(False)
    ax.locator_params(axis='x', nbins=4)
    if limit:
        ax.axvline(limit, color=INK2, linewidth=0.7, linestyle=(0, (3, 2)), zorder=2)
        ax.text(limit, -0.5, 'limit', ha='center', va='bottom', fontsize=6.3, color=INK2)

def save(fig, name):
    for ext in ('pdf', 'png', 'svg'): fig.savefig(os.path.join(OUT, f'{name}.{ext}'), dpi=300, bbox_inches='tight', pad_inches=0.04)
    plt.close(fig); print('wrote', name)

# ---------------------------------------------------------------- agent settings
HARNESS = [('mini_swe', 'mini-swe-agent', '#2a78d6', None), ('openhands', 'OpenHands', '#eb6834', '/////')]
METRICS = [('seconds_mean', 1, 'Wall time (s)', None), ('prompt_tokens_mean', 1e-3, 'Input tokens (k)', None),
           ('completion_tokens_mean', 1e-3, 'Output tokens (k)', None), ('steps_mean', 1, 'Agent steps', 40)]          # all per task
SCEN = [('3.2', 'Scenario 3.2\nname + docs', ['claude-haiku-5-5', 'openai-gpt-6-luna', 'qwen3.8-27b', 'gpt-oss-20b', 'glm-4.7-flash']),
        ('3.1', 'Scenario 3.1\nname only', ['qwen3.8-27b', 'gpt-oss-20b', 'glm-4.7-flash'])]
fig, axes = plt.subplots(2, 4, figsize=(7.4, 3.75), sharex='col', gridspec_kw=dict(height_ratios=[5, 3], hspace=0.16, wspace=0.10))
for r, (scen, label, models) in enumerate(SCEN):
    for c, (key, scale, title, limit) in enumerate(METRICS):
        vals = [[(lambda x: num(x, key) * scale if x and num(x, key) is not None else None)(get(scen, h, m)) for m in models] for h, *_ in HARNESS]
        panel(axes[r][c], models, HARNESS, vals, [h[2] for h in HARNESS], [h[3] for h in HARNESS], c == 0, limit if r == 0 else None, bool(limit))
        if r == 0: axes[r][c].set_title(title, color=INK, pad=9)
        elif limit: axes[r][c].axvline(limit, color=INK2, linewidth=0.7, linestyle=(0, (3, 2)), zorder=2)
    axes[r][0].annotate(label, xy=(0, 0.5), xycoords='axes fraction', xytext=(-78, 0), textcoords='offset points', ha='center', va='center',
                        fontsize=7.5, color=INK2, rotation=90)
for c, (key, scale, title, limit) in enumerate(METRICS):               # one x scale per column, for both scenarios
    top = max(num(x, key) * scale for scen, _, models in SCEN for h, *_ in HARNESS for m in models for x in [get(scen, h, m)] if x)
    axes[0][c].set_xlim(0, max(top, limit or 0) * 1.24)
fig.legend(handles=[Patch(facecolor=h[2], hatch=h[3], edgecolor='white', linewidth=0, label=h[1]) for h in HARNESS], loc='upper center', title='Mean per task (205 tasks per setting)', title_fontsize=7.5,
           bbox_to_anchor=(0.5, 1.09), ncol=2, frameon=False, fontsize=7.5, handlelength=1.6, columnspacing=2.0)
save(fig, 'cost_agent')

# ---------------------------------------------------------------- one-shot settings
SCEN1 = [('1.3', 'Scenario 1.3: name only', '#6250d6', None), ('1.4', 'Scenario 1.4: name + docs', '#008300', '/////')]
MODELS1 = ['claude-haiku-5-5', 'openai-gpt-6-luna', 'deepseek-v4-flash', 'qwen3.8-27b', 'gpt-oss-20b', 'glm-4.7-flash']
LOCAL = {'qwen3.8-27b', 'gpt-oss-20b', 'glm-4.7-flash'}
def one(scen, model):
    """(seconds per reply, prompt tokens, output tokens per reply) of a one-shot setting"""
    if model in LOCAL:                                  # 100 replies per task: the harness "oneshot", model folder <model>-n100
        r = get(scen, 'oneshot', model + '-n100'); n = num(r, 'replies') / num(r, 'tasks')
        return num(r, 'seconds_mean') / n, num(r, 'prompt_tokens_mean'), num(r, 'completion_tokens_per_reply')
    r = get(scen, 'oneshot1', model)
    return num(r, 'seconds_mean'), num(r, 'prompt_tokens_mean'), num(r, 'completion_tokens_mean')
TITLES = ['Time per reply (s)', 'Prompt tokens', 'Output tokens per reply']
fig, axes = plt.subplots(1, 3, figsize=(7.4, 2.75), gridspec_kw=dict(wspace=0.10))
data = {s[0]: [one(s[0], m) for m in MODELS1] for s in SCEN1}
for c in range(3):
    vals = [[data[s[0]][i][c] for i in range(len(MODELS1))] for s in SCEN1]
    panel(axes[c], MODELS1, SCEN1, vals, [s[2] for s in SCEN1], [s[3] for s in SCEN1], c == 0)
    axes[c].set_title(TITLES[c], color=INK, pad=6)
axes[0].set_yticklabels([NAMES[m] + (' †' if m in LOCAL else '') for m in MODELS1])
fig.legend(handles=[Patch(facecolor=s[2], hatch=s[3], edgecolor='white', linewidth=0, label=s[1]) for s in SCEN1], loc='upper center',
           bbox_to_anchor=(0.5, 1.07), ncol=2, frameon=False, fontsize=7.5, handlelength=1.6, columnspacing=2.0)
fig.text(0.5, -0.03, '† local models: 100 replies per task, generated in batches on two L40S GPUs; time = wall time of the task / 100.  '
         'API models: one reply per task.', ha='center', va='top', fontsize=6.5, color=INK2)
save(fig, 'cost_oneshot')
