# wine_bench

一个 benchmark：让大语言模型重新实现 Wine 中的 Windows API 函数。
这个目录包含复现数据集和全部实验所需的东西。English version: `README.en.md`.

```
wine_bench/
  README.md                      本文件
  secrets.toml                   API 密钥（git 忽略；从 secrets.toml.example 复制）
  scripts/
    setup_wine_build.sh          一次性：在源码树外生成 IDL 头文件和 config.h
    wine_locate.py               导出函数 (module!name) -> 实现所在的 文件:行
    wine_deps.py                 用 libclang 分析一个函数的依赖
    build_benchmark.py           数据集流水线：抽样 -> 定位 -> 依赖 -> 同名实现 -> 每个函数一个 JSON
    fetch_docs.py                微软文档：建索引、按函数取页面、附到数据集
    build_prompts.py             第一步：数据记录 + 模板 -> 提示词（不联网）
    run_llm.py                   第二步：提示词 -> 各模型的回复
    summary_table.py             汇总所有运行结果为一张表
    run_all.sh                   一键：所有启用的模型跑完全部阶段
    evaluate.py                  第三步（Linux）：把生成的代码放进 Wine 编译、跑测试、记录结果
    eval_all.sh                  一键：所有模型 × 场景的评测
    setup_eval_ubuntu.sh         一次性：在 Ubuntu 上装依赖、编译 Wine 11.18 和全部测试
    bench/                       共用代码：config.py dataset.py prompt.py llm.py report.py csplice.py
  dataset/
    wine500/                     500 条记录（每个函数一个 JSON）+ manifest.json + pipeline.log，场景 1.x 用
    wine500_doc/                 500 条有微软文档的函数 + docs/（文档页副本），场景 2.1 用
    wine_exports.tsv             Wine 全部导出函数的定位表
    docs_index.tsv               微软文档索引（60,155 条）
  scenarios/
    models.toml                  所有场景共用的模型列表
    common/templates/            多个场景共用的模板（程序员阶段）
    scenario1.1/                 config.toml + templates/：函数名（+ 同名实现）-> 需求 -> 代码
    scenario1.2/                 config.toml + templates/：原实现 + 上下文 -> 需求 -> 代码
    scenario2.1/                 config.toml + templates/：函数名 + 官方文档 -> 代码（无架构师）
  runs/                          实验输出（git 忽略）
    <场景>/<阶段>[/from_<上游模型>]/prompts/            发送的提示词
    <场景>/<阶段>[/from_<上游模型>]/responses/<模型>/   回复、summary.json（程序员阶段另有 <id>.c）
    <场景>/<阶段>[/from_<上游模型>]/eval/<模型>/        编译 / 测试结果（evaluate.py）、summary.json
    baseline/                                            未改动的 Wine 上每个测试文件的结果（evaluate.py 自动生成）
  docs/
    SCHEMA_dataset.md            数据集字段和抽样规则
  _archive/                      早期版本，可整个删除
```

相关路径：Wine 源码 `../wine_src/wine`（11.18，commit 6880117619a），生成的头文件 `../wine-build`，Python 环境 `../venv`。

---

## 0. 环境准备（只做一次）

### macOS

```sh
xcode-select --install                     # 已装过会提示，忽略
brew install bison flex ripgrep            # 系统自带的 bison 2.3 太老；ripgrep 可选，但快很多
python3 -m venv ~/wine_fuzz/venv
source ~/wine_fuzz/venv/bin/activate
pip install libclang
```

### Linux（Debian / Ubuntu）

```sh
sudo apt install gcc bison flex ripgrep python3-venv
python3 -m venv ~/wine_fuzz/venv
source ~/wine_fuzz/venv/bin/activate
pip install libclang tomli                 # Python < 3.11 需要 tomli
```

**下面所有命令都默认已经执行了这两行：**

```sh
source ~/wine_fuzz/venv/bin/activate
cd ~/wine_fuzz/wine_bench
```

---

## 1. 生成头文件（每个 Wine 版本做一次）

Wine 源码里没有 COM 接口的头文件（`objidl.h` 等），它们由 IDL 生成。这一步在源码树**外面**编译 Wine 的 IDL 编译器并生成这些头文件和一份 `config.h`，不改动源码：

```sh
sh scripts/setup_wine_build.sh ../wine_src/wine ../wine-build
```

结束时打印 `done: 6xx headers in ...`。

---

## 2. 数据集

数据集已经生成在 `dataset/wine500/`，一般不用重做。

### 2.1 抽样规则

候选池是 `dlls/*/*.spec` 中所有非 `stub` 的导出，经 `wine_locate.py` 定位到唯一的 C 函数，排除：第三方代码（musl / ICU / sqlite）、宏或汇编生成的函数、C++ 修饰名、每个模块都有的样板入口（`DllGetClassObject`、`DllRegisterServer` 等），并按实现位置去重（kernel32 转发到 kernelbase、msvcr* 共用 msvcrt 源码的只算一次）。

然后过滤：函数体 ≥ 5 行；没有 `FIXME("...stub")` 半桩；源文件不是自动生成的；导出名出现在该模块的 `tests/*.c` 里（有原生测试）；依赖分析没有解析错误。固定种子打乱后取前 500 个。

每条记录的字段见 `docs/SCHEMA_dataset.md`。要点：原实现（`function.code`）、同文件依赖（`same_file_dependencies`，含 `exclusive_to_target` 标记）、同文件私有定义、其他依赖的名字和位置、其他 DLL 中的同名实现、所在文件的 `#include` 列表。

### 2.2 重新生成

```sh
cd ../wine_src/wine
python3 ../../wine_bench/scripts/build_benchmark.py --src . --build ../../wine-build \
    --out ../../wine_bench/dataset/wine500 --n 500 --seed 20261020
cd ../../wine_bench
```

约 10 分钟。可以中断，用同样的参数重跑会接着补。

可选过滤（会改变抽到的函数，要输出到一个空目录重新生成）：

| 参数 | 作用 |
|---|---|
| `--exclude-win16` | 排除 16 位模块（`*16`、`*.exe16`） |
| `--exclude-crt` | 排除 C 运行时家族（msvcr*、ucrtbase、crtdll、msvcp*） |
| `--max-per-module N` | 每个模块最多取 N 个 |
| `--min-body N` | 函数体最少 N 行（默认 5） |
| `--seed N` | 换一批函数 |

### 2.3 维护已有数据集

```sh
cd ../wine_src/wine
B="python3 ../../wine_bench/scripts/build_benchmark.py --src . --build ../../wine-build --out ../../wine_bench/dataset/wine500"
$B --redo-errors            # 重做 meta.parse_errors > 0 的记录（原 id 不变）
$B --redo 0040,0058         # 重做指定 id
$B --backfill               # 重算衍生字段：has_fixme、同名实现、类型定义、file_includes
$B --renumber               # 删掉某些记录后重新编号为连续的 0001..N，并生成 manifest.json
cd ../../wine_bench
```

### 2.4 场景 2.1 的数据集 wine500_doc（有官方文档的函数）

已生成在 `dataset/wine500_doc/`。做法：先把微软的四个文档仓库的文件树拉到本地建索引，再从 wine500 中保留有文档的 390 个，随机补足 500 个，最后把每个函数的文档页取下来附进记录。

```sh
python3 scripts/fetch_docs.py index                       # 克隆 MicrosoftDocs 的 sdk-api / windows-driver-docs-ddi / cpp-docs / win32
                                                          # （只拉文件列表，页面按需取）-> dataset/docs_index.tsv
python3 scripts/fetch_docs.py lookup CreateFileW _wtol    # 查某个函数在哪个仓库有文档

cd ../wine_src/wine
python3 ../../wine_bench/scripts/build_benchmark.py --src . --build ../../wine-build \
    --out ../../wine_bench/dataset/wine500_doc --n 500 --seed 20261021 \
    --lite --doc-index ../../wine_bench/dataset/docs_index.tsv --keep-from ../../wine_bench/dataset/wine500
python3 ../../wine_bench/scripts/build_benchmark.py --src . --out ../../wine_bench/dataset/wine500_doc --renumber
cd ../../wine_bench
python3 scripts/fetch_docs.py attach dataset/wine500_doc  # 取页面 -> dataset/wine500_doc/docs/，写入每条记录的 docs 字段
```

`--lite` 表示只定位函数、取代码和编译上下文，不做依赖分析（快，不需要 libclang）。以后要依赖的话一条命令原地补上，字段和 wine500 一样：

```sh
cd ../wine_src/wine
python3 ../../wine_bench/scripts/build_benchmark.py --src . --build ../../wine-build --out ../../wine_bench/dataset/wine500_doc --add-deps
```

文档仓库克隆在 `external/msdocs/`（git 忽略）；换位置用环境变量 `WINE_BENCH_MSDOCS=/path`。

### 2.5 查单个函数

```sh
cd ../wine_src/wine
python3 ../../wine_bench/scripts/wine_locate.py 'kernel32!CreateFileW'
python3 ../../wine_bench/scripts/wine_deps.py 'kernel32!CreateFileW' --build ../../wine-build --same-file-only
cd ../../wine_bench
```

---

## 3. 密钥和模型

```sh
cp secrets.toml.example secrets.toml       # 然后填入你有的密钥
```

`scenarios/models.toml` 预置了 豆包 / DeepSeek / OpenAI / Claude / 通义 / Grok / Gemini / Kimi / GLM / 本地模型。每个模型一个 `[[models]]` 块：

| 字段 | 说明 |
|---|---|
| `enabled` | true 才会被调用 |
| `name` | 结果目录名，任意字符串 |
| `provider` | `openai`（任何 OpenAI 兼容接口）或 `anthropic` |
| `base_url` | 接口地址 |
| `model` | 发给接口的模型 ID。**模型 ID 几个月就变，跑之前到各家文档页核对** |
| `api_key_env` | 在 `secrets.toml` 的 `[keys]` 里（或环境变量）读哪个名字 |
| `max_tokens` / `temperature` / `timeout_s` | 可选，覆盖场景里的 `[run]` |
| `extra` | 可选，合并进请求体，如 `extra = { response_format = { type = "json_object" } }` |

一个模型只有 `enabled = true` **且**密钥存在时才会被调用，否则跳过并打印原因。

**命名约定**：`name` 就是结果目录名，用 `<厂商>-<模型>`，如 `deepseek-v4-flash`、`openai-gpt-5`、`claude-sonnet-5-5`。同一厂商的多个模型就是多个 `[[models]]` 块，各有各的 `name`，结果互不干扰。
每条回复里都记录三样：`model`（这个 name）、`model_id`（配置里发出去的 id）、`served_model`（接口返回的实际模型 id）。有些 id 是别名（`deepseek-chat` 指向 DeepSeek 当前默认模型），先探测一下再定名字：

```sh
python3 scripts/run_llm.py --scenario 1.1 --probe        # 每个启用的模型发一个极小请求，打印实际服务的模型 id
python3 scripts/rename_model.py deepseek deepseek-v4-flash --model-id deepseek-chat   # 已有结果改名（目录 + JSON 字段）
```

---

## 4. 运行方式：两步

每个场景有若干阶段（目前 `architect` 架构师、`programmer` 程序员）。每个阶段都是两条命令：

```sh
python3 scripts/build_prompts.py --scenario 1.1 --stage architect     # 记录 + 模板 -> runs/scenario1.1/architect/prompts/<id>.{json,md}
python3 scripts/run_llm.py       --scenario 1.1 --stage architect     # 提示词 -> runs/scenario1.1/architect/responses/<模型>/<id>.json
```

`build_prompts.py` 不联网，先打开几个 `.md` 看看再花钱。`run_llm.py` 不关心场景内容，只读提示词目录。

| 参数（两个脚本通用） | 说明 |
|---|---|
| `--scenario X` | 用 `scenarios/scenarioX/config.toml`；也可以直接给一个 config.toml 的路径 |
| `--stage S` | 用配置里的 `[stage.S]`，默认 `architect` |
| `--limit N` / `--ids 0001,0040` | 只处理部分记录 |
| `--from-model M` | 消费上一阶段回复的阶段（程序员 <- 架构师）用：取模型 M 的回复，输出到 `<阶段>/from_M/` |
| `run_llm.py --models a,b` | 只调用 `models.toml` 里的这几个模型 |
| `run_llm.py --redo-bad` | 把出错、被截断、格式不对的回复重新请求一遍 |
| `run_llm.py --workers N` | 每个模型的并发数（默认 `[run].workers` = 4） |

回复文件 `responses/<模型>/<id>.json` 的字段：`response`（原文）、`parsed`（解析后的 JSON 表单，程序员阶段是代码）、`format_ok`、`truncated`（撞到输出上限）、`code_leak`（架构师回复里出现了代码，违规）、`usage`（token）、`seconds`、`error`。每个模型目录下有 `summary.json`。

**可以随时中断**：已完成的回复会跳过，重跑同一条命令即可继续。改了模板或配置后要重新 `build_prompts`，而旧回复不会自动失效，需要删掉对应的 `responses/<模型>/` 目录再跑。

---

## 5. 场景 1.1：架构师只看函数名

架构师输入：DLL 名 + 导出函数名；如果其他 DLL 有独立的同名实现（500 个里有 28 个），附上其代码。不给原型、不给代码。
架构师输出：固定表单的 JSON 需求（purpose / inputs / return_type / outputs / behaviour / assumptions）。零样本。

```sh
python3 scripts/build_prompts.py --scenario 1.1
open runs/scenario1.1/architect/prompts/0001.md                          # 看一眼

python3 scripts/run_llm.py --scenario 1.1 --models deepseek --limit 10   # 试 10 条
cat runs/scenario1.1/architect/responses/deepseek/summary.json           # total/format_ok 应为 10，其余为 0

python3 scripts/run_llm.py --scenario 1.1 --redo-bad                     # 全量：所有启用的模型，500 条
```

---

## 6. 场景 1.2：架构师看原实现

架构师输入：1.1 的内容，再加上原型、原实现（含注释块）、同文件里被调用的辅助函数代码（最多 10 个，标注"只被该函数使用"或"别处也用"）、同文件的私有类型/全局变量/宏、以及其他依赖的名字和位置。
架构师输出：与 1.1 完全相同的 JSON 表单，便于直接对比。

```sh
python3 scripts/build_prompts.py --scenario 1.2
open runs/scenario1.2/architect/prompts/0002.md

python3 scripts/run_llm.py --scenario 1.2 --models deepseek --limit 10
python3 scripts/run_llm.py --scenario 1.2 --redo-bad
```

---

## 7. 程序员阶段（1.1 和 1.2 通用）

程序员输入：架构师的需求 JSON + 编译上下文（准确的函数原型、文件的 `#include` 列表、文件里保留下来的辅助函数的原型、文件里的私有类型/全局变量/宏）。两个场景的程序员输入完全一样，**不给原实现**。
程序员输出：纯 C 代码（需要的 static 辅助函数 + 目标函数）。脚本检查：只有代码（允许一层围栏并剥掉）、定义了该函数、花括号平衡；通过的另存为 `<id>.c`。

程序员依赖某个架构师模型的输出，所以要用 `--from-model` 指定，结果按上游模型分目录：

```sh
python3 scripts/build_prompts.py --scenario 1.1 --stage programmer --from-model deepseek
open runs/scenario1.1/programmer/from_deepseek/prompts/0001.md

python3 scripts/run_llm.py --scenario 1.1 --stage programmer --from-model deepseek --models deepseek --limit 10
python3 scripts/run_llm.py --scenario 1.1 --stage programmer --from-model deepseek --redo-bad
ls  runs/scenario1.1/programmer/from_deepseek/responses/deepseek/*.c
```

1.2 把 `1.1` 换掉即可。

### 7.1 架构师和程序员用不同模型

两个角色相互独立：`--from-model` 选谁写的需求，`--models` 选谁写代码。每种组合单独存放，不会互相覆盖：

```sh
# deepseek 的需求 -> openai 和 claude 写代码
python3 scripts/build_prompts.py --scenario 1.1 --stage programmer --from-model deepseek
python3 scripts/run_llm.py       --scenario 1.1 --stage programmer --from-model deepseek --models openai,claude

# openai 的需求 -> deepseek 写代码（先要跑过 openai 的架构师阶段）
python3 scripts/build_prompts.py --scenario 1.1 --stage programmer --from-model openai
python3 scripts/run_llm.py       --scenario 1.1 --stage programmer --from-model openai --models deepseek
```

```
runs/scenario1.1/programmer/from_deepseek/responses/openai/     deepseek 需求 -> openai 代码
runs/scenario1.1/programmer/from_deepseek/responses/claude/     deepseek 需求 -> claude 代码
runs/scenario1.1/programmer/from_openai/responses/deepseek/     openai 需求 -> deepseek 代码
```

---

## 7.2 场景 2.1：程序员直接看官方文档

没有架构师。程序员输入：DLL、函数名、项目使用的原型、该函数的微软文档页原文（去掉 YAML 头和 see-also 节），以及和 1.x 程序员阶段相同的编译上下文（`#include`、可用的辅助函数原型、私有定义）。数据集是 `wine500_doc`，500 个函数都有文档。输出同样是纯 C 代码。

```sh
python3 scripts/build_prompts.py --scenario 2.1 --stage programmer
open runs/scenario2.1/programmer/prompts/0001.md

python3 scripts/run_llm.py --scenario 2.1 --stage programmer --models deepseek --limit 10
python3 scripts/run_llm.py --scenario 2.1 --stage programmer --redo-bad
cat runs/scenario2.1/programmer/responses/*/summary.json
```

想要"只给函数名和文档、不给编译上下文"的版本，把 `scenarios/scenario2.1/config.toml` 里 `show_file_includes`、`show_shared_helpers`、`show_same_file_defs` 改成 false。

## 8. 汇总

```sh
python3 scripts/summary_table.py                 # 场景 | 阶段 | 上游模型 | 模型 | total | ok | trunc | err | tokens
python3 scripts/summary_table.py --csv > runs/summary.csv
```

---

## 9. 完整流程速查

从零开始到两个场景都跑完，按顺序：

```sh
source ~/wine_fuzz/venv/bin/activate
cd ~/wine_fuzz/wine_bench
sh scripts/setup_wine_build.sh ../wine_src/wine ../wine-build          # 1 头文件（一次）
# 2 数据集已在 dataset/wine500，跳过；要重做见 2.2
cp secrets.toml.example secrets.toml && open -e secrets.toml           # 3 填密钥

python3 scripts/build_prompts.py --scenario 1.1                        # 5 场景 1.1 架构师
python3 scripts/run_llm.py       --scenario 1.1 --redo-bad
python3 scripts/build_prompts.py --scenario 1.1 --stage programmer --from-model deepseek     # 7 程序员
python3 scripts/run_llm.py       --scenario 1.1 --stage programmer --from-model deepseek --redo-bad

python3 scripts/build_prompts.py --scenario 1.2                        # 6 场景 1.2 架构师
python3 scripts/run_llm.py       --scenario 1.2 --redo-bad
python3 scripts/build_prompts.py --scenario 1.2 --stage programmer --from-model deepseek
python3 scripts/run_llm.py       --scenario 1.2 --stage programmer --from-model deepseek --redo-bad

python3 scripts/build_prompts.py --scenario 2.1 --stage programmer     # 7.2 场景 2.1（数据集 wine500_doc）
python3 scripts/run_llm.py       --scenario 2.1 --stage programmer --redo-bad

python3 scripts/summary_table.py                                       # 8 汇总
```

### 9.1 一键全跑：run_all.sh

提示词都生成过之后，`scripts/run_all.sh` 把上面第 5–8 步对**所有启用的模型**串起来：1.1 架构师 → 1.2 架构师 → 每个模型用**自己**的需求跑 1.1 / 1.2 程序员 → 2.1 程序员 → 汇总。每个阶段先正常跑一遍，再 `--redo-bad` 补一遍。已有的回复一律跳过，所以中断后重跑同一条命令就是续跑。

```sh
PY=~/wine_fuzz/venv/bin/python bash scripts/run_all.sh                     # 全部启用的模型
PY=~/wine_fuzz/venv/bin/python bash scripts/run_all.sh claude-haiku-5-5    # 只跑一个（或逗号分隔几个）
LIMIT=5 PY=~/wine_fuzz/venv/bin/python bash scripts/run_all.sh             # 试跑：每个阶段前 5 条
```

要让"A 的需求交给 B 实现"，仍然手动用 7.1 的命令。

---

## 10. 常见问题

- **`bad-format` / `TRUNCATED`**：回复撞到了输出上限（`summary.json` 里 `truncated` 计数）。`[run].max_tokens = 0` 表示不设上限、由厂商决定；DeepSeek 不传时默认 4096，所以 `models.toml` 里给它单独写了 8192（它的最大值）。用 `--redo-bad` 重试；温度为 0 时结果可能一样，那就记为失败。
- **`skipped: no key`**：`secrets.toml` 里对应的名字是空的，或者文件不存在。
- **`skipped: enabled = false`**：到 `scenarios/models.toml` 里把那个模型的 `enabled` 改成 true。
- **HTTP 400 / 404**：多半是 `model` 字段的模型 ID 过期了，到厂商的模型页核对。
- **`N skipped: no usable architect reply`**（程序员阶段）：那些 id 的架构师回复缺失或格式不对，先用 `--redo-bad` 把架构师阶段补齐。
- **libclang 报 `Unknown template argument kind`**：pip 的绑定比库旧，脚本里已做兼容；如果仍出现，`pip install -U libclang`。
- **macOS 上 Unix 侧函数解析报 `assert.h not found`**：脚本已通过 `xcrun` 找 SDK；确认 `xcode-select --install` 装过。
- **1.2 的提示词太长**：`scenarios/scenario1.2/config.toml` 里 `same_file_deps_max_items`（默认 10）和 `*_max_lines`。

---

## 11. 评测：编译 + 测试（Linux）

生成阶段在 macOS 上做，评测在 Ubuntu 上做：Wine 只能在 Linux 上完整编译和跑测试。

### 11.1 打包，搬到 Ubuntu

在 Mac 上（排除文档仓库、归档、密钥、提示词的 .md 副本）：

```sh
cd ~/wine_fuzz
tar czf wine_bench_eval.tgz --exclude='wine_bench/external' --exclude='wine_bench/_archive' \
    --exclude='wine_bench/secrets.toml' --exclude='__pycache__' --exclude='*/prompts/*.md' wine_bench
scp wine_bench_eval.tgz ubuntu:~/            # 或 U 盘 / 网盘
```

需要的只有 `dataset/`（函数位置和原代码）、`runs/**/responses/*/<id>.c`（生成的代码）和 `scripts/`、`scenarios/`。回来时把 `runs/` 里新出现的 `eval/` 和 `baseline/` 目录拷回 Mac 即可。

### 11.2 Ubuntu 上一次性准备

```sh
tar xzf wine_bench_eval.tgz && cd wine_bench
bash scripts/setup_eval_ubuntu.sh            # 装依赖，克隆 wine-11.18 到 ~/wine，编译到 ~/wine-build，编译全部测试，建 ~/.wine-bench
```

30–90 分钟。Wine 源码必须和数据集同一版本（11.18），脚本会检查。编译用 ccache，后面每条记录的"改 → 编 → 还原 → 再编"只有一次真正的编译。

### 11.3 评测一个模型

```sh
cd ~/wine_bench
xvfb-run -a python3 scripts/evaluate.py --src ~/wine --build ~/wine-build \
    --scenario 1.1 --stage programmer --from-model claude-haiku-5-5 --models claude-haiku-5-5
xvfb-run -a python3 scripts/evaluate.py --src ~/wine --build ~/wine-build --scenario 2.1 --stage programmer   # 不带 --models = 该阶段所有模型
python3 scripts/evaluate.py --table                                                                           # 汇总表（--csv 输出 CSV）
```

`xvfb-run -a` 提供一个虚拟显示器：user32 / gdi32 等模块的测试没有显示器就跑不了。每条记录做四件事：

1. **替换**（`bench/csplice.py`）：把 `<id>.c` 放进该函数所在的源文件。目标函数整个替换；模型额外定义的辅助函数，文件里已有同名的就**原位替换**，没有的就**加在目标函数前面**；模型写的宏 / 类型 / 全局变量同理（文件里已有的丢弃，避免重定义）；`#include` 加到文件原有的 include 后面。替换细节记在结果的 `splice` 字段里。
2. **编译**：`make` 该模块的 dll（只重编改过的那个 .c 再链接，几秒到几十秒）。共用源码的模块（msvcrt 家族）只编译被测的那个。失败时记录前 30 条 `error:`。
3. **测试**：对数据集里记录的、引用了该导出名的每个测试文件（`native_tests.files`）跑 `make dlls/<模块>/tests/<文件>.ok`，和**未改动的 Wine 上同一测试的结果**（baseline，第一次遇到时自动跑一次并缓存到 `runs/baseline/`）比较。只有**新出现**的失败行（`文件:行`）才算失败；失败的测试会再跑一次，两次都失败才算数（Wine 的测试有少量不稳定项）。`todo_wine` 块里"意外通过"的（模型比 Wine 原实现做得更对）单独记在 `todo_fixed`，默认不算失败（`--strict-todo` 则算）。
4. **还原**：写回原文件，再 `make` 一次让树回到干净状态。中断了下次启动会先用 `eval/` 里的备份把源文件复原。

结果 `runs/<场景>/<阶段>[/from_M]/eval/<模型>/<id>.json`，`status` 取值：

| status | 含义 |
|---|---|
| `no_code` | 生成阶段没有可用回复 |
| `splice_fail` | 回复里没有目标函数的定义，或者源码和数据集对不上 |
| `compile_fail` | 编译 / 链接失败（`compile.errors`） |
| `test_fail` / `crash` / `timeout` | 编译过了，测试有新失败 / 测试进程崩了 / 超过 `--timeout`（默认 600 秒） |
| `pass` | 编译过了，所有相关测试没有新失败 |
| `no_tests` | 编译过了，但相关测试在 baseline 上就跑不了（超时 / 崩溃），无法判定 |

每条还有 `identical`（去掉注释和空白后和原实现完全一致）和 `similarity`（0–1，difflib 相似度），对应指标 4。`summary.json` 汇总：`compiled`、`passed`、`identical`、`mean_similarity` 等。

其他参数：`--limit N` / `--ids` 只评测部分记录；`--redo` 重做已有结果；`--no-tests` 只编译；`--dry-run` 只做替换、把拼好的文件写成 `eval/<模型>/<id>.spliced.c`（不需要 Wine 构建，Mac 上也能跑，用来检查替换逻辑）；`--baseline` 只跑干净树上的基线；`--jobs`、`--timeout`、`--compile-timeout`、`--prefix`。

全部评测（所有场景 × 所有有回复的模型），`scripts/eval_all.sh`：

```sh
LIMIT=20 bash scripts/eval_all.sh            # 先每个组合跑 20 条看成功率
bash scripts/eval_all.sh                     # 全部；中断了重跑即续跑
bash scripts/eval_all.sh claude-haiku-5-5    # 只跑一个模型
```

Wine 不在默认位置时 `WINE_SRC=... WINE_BUILD=...`，给 evaluate.py 传额外参数用 `EVAL_OPTS="--timeout 300"`。脚本自动套上 `xvfb-run -a`。

每条记录大约 20 秒到几分钟（取决于测试文件的长短），500 条一轮约 3–8 小时，总共 18 轮，适合挂着跑几天；中断了重跑同一条命令会接着跑。

---

## 12. 扩展

代码拆分的原则是：新场景只改配置和模板，不改代码。

- **新场景**：复制 `scenarios/scenario1.2/` 为 `scenarios/scenarioX/`，改 `config.toml` 里的 `[paths].out`、各阶段的 `[stage.*.inputs]` 开关，以及 `templates/*.txt`。用 `--scenario X` 运行。
- **新阶段**：在场景 config 里加 `[stage.<名字>]` 和 `[stage.<名字>.inputs]` 及其模板；用 `--stage <名字>` 运行。消费上一阶段回复的阶段设置 `input_stage = "<上一阶段>"`，运行时带 `--from-model`；上一阶段的回复在 section 函数里以 `ctx["upstream"]` 访问。多个场景共用的模板放在 `scenarios/common/templates/`。
- **新的输入类型**（比如场景 2.1 的外部文档）：在 `scripts/bench/prompt.py` 里加一个用 `@section('名字')` 装饰的函数，模板里写 `{{名字}}`，别的不用动。
- **新模型厂商**：在 `scripts/bench/llm.py` 里加一个 `call_<名字>()` 并登记到 `PROVIDERS`。
- **回复格式**（每个阶段可不同）：`reply_format = "code"`（C 代码，另存 .c）；JSON 表单（`required_headings = []`，表单写在 system 模板里）；Markdown 标题（`required_headings = ["## Purpose", ...]`，1.1 的 `system_markdown_oneshot.txt` 是现成的例子，配 `one_shot = true`）。
- **提示词里的 "{{project_name}}"** 默认是 "a Windows compatibility layer" 而不是 "Wine"，避免模型直接回忆 Wine 源码；要改在各阶段的配置里。
