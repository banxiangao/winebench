#!/usr/bin/env python3
"""make_leakage_figure.py - the figure of the leakage experiment, drawn from leakage/results.csv.

    python3 figures/make_leakage_figure.py     (needs matplotlib; on Vulcan: sbatch figures/make_figures.sbatch)

Writes figures/leakage.pdf, .png (300 dpi) and .svg: gpt-oss-20b on 252 functions written after its training cutoff
(NEW) and their 252 matched partners untouched since (OLD).
  left   the rate of each group (one-shot: pass@1, pass@10, pass@100; agent: tasks passed)
  right  the difference OLD - NEW in percentage points with its 95 % interval (paired bootstrap)
Nothing is computed here that is not in the csv.  Style as in make_figures.py.
"""
import os, csv, glob
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for d in ('/cvmfs/soft.computecanada.ca/gentoo/2023/x86-64-v3/usr/share/fonts/liberation-fonts', '/usr/share/fonts/truetype/liberation',
          '/usr/share/fonts/liberation-serif', '/usr/share/fonts/truetype/msttcorefonts'):
    for f in glob.glob(os.path.join(d, '*.ttf')):
        try: font_manager.fontManager.addfont(f)
        except Exception: pass
SERIF = ['Times New Roman', 'Liberation Serif', 'Nimbus Roman', 'Nimbus Roman No9 L', 'TeX Gyre Termes', 'Times', 'STIXGeneral']
INK, INK2, GRID, AXIS = '#1a1a1a', '#4d4d4d', '#e6e6e6', '#b3b3b3'
C_OLD, C_NEW = '#4C72B0', '#C44E52'
plt.rcParams.update({'font.family': 'serif', 'font.serif': SERIF, 'mathtext.fontset': 'stix', 'font.size': 9, 'axes.edgecolor': AXIS,
                     'axes.labelcolor': INK2, 'xtick.color': INK2, 'ytick.color': INK, 'axes.titlesize': 9.5, 'axes.titleweight': 'bold',
                     'axes.linewidth': 0.7, 'pdf.fonttype': 42, 'svg.fonttype': 'none'})

R = {(r['scenario'], r['harness'], r['metric']): r for r in csv.DictReader(open(os.path.join(ROOT, 'leakage', 'results.csv'), encoding='utf-8')) if r['subset'] == 'all pairs'}
ROWS = [('1.1', 'one-shot', 'pass@1', 'pass@1'), ('1.1', 'one-shot', 'pass@10', 'pass@10'), ('1.1', 'one-shot', 'pass@100', 'pass@100'), None,
        ('1.2', 'one-shot', 'pass@1', 'pass@1'), ('1.2', 'one-shot', 'pass@10', 'pass@10'), ('1.2', 'one-shot', 'pass@100', 'pass@100'), None,
        ('2.1', 'mini_swe', 'pass', 'mini-SWE-agent'), ('2.1', 'openhands', 'pass', 'OpenHands'), None,
        ('2.2', 'mini_swe', 'pass', 'mini-SWE-agent'), ('2.2', 'openhands', 'pass', 'OpenHands')]
GROUPS = {0: 'Scenario 1.1 (one-shot)', 4: 'Scenario 1.2 (one-shot)', 8: 'Scenario 2.1 (agent)', 11: 'Scenario 2.2 (agent)'}

fig, (a, b) = plt.subplots(1, 2, figsize=(7.0, 3.9), sharey=True, gridspec_kw={'width_ratios': [1.0, 1.0], 'wspace': 0.06})
ys = []; labels = []; y = 0.0
for k, row in enumerate(ROWS):
    if row is None: y += 0.55; continue
    r = R[row[:3]]; new, old = float(r['new']), float(r['old']); d, lo, hi = float(r['old_minus_new']), float(r['ci_low']), float(r['ci_high'])
    if k in GROUPS:
        a.text(-0.34, y - 0.72, GROUPS[k], transform=a.get_yaxis_transform(), ha='left', va='center', fontsize=8.5, fontweight='bold', color=INK)
    a.plot([new, old], [y, y], color=AXIS, lw=1.6, zorder=2, solid_capstyle='round')
    a.plot(new, y, 'o', ms=5.5, mfc='white', mec=C_NEW, mew=1.5, zorder=3); a.plot(old, y, 'o', ms=5.5, color=C_OLD, zorder=3)
    left, right = (new, old) if new <= old else (old, new)
    a.text(left - 1.6, y, f'{left:.1f}', ha='right', va='center', fontsize=7.5, color=C_NEW if new <= old else C_OLD)
    a.text(right + 1.6, y, f'{right:.1f}', ha='left', va='center', fontsize=7.5, color=C_OLD if new <= old else C_NEW)
    sig = lo > 0 or hi < 0
    b.plot([lo, hi], [y, y], color=INK if sig else '#8c8c8c', lw=1.3, zorder=2, solid_capstyle='butt')
    b.plot(d, y, 's', ms=5, color=INK if sig else '#8c8c8c', zorder=3)
    b.text(26.5, y, f'{d:+.1f}  [{lo:+.1f}, {hi:+.1f}]', ha='left', va='center', fontsize=7.5, color=INK if sig else INK2, fontweight='bold' if sig else 'normal', clip_on=False)
    ys.append(y); labels.append(row[3]); y += 1.0
a.set_yticks(ys); a.set_yticklabels(labels, fontsize=8.5); a.set_ylim(y - 0.4, -1.3)
a.set_xlim(0, 66); a.set_xticks(range(0, 61, 20)); a.set_xlabel('Tasks solved (%)'); a.set_title('Rate of each group', loc='left', pad=6)
b.axvline(0, color=INK2, lw=0.8, zorder=1); b.set_xlim(-14, 26); b.set_xticks([-10, 0, 10, 20]); b.set_xlabel('OLD − NEW (percentage points)')
b.set_title('Difference, 95 % interval', loc='left', pad=6)
for ax in (a, b):
    ax.grid(axis='x', color=GRID, lw=0.6, zorder=0); ax.set_axisbelow(True); ax.tick_params(length=0)
    for s in ('top', 'right', 'left'): ax.spines[s].set_visible(False)
a.tick_params(axis='y', pad=22)
fig.legend(handles=[Line2D([], [], marker='o', ls='', ms=5.5, mfc='white', mec=C_NEW, mew=1.5, label='NEW: written after the cutoff (2024-06-30)'),
                    Line2D([], [], marker='o', ls='', ms=5.5, color=C_OLD, label='OLD: untouched since the cutoff'),
                    Line2D([], [], marker='s', ls='-', ms=5, lw=1.3, color=INK, label='interval excludes 0')],
           loc='lower center', ncol=3, frameon=False, fontsize=8, bbox_to_anchor=(0.5, -0.005), handletextpad=0.4, columnspacing=1.6)
fig.subplots_adjust(left=0.175, right=0.80, top=0.93, bottom=0.21)
for ext in ('pdf', 'png', 'svg'): fig.savefig(os.path.join(ROOT, 'figures', 'leakage.' + ext), dpi=300)
print('wrote figures/leakage.pdf, .png, .svg')
