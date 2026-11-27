# WineBench

Can a language model re-implement a Windows API function of Wine? Wine's own conformance tests decide.

Each task is one exported function in the Wine source tree. Its implementation is removed and the model writes it
again; the model's code is put back into Wine, the module is compiled, and the test files that reference the function
are run and compared with the same tests on the untouched Wine. A task passes when no test fails that did not fail
before.

This repository holds one full round of experiments, run in November 2026 on the Vulcan cluster: the code, the
dataset, every result and the raw outputs.

## Setup

| | |
|---|---|
| Wine | 11.19 (tag `wine-11.19`) |
| Tasks | 205 functions, dataset `wine_agent/dataset/winebench205_doc` |
| Local models | qwen3.8-27b, gpt-oss-20b, glm-4.7-flash (vLLM, two L40S GPUs) |
| API models | claude-haiku-5-5, openai-gpt-6-luna, deepseek-v4-flash (thinking switched off) |

Four scenarios:

| Scenario | What the model gets | Mode |
|---|---|---|
| 1.3 | function name, prototype, context of its source file | one-shot: a single reply, no source tree, no compiler |
| 1.4 | as 1.3, plus the full Microsoft documentation of the function | one-shot |
| 3.1 | function name + the whole source tree (tests and the original implementation removed) | agent: can read code, edit code and run `./compile` |
| 3.2 | as 3.1, plus the full Microsoft documentation | agent |

The agent scenarios use two off-the-shelf harnesses, both unmodified: mini-swe-agent 2.4.6 and OpenHands
(openhands-sdk 1.60.1). Limits per task: 40 steps, 30 minutes, 5 failed compiles. The agent's own tree has no tests
and no git history, and its shell has no network access. The trees of the tasks that run in parallel in one job are
visible to each other, however; this is a flaw, see [Known limitations](#known-limitations).

One-shot generation differs by model type: local models are sampled 100 times per task and reported as pass@1,
pass@10 and pass@100; API models produce one reply per task.

## Dataset

The 205 tasks are a subset of the full WineBench set (4,598 functions with tests, `incoming/winebench_2026-11-24/`).
Every task comes with the full text of its Microsoft documentation.

- Selection: the implementation has at least 15 lines; more than 10 and at most 50 tests of its own module reference
  it; at least 10 tasks in each of the 12 top-level categories.
- Twelve tasks could not be tested on the cluster (they need outside network access or an audio device) and were
  replaced by twelve others from the full set (more than 10 lines, more than 5 tests); see
  `wine_agent/dataset/winebench205_doc/CHANGES.md`.
- Size: 35.5 lines per implementation on average (13 to 198); 3.6 test files per task on average.

| Category | Tasks | Category | Tasks |
|---|---|---|---|
| Graphics and multimedia | 36 | User input and messaging | 15 |
| System services | 29 | Networking and internet | 14 |
| Data access and storage | 17 | User interface | 14 |
| Security and identity | 16 | Diagnostics | 14 |
| Application installation and servicing | 16 | Devices | 13 |
| Windows environment (Shell) | 11 | C runtime library | 10 |

## Results

### Agent: tasks passed (of 205)

| Scenario | Harness | qwen3.8-27b | gpt-oss-20b | glm-4.7-flash | claude-haiku-5-5 | openai-gpt-6-luna | deepseek-v4-flash |
|---|---|---|---|---|---|---|---|
| 3.1 | mini_swe | 76 (37.1%) | 11 (5.4%) | 7 (3.4%) | — | — | — |
| 3.1 | OpenHands | 88 (42.9%) | 55 (26.8%) | 28 (13.7%) | — | — | — |
| 3.2 | mini_swe | 80 (39.0%) | 13 (6.3%) | 7 (3.4%) | 100 (48.8%) | 102 (49.8%) | 82 (40.0%) |
| 3.2 | OpenHands | 88 (42.9%) | 59 (28.8%) | 31 (15.1%) | 106 (51.7%) | 93 (45.4%) | 82 (40.0%) |

Compiled (%):

| Scenario | Harness | qwen3.8-27b | gpt-oss-20b | glm-4.7-flash | claude-haiku-5-5 | openai-gpt-6-luna | deepseek-v4-flash |
|---|---|---|---|---|---|---|---|
| 3.1 | mini_swe | 84.9 | 15.1 | 6.3 | — | — | — |
| 3.1 | OpenHands | 92.2 | 76.1 | 36.6 | — | — | — |
| 3.2 | mini_swe | 84.9 | 18.5 | 10.2 | 98.0 | 97.6 | 88.8 |
| 3.2 | OpenHands | 87.3 | 77.1 | 40.0 | 98.0 | 98.0 | 93.7 |

The API models were run in scenario 3.2 only. The two deepseek-v4-flash runs were not made on the cluster, and its
mini_swe run is strongly affected by the tree-visibility flaw described under
[Known limitations](#known-limitations): use its 82 with care.

### One-shot, local models (100 samples per task, %)

| Scenario | Model | pass@1 | pass@10 | pass@100 | compile@1 | compile@100 |
|---|---|---|---|---|---|---|
| 1.3 | gpt-oss-20b | 5.0 | 17.8 | 28.8 | 34.1 | 100.0 |
| 1.3 | qwen3.8-27b | 4.4 | 11.9 | 23.4 | 23.9 | 95.6 |
| 1.3 | glm-4.7-flash | 1.6 | 7.6 | 19.0 | 8.0 | 80.0 |
| 1.4 | gpt-oss-20b | 5.8 | 17.3 | 27.8 | 33.4 | 99.0 |
| 1.4 | qwen3.8-27b | 4.9 | 14.0 | 24.9 | 23.5 | 93.7 |
| 1.4 | glm-4.7-flash | 2.0 | 8.3 | 17.6 | 9.1 | 83.9 |

pass@k is the unbiased estimator `1 − C(n−c, k) / C(n, k)` with n = 100 and c the number of passing replies,
averaged over the tasks.

### One-shot, API models (one reply per task)

| Scenario | Model | With code | Compiled | Passed |
|---|---|---|---|---|
| 1.3 | claude-haiku-5-5 | 204 | 128 (62.4%) | 41 (20.0%) |
| 1.3 | openai-gpt-6-luna | 205 | 121 (59.0%) | 40 (19.5%) |
| 1.3 | deepseek-v4-flash | 198 | 93 (45.4%) | 29 (14.1%) |
| 1.4 | claude-haiku-5-5 | 203 | 137 (66.8%) | 41 (20.0%) |
| 1.4 | openai-gpt-6-luna | 204 | 136 (66.3%) | 38 (18.5%) |
| 1.4 | deepseek-v4-flash | 204 | 97 (47.3%) | 30 (14.6%) |

The deepseek-v4-flash replies were not generated on the cluster (see [Known limitations](#known-limitations)); they
were evaluated like all the others.

### Cost (scenario 3.2, mean per task)

| Model | Harness | Wall time (s) | Steps | Input tokens | Output tokens |
|---|---|---|---|---|---|
| claude-haiku-5-5 | mini_swe / OpenHands | 19 / 32 | 6.5 / 6.7 | 60k / 169k | 2,409 / 6,518 |
| openai-gpt-6-luna | mini_swe / OpenHands | 25 / 34 | 9.0 / 10.5 | 77k / 144k | 1,851 / 1,249 |
| deepseek-v4-flash | mini_swe / OpenHands | 30 / 32 | 14.4 / 18.1 | 201k / 400k | 2,240 / 3,256 |
| gpt-oss-20b | mini_swe / OpenHands | 77 / 46 | 25.9 / 18.0 | 250k / 344k | 4,103 / 2,501 |
| glm-4.7-flash | mini_swe / OpenHands | 153 / 150 | 34.5 / 35.4 | 337k / 580k | 4,623 / 3,217 |
| qwen3.8-27b | mini_swe / OpenHands | 584 / 687 | 25.1 / 18.2 | 349k / 397k | 2,654 / 2,747 |

Input tokens are summed over the steps of a task (the history is sent again at every step). Wall times of local and
API models cannot be compared directly: the former run six tasks at a time on two L40S GPUs, the latter go through a
vendor's API. The deepseek-v4-flash times were measured on a different machine.

Where the complete numbers are:

- `wine_agent/results/table.txt`: one line per agent setting
- `wine_bench/results/pass_at_k.txt` and `table.txt`: the one-shot settings
- `results/metrics_tasks.csv`: time, tokens, steps and outcome of every task; `metrics_settings.txt`: the same per setting
- `results/jobs_usage.txt`: what every cluster job requested and used
- `results/tree_access_settings.txt`, `tree_access_tasks.csv`: which agents left the tree of their own task (see
  [Known limitations](#known-limitations))
- `figures/`: two figures of the time and token cost (`cost_agent`, `cost_oneshot`), described in its README

## How a task is evaluated

`wine_bench/scripts/evaluate.py` (one-shot) and `wine_agent/scripts/evaluate.py` (agent) follow the same steps:

1. **Splice.** The model's code replaces the original function in its source file. (An agent hands in a patch, which
   is applied to the tree as the agent saw it.)
2. **Compile.** The module of the function is built.
3. **Test.** Every test file that references the function is run and compared with its result on the untouched Wine
   (the baseline).
4. **Restore.** The tree is put back as it was.

Every task ends in one of these states:

| Status | Meaning |
|---|---|
| `pass` | compiles, and no test fails that did not fail on the baseline |
| `test_fail` | a test fails that passed on the baseline |
| `crash` | a test process crashed or did not finish |
| `timeout` | a test ran longer than 300 seconds |
| `compile_fail` | the module does not compile |
| `splice_fail` | the code cannot be placed into the source file |
| `no_code` | the reply holds no usable code |

Test files that crash or time out on the baseline itself are left out.

## Repository layout

| Directory | Content |
|---|---|
| `wine_bench/` | one-shot: building the prompts, querying the models, evaluation, pass@k |
| `wine_agent/` | agent: the runners of the two harnesses, evaluation, the dataset |
| `vulcan/` | job scripts and entry points for the cluster (`vulcan/README.md`, in Chinese) |
| `container/` | definition of the container image (`wine-agent.def`) and the script that builds Wine |
| `results/` | metrics tables |
| `figures/` | cost figures and the script that draws them |
| `runs_archive/` | every raw output, packed: prompts, replies, patches, agent trajectories, per-task evaluations (see its README) |
| `incoming/` | the full WineBench set and the subset as they were delivered |

## Running it

The experiments are written for a Slurm cluster: one setting (model + scenario + harness) is one job, and the job
submits the evaluation of its setting when the generation is complete.

```bash
bash vulcan/submit.sh qwen3.8-27b 3.2 openhands          # a local model, agent setting
bash vulcan/submit_api.sh claude-haiku-5-5 1.4           # an API model, one-shot
bash vulcan/submit_api.sh openai-gpt-6-luna 3.2 mini_swe # an API model, agent
```

Three things have to be prepared first; they are too large for the repository:

- the container image `container/wine-agent.sif`, built from `wine-agent.def` (Ubuntu 22.04, the toolchain that
  compiles Wine, the two agent harnesses)
- a compiled Wine 11.19 source and build tree (`container/build_wine.sbatch`)
- the trees for the agents and for the evaluation, packed from it (`wine_agent/vulcan/pack_trees.sbatch`)

API keys go into `~/.config/winebench/secrets.toml`, in the form of `wine_bench/secrets.toml.example`.

None of this is needed to look at the results or to recompute the statistics: unpack the archives in `runs_archive/`.

## Known limitations

What should be known when the numbers are read:

- **API models get at most two generations per task.** A task is generated a second time only if the first attempt
  returned nothing because of an API, network or runner error; if the second fails too, the task counts as a failed
  generation. A reply without code, a truncated reply and an agent that hits one of its limits are results of the
  task and are not retried. In these runs no task needed its second attempt.
- **The trees of parallel tasks are visible to each other (agent settings).** A job runs six tasks at once, and their
  six source trees sit side by side. Each tree hides only the function of its own task, so the original
  implementation of that function can be read in the other trees, and nothing keeps an agent inside its own tree.
  Counted from the commands in the trajectories (`vulcan/tree_access.py`, details in `results/tree_access_tasks.csv`):
  - In the 16 settings run on the cluster (3,280 tasks), the commands of 76 tasks name another tree. Six of the tasks
    that read their target file in another tree passed (gpt-oss-20b 4, claude-haiku-5-5 1, qwen3.8-27b 1). In the
    worst case a setting loses 3 passes.
  - The mini_swe run of deepseek-v4-flash is affected far more: 40 of its 205 tasks left their own tree, 36 read the
    target file in another tree, 31 wrote into another tree, and 8 of those that read the target file passed. Its 82
    may be too high, and it may be too low (some tasks put their code into another tree, left their own untouched and
    count as no code). Its OpenHands run shows none of this.
  - These counts are upper bounds taken from the text of the commands; whether the submitted code was actually copied
    has not been checked task by task. The commands of 6 further tasks name the project directory or the dataset.
- **deepseek-v4-flash was not run on the cluster.** The cluster's proxy does not let its API through, so its replies
  and its agent runs were produced on another machine, with the same scripts, the same prompts, the same container
  image and the same packed trees; the evaluation was done on the cluster. That machine has direct internet access,
  so the agent's shell was given a proxy that does not exist (`WB_AGENT_OFFLINE=1`) to cut it off, which is weaker
  than the cluster's compute nodes, which have no route out at all. Its wall times are not comparable with the others.
- **Output caps differ.** One-shot: 8,192 tokens for deepseek-v4-flash (8 replies were truncated by it), 16,000 for
  claude-haiku-5-5, none for openai-gpt-6-luna. Agent settings: 8,192 for the local models, deepseek and gpt-6-luna.
- **The cap of gpt-6-luna was added during the runs.** This model now and then runs away into endless whitespace
  inside a tool call. The first 74 tasks of its mini_swe 3.2 setting and its whole OpenHands 3.2 setting ran without
  a cap; four tasks were run again because one reply had timed out after 600 seconds, and their first results are in
  the `superseded/` folder of the archive.
- **gpt-oss-20b and glm-4.7-flash pass few tasks with mini_swe** mainly because they often hand in nothing that
  compiles, not because the code they write is wrong.
- **The prompt templates of scenarios 1.3 and 1.4 were reconstructed.** The original templates were not on the
  cluster; the ones here were rebuilt from the prompts of the pilot run and checked against them: all 464 prompts of
  scenario 1.4 are identical character for character, one prompt of scenario 1.3 differs.
- **Some trajectories were cleaned.** In 15 agent trajectories a command had listed the file system of the cluster;
  the output of those commands was replaced by a note, see `runs_archive/REDACTED.txt`. Results and evaluations are
  untouched.

## Sources

The implementations and tests of the tasks come from [Wine](https://www.winehq.org/) (LGPL), the documentation from
Microsoft's public API documentation. Their licences apply to that material.
