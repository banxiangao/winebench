# wine_bench: one-shot generation

The one-shot half of WineBench: a model gets one prompt per task and answers once, without a source tree and without a
compiler. The scenarios, the results and how a reply is evaluated are described in the [README at the root](../README.md).

| Scenario | The prompt holds |
|---|---|
| 1.1 | function name, prototype, context of its source file |
| 1.2 | as 1.1, plus the full Microsoft documentation of the function |

| Path | Content |
|---|---|
| `scenarios/scenario1.1`, `scenario1.2` | configuration and prompt templates of the two scenarios; `scenarios/models.toml` lists the models |
| `scripts/build_prompts.py` | writes `runs/scenario<S>/programmer/prompts/<id>.json` from the dataset and the templates |
| `scripts/run_llm.py` | one reply per task (API models) |
| `scripts/run_samples.py` | N replies per task (local models, pass@k) |
| `scripts/evaluate.py`, `eval_samples.py` | splice the code into Wine, compile, run the tests |
| `scripts/pass_at_k.py` | pass@1 / pass@10 / pass@100 from the evaluated samples |
| `vulcan/` | Slurm job scripts for the local models |
| `results/` | `table.txt` (one reply per task), `pass_at_k.txt` (100 samples per task) |
| `docs/README_legacy*.md` | documentation of an earlier design; its scenario numbers are not the current ones |

`dataset` is a link to `../wine_agent/dataset`. The helper scripts `run_all.sh`, `redo_model.sh` and `eval_all.sh` belong
to the earlier two-stage design as well.
