# Figures

Two cost figures and the figure of the leakage experiment. The cost figures take their numbers from
`results/metrics_settings.csv` (every bar is the mean over the 205 tasks of one setting), the leakage figure from
`leakage/results.csv`. Each figure exists as `.pdf` (vector, for the paper), `.png` (300 dpi) and `.svg`.

| File | Content |
|---|---|
| `cost_agent` | cost per task of the agent settings: wall time, input tokens, output tokens, steps. Top: scenario 2.2 (six models); bottom: scenario 2.1 (the three local models). The two harnesses side by side. |
| `cost_oneshot` | cost of the one-shot settings: time per reply, prompt tokens, output tokens per reply. Six models, scenarios 1.1 and 1.2 side by side. |
| `leakage` | leakage experiment (`leakage/README.md`): gpt-oss-20b on 252 functions written after its training cutoff (NEW) and their 252 matched partners untouched since (OLD). Left: the rate of each group (one-shot: pass@1, pass@10, pass@100; agent: tasks passed). Right: the difference OLD − NEW in percentage points with its 95 % interval; black where the interval excludes 0. Drawn by `make_leakage_figure.py`. |
| `venn_oneshot` | which tasks the models pass in common, scenarios 1.1 and 1.2: one Venn diagram for the three local models (a task counts when at least one of its 100 samples passes) and one for the three API models (the single reply passes). Numbers are tasks; the circles are not to scale. Drawn by `make_venn_figures.py`, counts in `results/pass_overlap.csv`. |
| `venn_agent` | the same for the agent settings: scenario 2.1 (local models) and scenario 2.2 (local models, API models), top row mini-SWE-agent, bottom row OpenHands. |

To draw them again (needs matplotlib; on Vulcan the cluster's own is used):

```bash
sbatch figures/make_figures.sbatch        # or, on any machine: python3 figures/make_figures.py
```

Reading the figures:

- **Wall times of local and API models cannot be compared directly.** Local models run several tasks at a time on two
  L40S GPUs; API models go through a vendor's API.
- **"Time per reply" of the local models in the one-shot figure** is the wall time of a task's 100 samples divided by
  100: a throughput average, not the latency of a single request.
- **Input tokens of the agent settings** are summed over the steps of a task (the history is sent again at every
  step), which is why they are far larger than in the one-shot settings.
- **The agent runs of deepseek-v4-flash were not made on the cluster**; their wall times were measured on another
  machine and are not comparable with the others.

Font: the script uses Times New Roman where it is installed and otherwise falls back to Liberation Serif (a free font
with the same metrics) or Nimbus Roman. Vulcan has no Times New Roman, so the figures in the repository are set in
Liberation Serif. For Times New Roman proper, run `python3 figures/make_figures.py` on a machine that has the font:
the script picks it automatically and prints the font it used.
