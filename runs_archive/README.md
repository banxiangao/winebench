# Raw run outputs (2026-11-26)

Everything the experiments wrote under `wine_bench/runs/` and `wine_agent/runs/`: prompts, model replies, patches,
agent trajectories, per-task evaluation results and the job records.  20,160 files, 1.6 GB unpacked, packed per setting.
Wine 11.19, dataset `wine_agent/dataset/winebench205_doc` (205 tasks).

Unpack in the repository root; the files land where the scripts expect them:

    for f in runs_archive/*.tar.zst; do zstd -dc --long=27 "$f" | tar -xf -; done
    (cd runs_archive && sha256sum -c SHA256SUMS)          # before unpacking, to check the download

| archive | content |
|---|---|
| `oneshot_<S>_prompts` | the prompt of every task, scenario 1.3 (name only) / 1.4 (name + Microsoft docs) |
| `oneshot_<S>_samples_<model>-n100` | local models: 100 replies per task (`samples/`), their evaluation (`samples_eval/`), job record |
| `oneshot_<S>_single_<model>` | API models: one reply per task (`responses/`), its evaluation (`eval/`), job record |
| `oneshot_<S>_responses_deepseek-v4-flash` | DeepSeek: one reply per task (`responses/`) only - generated outside the cluster, NOT evaluated yet (see the end) |
| `agent_<S>_<harness>_prompts` | the task text given to the agent, scenario 3.1 / 3.2, mini_swe / openhands |
| `agent_<S>_<harness>_<model>` | per task: result `<id>.json`, patch, trajectory `<id>.traj.json` (`responses/`), evaluation (`eval/`), job record |
| `baseline_wine11.19` | the dataset's tests on the untouched Wine tree: what a generated function is compared with |

Models: qwen3.8-27b, gpt-oss-20b, glm-4.7-flash (local, vLLM); claude-haiku-5-5, openai-gpt-6-luna (API).
The numbers computed from these files are in `results/`, `wine_bench/results/` and `wine_agent/results/`.

Two things were changed after the runs:

- `REDACTED.txt`: in 20 files the output of commands with which an agent listed the cluster's file system was replaced
  by a note (it held directory names of other users of the cluster).  Results and evaluations are untouched.
- `agent_3.2_mini_swe_openai-gpt-6-luna` has a `superseded/` folder: four tasks were run again because one model
  reply never ended and the recorded time was about 600 s too high (see its README.txt).

## Not evaluated yet: deepseek-v4-flash (added 2026-11-27)

The cluster's proxy refuses `api.deepseek.com`, so DeepSeek cannot be queried from a compute node.  Its one-shot replies
were generated on a workstation on 2026-11-27 with `wine_bench/scripts/run_llm.py` from the archived prompts
(`oneshot_<S>_prompts`, the ones every other model got): 205 replies per scenario and no failed request;
with usable code / truncated: 198 / 7 in scenario 1.3, 204 / 1 in scenario 1.4.

These two archives hold `responses/` only.  The replies still have to be evaluated on the cluster, in the same trees and
against the same baseline as every other setting; until then DeepSeek has no row in `results/`.  After the evaluation the
archives are to be replaced by `oneshot_<S>_single_deepseek-v4-flash` (with `eval/`), like the other API models.
