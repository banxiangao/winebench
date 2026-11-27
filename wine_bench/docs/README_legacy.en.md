# wine_bench

> **Legacy document.** It describes the earlier two-stage design (architect -> programmer). The scenario numbers in it
> (1.1, 1.2, 2.1, ...) are those of that design and do NOT mean the current scenarios 1.1 / 1.2 / 2.1 / 2.2, which are
> described in the README at the root of the repository.

Benchmark: can LLM agents re-implement Wine's Windows API functions?
Everything needed to reproduce the dataset and the experiments is in this folder.

```
wine_bench/
  README.md                      this file: layout + every command
  secrets.toml                   API keys (git-ignored; copy from secrets.toml.example)
  scripts/
    wine_locate.py               export (module!name) -> implementation file:line
    wine_deps.py                 libclang dependency analysis of one function
    build_benchmark.py           dataset pipeline (sample -> locate -> dependencies -> same-name impls -> JSON)
    setup_wine_build.sh          one-off: generate the IDL headers / config.h that wine_deps needs
    build_prompts.py             stage 1: record + templates -> prompts (no network)
    run_llm.py                   stage 2: prompts -> model replies (any scenario, any stage)
    summary_table.py             one table over all runs (scenario x stage x architect model x programmer model)
    bench/                       shared code: config.py dataset.py prompt.py llm.py report.py
  dataset/
    wine500/                     500 records (one JSON per function) + manifest.json + pipeline.log
  scenarios/
    models.toml                  the model list shared by all scenarios
    common/templates/            templates shared by scenarios (programmer stage)
    scenario1.1/                 config.toml ([stage.architect], [stage.programmer]) + templates/: name (+ same-named impls) -> spec -> code
    scenario1.2/                 config.toml + templates/: original code + context -> spec -> code
  runs/                          outputs, git-ignored
    scenario1.1/architect/{prompts,responses/<model>}
    scenario1.1/programmer/from_<architect model>/{prompts,responses/<model>}   (+ <id>.c)
    scenario1.2/...              same layout
  docs/
    SCHEMA_dataset.md            dataset fields and sampling rules
  _archive/                      earlier runs; safe to delete
```

Wine source: `../wine_src/wine` (Wine 11.18, commit 6880117619a). Generated headers: `../wine-build`. Python env: `../venv`.

## 0. Environment (once)

```sh
# macOS
xcode-select --install
brew install bison flex ripgrep            # Apple's bison 2.3 is too old; ripgrep is optional but much faster
python3 -m venv ~/wine_fuzz/venv
source ~/wine_fuzz/venv/bin/activate
pip install libclang

# Linux (Debian/Ubuntu)
sudo apt install gcc bison flex ripgrep python3-venv
python3 -m venv ~/wine_fuzz/venv && source ~/wine_fuzz/venv/bin/activate && pip install libclang tomli
```

Every command below assumes `source ~/wine_fuzz/venv/bin/activate` and `cd ~/wine_fuzz/wine_bench`.

## 1. Generated headers (once per Wine version)

```sh
sh scripts/setup_wine_build.sh ../wine_src/wine ../wine-build
```

Builds Wine's IDL compiler out of tree and generates the COM headers (`objidl.h` ...) and a `config.h` into `../wine-build`. The source tree is not touched.

## 2. Dataset (already built: dataset/wine500)

```sh
cd ../wine_src/wine
python3 ../../wine_bench/scripts/build_benchmark.py --src . --build ../../wine-build \
    --out ../../wine_bench/dataset/wine500 --n 500 --seed 20261020
cd ../../wine_bench
```

Sampling: non-stub exports of `dlls/*/*.spec` resolved to a unique C function; third-party code, macro/asm bodies, C++ names, per-module boilerplate (DllGetClassObject ...) excluded; body >= 5 lines; no `FIXME("stub")`; not a generated file; the export name is referenced in the module's `tests/*.c`; dependency analysis parses without errors. Full field list: `docs/SCHEMA_dataset.md`.

Optional filters: `--exclude-win16 --exclude-crt --max-per-module 15 --min-body 10` (they change the sample: rebuild into an empty directory).

Maintenance on an existing dataset:

```sh
B="python3 ../../wine_bench/scripts/build_benchmark.py --src . --build ../../wine-build --out ../../wine_bench/dataset/wine500"
$B --redo-errors            # re-analyse records with parse errors
$B --redo 0040,0058         # re-analyse specific ids
$B --backfill               # recompute derived fields (has_fixme, same-name impls, type extraction)
$B --renumber               # contiguous ids + manifest.json after deleting records
```

Look at one function:

```sh
cd ../wine_src/wine
python3 ../../wine_bench/scripts/wine_locate.py 'kernel32!CreateFileW'
python3 ../../wine_bench/scripts/wine_deps.py 'kernel32!CreateFileW' --build ../../wine-build --same-file-only
```

## 3. Keys and models

```sh
cp secrets.toml.example secrets.toml       # then fill in the keys you have
```

`scenarios/models.toml` lists every model (豆包 / DeepSeek / OpenAI / Claude / Qwen / Grok / Gemini / Kimi / GLM / local).
Per model: `enabled`, `model` (check the provider's model page, ids change), `base_url`, `api_key_env`, optional `max_tokens`, `temperature`, `extra`.
A model is queried only if `enabled = true` and its key is present.

## 4. Running a scenario: two steps

Every scenario has stages (today: `architect`; later: `programmer`, ...). Each stage is two commands:

```sh
python3 scripts/build_prompts.py --scenario 1.1 [--stage architect]        # record + templates -> runs/scenario1.1/architect/prompts/<id>.{json,md}
python3 scripts/run_llm.py       --scenario 1.1 [--stage architect] ...    # prompts -> runs/scenario1.1/architect/responses/<model>/<id>.json
```

`build_prompts.py` needs no network; look at a few `.md` files before spending money. `run_llm.py` is model-agnostic: it only reads the prompts directory.

| option (both scripts) | meaning |
|---|---|
| `--scenario X` | `scenarios/scenarioX/config.toml`, or a path to any config.toml |
| `--stage S` | which `[stage.S]` of the config (default `architect`) |
| `--limit N` / `--ids 0001,0040` | subset of records |
| `--from-model M` | for a stage fed by another stage (programmer <- architect): use model M's replies; output under `<stage>/from_M/` |
| run_llm.py `--models a,b` | subset of model names from `scenarios/models.toml` |
| run_llm.py `--redo-bad` | re-query replies that errored, were truncated or failed the format check |
| run_llm.py `--workers N` | parallel requests per model |

Replies: `runs/<scenario>/<stage>/responses/<model>/<id>.json` with `response` (raw), `parsed` (the JSON form), `format_ok`, `truncated`, `code_leak` (the reply contains code: a rule violation for the architect), `usage`, `seconds`, `error`; `summary.json` per model. Runs are resumable: existing good replies are skipped.

## 5. Scenario 1.1 - architect from the function name

Input: DLL + export name, plus independent same-named implementations from other DLLs when they exist (28 of 500). No code, no prototype.
Output: a JSON requirement spec (purpose / inputs / return_type / outputs / behaviour / assumptions). Zero-shot.

```sh
python3 scripts/build_prompts.py --scenario 1.1
python3 scripts/run_llm.py --scenario 1.1 --models deepseek --limit 10      # trial: DeepSeek as the architect, 10 functions
python3 scripts/run_llm.py --scenario 1.1 --redo-bad                        # every enabled model, all 500
cat runs/scenario1.1/architect/responses/*/summary.json
```

## 6. Scenario 1.2 - architect from the original implementation

Input: everything from 1.1 plus the prototype, the original code (with its header comment), the same-file helper functions it calls (with code, marked "only used by this function" / "also used elsewhere"), the same-file private types / globals / macros, and the names of everything else it calls (other files, other DLLs, wineserver requests, Unix-side calls).
Output: the same JSON form as 1.1, so the two can be compared directly.

```sh
python3 scripts/build_prompts.py --scenario 1.2
python3 scripts/run_llm.py --scenario 1.2 --models deepseek --limit 10
python3 scripts/run_llm.py --scenario 1.2 --redo-bad
cat runs/scenario1.2/architect/responses/*/summary.json
```

## 7. Programmer stage (scenarios 1.1 and 1.2)

The programmer sees only the architect's specification plus the compile context of the file: the exact prototype (needed to replace the original and to link against the tests), the file's `#include` lines, the prototypes of same-file helpers that stay in the file (the ones not exclusive to the target), and the private types / globals / macros of the file. It never sees the original code, in either scenario. The reply must be pure C (static helpers + the function), which is saved as `<id>.c` next to the JSON.

The stage is fed by one architect model at a time, so outputs are kept per upstream model: `runs/<scenario>/programmer/from_<architect model>/`.

```sh
python3 scripts/build_prompts.py --scenario 1.1 --stage programmer --from-model deepseek            # specs written by deepseek
python3 scripts/run_llm.py       --scenario 1.1 --stage programmer --from-model deepseek --models deepseek --limit 10
python3 scripts/run_llm.py       --scenario 1.1 --stage programmer --from-model deepseek --redo-bad   # all enabled programmer models
ls  runs/scenario1.1/programmer/from_deepseek/responses/deepseek/*.c
cat runs/scenario1.1/programmer/from_deepseek/responses/*/summary.json
```

Same for 1.2. `format_ok` here means: the reply is code only (one fence tolerated), defines the function, braces balance. Compiling and testing is the next step (not yet in this folder).

### Mixing models: architect A -> programmer B

The two roles are independent: `--from-model` picks whose specs are used, `--models` picks who writes the code. Every combination is stored separately, so nothing is overwritten:

```sh
# specs by deepseek, code by openai and claude
python3 scripts/build_prompts.py --scenario 1.1 --stage programmer --from-model deepseek
python3 scripts/run_llm.py       --scenario 1.1 --stage programmer --from-model deepseek --models openai,claude

# specs by openai, code by deepseek
python3 scripts/build_prompts.py --scenario 1.1 --stage programmer --from-model openai
python3 scripts/run_llm.py       --scenario 1.1 --stage programmer --from-model openai --models deepseek
```

```
runs/scenario1.1/programmer/from_deepseek/responses/openai/     architect deepseek -> programmer openai
runs/scenario1.1/programmer/from_deepseek/responses/claude/     architect deepseek -> programmer claude
runs/scenario1.1/programmer/from_openai/responses/deepseek/     architect openai   -> programmer deepseek
```

The whole matrix in one table:

```sh
python3 scripts/summary_table.py            # scenario | stage | from | model | total | ok | trunc | err | tokens
python3 scripts/summary_table.py --csv > runs/summary.csv
```

## 8. Adding a scenario or a stage

The code is split so that a new scenario is configuration, not code:

- **New scenario** = copy `scenarios/scenario1.2/` to `scenarios/scenarioX/`, edit `config.toml` (`[paths].out`, the `[stage.*.inputs]` switches) and `templates/*.txt`. Run with `--scenario X`.
- **New stage** = add `[stage.<name>]` + `[stage.<name>.inputs]` and its templates to the scenario config; run with `--stage <name>`. A stage that consumes another stage's replies sets `input_stage = "<previous>"` and is run with `--from-model <model>`; the previous reply is available to sections as `ctx["upstream"]`. Templates shared by several scenarios live in `scenarios/common/templates/`.
- **Reply formats** per stage: `reply_format = "code"` (C source, saved as .c), or JSON form (`required_headings = []`), or Markdown headings (`required_headings = [...]`).
- **New kind of input** that no switch covers (e.g. the architect's spec fed to the programmer, external docs for scenario 2.1) = add one function in `scripts/bench/prompt.py` decorated with `@section('my_section')`, then use `{{my_section}}` in a template. Nothing else changes.
- **New model provider** = add `call_<name>()` in `scripts/bench/llm.py` and register it in `PROVIDERS`.
- Reply format per stage: JSON form in `system.txt` with `required_headings = []`, or Markdown headings (`system_markdown_oneshot.txt` in 1.1 + the five headings in `required_headings`, `one_shot = true`).
