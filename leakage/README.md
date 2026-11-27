# Leakage experiment: functions written before and after the model's training cutoff

Does a model do better on Wine functions that existed when it was trained than on functions written afterwards?
If it had memorised Wine's source, it would.

Run for **gpt-oss-20b** only: it is the one local model with a published knowledge cutoff (2024-06, taken as
2024-06-30). Qwen3.8-27B and GLM-4.7-Flash state none and were left out.

## Result in short

| Setting | NEW | OLD | OLD − NEW (95 % interval) |
|---|---|---|---|
| 1.1 one-shot, pass@1 | 11.8 | 10.7 | −1.1 [−4.4, +2.2] |
| 1.1 one-shot, pass@10 | 27.9 | 32.1 | +4.2 [−2.6, +11.0] |
| 1.1 one-shot, pass@100 | 37.7 | 51.2 | **+13.5 [+5.6, +21.0]** |
| 1.2 one-shot, pass@1 | 12.8 | 13.4 | +0.6 [−2.7, +3.9] |
| 1.2 one-shot, pass@10 | 29.5 | 36.9 | +7.5 [+0.5, +14.3] |
| 1.2 one-shot, pass@100 | 38.9 | 54.0 | **+15.1 [+7.1, +23.0]** |
| 2.1 mini_swe, passed | 19.0 | 15.5 | −3.6 [−10.3, +2.8] |
| 2.1 OpenHands, passed | 41.3 | 40.1 | −1.2 [−9.1, +7.1] |
| 2.2 mini_swe, passed | 17.1 | 17.9 | +0.8 [−6.0, +7.5] |
| 2.2 OpenHands, passed | 41.3 | 48.4 | +7.1 [−1.2, +15.1] |

Percent of 252 tasks per group; the difference is in percentage points, its interval comes from a paired bootstrap.
All numbers, with compile rates and the similarity measures, are in `results.txt` and `results.csv`; the outcome of
every pair is in `results_tasks.csv`. The same is in the sheets `Leakage` and `Leakage per pair` of
`results/WineBench_results.xlsx`, and `figures/leakage.pdf` shows the table above. The raw outputs are in `runs_archive/`
(archives with `-new`, `-old` or `leak2024` in their names).

- **No sign that the original code is recited.** The code handed in is as close to Wine's implementation for the new
  functions as for the old ones: mean similarity 49.8 against 49.6 (scenario 1.1) and 49.6 against 49.6 (1.2), highest
  similarity among the 100 samples 71.4 against 72.0 and 70.5 against 71.5, a sample identical to the original in
  4.4 % against 4.4 % and 2.8 % against 4.0 % of the tasks. Samples with a similarity of 0.9 or more are, if anything,
  more frequent for the new functions (25.4 % against 20.2 %, 21.0 % against 16.7 % of the tasks).
- **With an agent, old and new functions are passed equally often.** None of the four differences is significant
  (exact McNemar test on the pairs in which only one member passed: p = 0.34, 0.85, 0.91, 0.10).
- **One-shot, the old functions are solved more often when many samples are drawn.** pass@1 is the same, pass@100 is
  13 to 15 points higher for the old functions. The difference sits in the tasks that are solved rarely: in scenario
  1.1, 63 old tasks but only 28 new ones have 1 to 9 passing samples out of 100, and 157 new tasks against 123 old
  ones have none.
- **The newer the function, the larger that difference.** Where the new function was written entirely after the
  cutoff (112 pairs) the pass@100 difference is +18.8 and +22.3; where only part of it is new (140 pairs) it is +9.3
  and +9.3.

Reading (an interpretation, not shown by the experiment): the agent settings use the same tasks and the same tests
and show no difference, so the two groups are about equally hard once the source tree can be read. One-shot, the model
has nothing but its memory of Wine's internal types and helpers, and for functions that existed before the cutoff
that memory fits more often. That is familiarity with the old code base, not recall of the function itself. A
remaining difference in difficulty between the groups cannot be ruled out for the one-shot settings; a model with a
later cutoff run on the same pairs would be the control, and none was run.

## Which functions are new, which are old

Every code line of every function of the benchmark was dated with `git blame -w -M -C` on Wine 11.19
(`function_dates.py` → `function_dates.csv`; comment and blank lines do not count).

- **NEW**: at least half of the code lines were committed after 2024-06-30. 289 functions; 252 of them have a
  Microsoft documentation page that could be downloaded and at least one test file that runs on the clean tree
  (`select_new.py`, `check_candidates.py`).
- **OLD**: no code line committed after 2024-06-30. For every NEW function the closest unused OLD function was taken
  (`match_old.py`): same top-level category, then the smallest distance in code lines, number of own tests, DLL,
  Unix or PE side, and use of the wineserver.

The 252 pairs (`pairs.csv`; task NNNN of one dataset is the partner of task NNNN of the other):

| | NEW | OLD |
|---|---|---|
| Lines, median | 14 | 15 |
| Code lines, median | 9 | 10 |
| Own tests, median | 1 | 1 |

251 pairs are in the same category, 126 in the same DLL. The datasets are `wine_agent/dataset/leak2024_new` and
`leak2024_old`, in the format of `winebench205_doc`. These functions are shorter than those of the main benchmark
(which has a lower bound of 15 lines), so the pass rates here are higher and must not be compared with the main tables.

## What was run

Scenarios 1.1 and 1.2 with 100 samples per task, scenarios 2.1 and 2.2 with mini_swe and with OpenHands, each for
both groups: 12 settings. Prompts, limits and evaluation are those of the main benchmark; the scenario folders
`scenario<S>-new` and `scenario<S>-old` differ from `scenario<S>` only in the dataset and the output folder.

The agent settings ran with the isolated runner (one source tree per container, nothing else of the project
mounted, see the main README). Checked with `vulcan/tree_access.py`: in none of the 2,016 agent tasks does a command
name another tree, the project directory or the scratch space.

Of the mini_swe runs, 12 to 26 tasks per setting ended because the conversation outgrew the model's context; they
count as they ended (the same happens in the main benchmark: 14 and 19 of 205).

## Limits of this experiment

- One model. Without a control model whose cutoff is later, a difference between the groups can come from the model's
  training data or from the groups themselves.
- "New" describes the lines of Wine 11.19. A function that was rewritten after the cutoff may have had an earlier
  implementation that the model has seen; the Windows API it implements and its documentation are older in any case.
- The pairs are matched on size, tests, category and DLL, not on difficulty.
- The cutoff is the one the model states (2024-06); the day is an assumption.

## Files

| File | Content |
|---|---|
| `function_dates.py`, `function_dates.csv` | commit dates of the code lines of every function |
| `select_new.py`, `new_candidates.json` | the NEW candidates |
| `match_old.py`, `old_candidates.json` | two OLD candidates per NEW function |
| `fetch_docs.sh`, `*_doc_pages.tsv` | downloads the documentation pages (not in the repository) |
| `prepare_new.sbatch`, `prepare_old.sbatch` | build the candidate records and run their tests on the clean tree |
| `check_candidates.py` | which candidates can be used |
| `assemble.py`, `pairs.csv` | the two datasets and the list of pairs |
| `build_prompts.sbatch` | prompts of the eight scenario folders |
| `analyze.py`, `analyze.sbatch` | the comparison → `results.txt`, `results.csv`, `results_tasks.csv` (one line per pair: the outcome in every setting) |
