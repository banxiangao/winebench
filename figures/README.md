# Figures

Two cost figures. All numbers come from `results/metrics_settings.csv`; every bar is the mean over the 205 tasks of
one setting. Each figure exists as `.pdf` (vector, for the paper), `.png` (300 dpi) and `.svg`.

| File | Content |
|---|---|
| `cost_agent` | cost per task of the agent settings: wall time, input tokens, output tokens, steps. Top: scenario 2.2 (six models); bottom: scenario 2.1 (the three local models). The two harnesses side by side. |
| `cost_oneshot` | cost of the one-shot settings: time per reply, prompt tokens, output tokens per reply. Six models, scenarios 1.1 and 1.2 side by side. |

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
