# Raw run outputs (2026-11-26)

Everything the experiments wrote under `wine_bench/runs/` and `wine_agent/runs/`: prompts, model replies, patches,
agent trajectories, per-task evaluation results and the job records.  23,013 files, 1.7 GB unpacked, packed per setting.
Wine 11.19, dataset `wine_agent/dataset/winebench205_doc` (205 tasks).

Unpack in the repository root; the files land where the scripts expect them:

    for f in runs_archive/*.tar.zst; do zstd -dc --long=27 "$f" | tar -xf -; done
    (cd runs_archive && sha256sum -c SHA256SUMS)          # before unpacking, to check the download

| archive | content |
|---|---|
| `oneshot_<S>_prompts` | the prompt of every task, scenario 1.1 (name only) / 1.2 (name + Microsoft docs) |
| `oneshot_<S>_samples_<model>-n100` | local models: 100 replies per task (`samples/`), their evaluation (`samples_eval/`), job record |
| `oneshot_<S>_single_<model>` | API models: one reply per task (`responses/`), its evaluation (`eval/`), job record |
| `agent_<S>_<harness>_prompts` | the task text given to the agent, scenario 2.1 / 2.2, mini_swe / openhands |
| `agent_<S>_<harness>_<model>` | per task: result `<id>.json`, patch, trajectory `<id>.traj.json` (`responses/`), evaluation (`eval/`), job record |
| `baseline_wine11.19` | the dataset's tests on the untouched Wine tree: what a generated function is compared with |

Models: qwen3.8-27b, gpt-oss-20b, glm-4.7-flash (local, vLLM); claude-haiku-5-5, openai-gpt-6-luna, deepseek-v4-flash
(API; deepseek-v4-flash was run outside the cluster, see the end).
The numbers computed from these files are in `results/`, `wine_bench/results/` and `wine_agent/results/`.

Two things were changed after the runs:

- `REDACTED.txt`: in 20 files the output of commands with which an agent listed the cluster's file system was replaced
  by a note (it held directory names of other users of the cluster).  Results and evaluations are untouched.
- `agent_2.2_mini_swe_openai-gpt-6-luna` has a `superseded/` folder: four tasks were run again because one model
  reply never ended and the recorded time was about 600 s too high (see its README.txt).

## deepseek-v4-flash: generated outside the cluster (added 2026-11-27)

The cluster's proxy refuses `api.deepseek.com`, so DeepSeek cannot be queried from a compute node.  Its one-shot replies
were generated on a workstation on 2026-11-27 with `wine_bench/scripts/run_llm.py` from the archived prompts
(`oneshot_<S>_prompts`, the ones every other model got): 205 replies per scenario and no failed request;
with usable code / truncated at the 8192-token cap: 198 / 7 in scenario 1.1, 204 / 1 in scenario 1.2.

They were then evaluated on the cluster like every other setting (same container, same Wine trees, same baseline);
`oneshot_<S>_single_deepseek-v4-flash` holds the replies and the evaluation.

The agent settings were run on the same workstation with `vulcan/run_api_local.sh`, which is the agent branch of
`vulcan/run_api.sbatch` without Slurm: the container image and the packed restricted trees are the files of the cluster
runs, copied and checked (sha256 `3d973942...a8e5eb` wine-agent.sif, `5fba2a6f...c81f15` swe-pair.tar), the runner call
and the limits are the same, 6 tasks in parallel (the first 3 tasks of the mini_swe setting: 4).  What differs:

- the machine (16 CPUs): times are not comparable with the cluster runs; steps, tokens and outcomes are;
- the network: the workstation is online, so the agent's shell got a proxy that does not exist (`WB_AGENT_OFFLINE=1`,
  `agent_network = dead_proxy` in every result) instead of having no route out.  That stops what honours the proxy
  variables, it is not a firewall; commands that name curl / wget / pip / git clone / apt are in `violations`.

`agent_2.2_mini_swe_deepseek-v4-flash` and `agent_2.2_openhands_deepseek-v4-flash` (generated 2026-11-27): 205 tasks
each, none failed to generate; 188 and 201 with a patch that changes the target file.  Both were then evaluated on the
cluster like every other setting; the archives hold the results, the trajectories and the evaluation.
Passed: 82 of 205 with mini_swe, 82 of 205 with OpenHands.

Checked after the runs:

- no network use: the `network` violations are the pattern matching words in code the agent typed, not commands; no key
  in any file (the key file shows up only as a name in `ls /` listings);
- THE mini_swe RUN LEFT ITS TREES.  All trees of a job sit side by side and each hides only the function of its own
  task, so the original implementation of a task's function is readable in the sibling trees (this is true of every
  agent run of the benchmark, see "Known limitations" in the main README and `results/tree_access_*`).  This model often starts
  with `cd /` or `cd /root` and looks for the file with `find /`: in 40 of the 205 mini_swe tasks a command names a
  tree other than the task's own, in 36 it names the target file there, in 31 it writes there (which may also have
  disturbed that worker's task); 8 of the 36 passed.  (A first count on the workstation, with a narrower criterion,
  gave 34 tasks.)  So the 82 may be too high or too low: use it with care, or run the setting again with one tree
  per container.  In the OpenHands run no command names another tree.

## Scenario numbers

The scenarios were numbered 1.3, 1.4, 3.1 and 3.2 while the experiments ran and were renamed afterwards:
1.3 → 1.1, 1.4 → 1.2, 3.1 → 2.1, 3.2 → 2.2.  Archive names and the paths inside the archives use the new numbers.
The job records (`jobs/<model>.jsonl`, field `scenario` and the job names) were left as written by the jobs and carry
the old ones.

## Leakage experiment (added 2026-11-27)

gpt-oss-20b on the two datasets of the leakage experiment, `wine_agent/dataset/leak2024_new` and `leak2024_old`
(252 tasks each, see `leakage/README.md`). The archives follow the naming above with the scenario written as
`<S>-new` or `<S>-old`; they unpack to `wine_bench/runs/scenario<S>-new/...` and so on. 25 archives, 15,812 files:

| archive | content |
|---|---|
| `oneshot_<S>-new_prompts`, `oneshot_<S>-old_prompts` | the prompt of every task, S = 1.1, 1.2 |
| `oneshot_<S>-new_samples_gpt-oss-20b-n100`, `..-old_..` | 100 replies per task, their evaluation, job record |
| `agent_<S>-new_<harness>_prompts`, `..-old_..` | the task text given to the agent, S = 2.1, 2.2 |
| `agent_<S>-new_<harness>_gpt-oss-20b`, `..-old_..` | per task: result, patch, trajectory, evaluation; job record |
| `baseline_wine11.19_leak2024` | the 76 test files these datasets use beyond those of `baseline_wine11.19`, on the untouched Wine tree |

These agent settings ran with one source tree per container and without the project directory mounted. Checked
before packing: no key in any file; no command that lists or walks the file system of the cluster; no directory name
of another user. Nothing was redacted.
