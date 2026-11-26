# Vulcan 上的本地模型实验：一个作业 = 一个设置

术语：**任务** = 让模型生成一个函数实现的一次尝试（数据集里的一条记录）；**作业** = 一个 Slurm 作业；
**设置** = 模型 + 场景（+ harness）。一个生成作业只跑一个设置；跑完后自动提交这个设置的评测作业。

| 场景 | 内容 | harness | 代码在 |
|---|---|---|---|
| 1.3 | 只给函数名，一次回答 | oneshot（无 agent） | `wine_bench/` |
| 1.4 | 函数名 + 微软文档，一次回答 | oneshot | `wine_bench/` |
| 3.1 | 函数名 + 源码树，agent 在树里工作、可编译 | mini_swe / openhands | `wine_agent/` |
| 3.2 | 同 3.1，另给微软文档 | mini_swe / openhands | `wine_agent/` |

```sh
cd ~/projects/aip-zhouyang/xingan1/WineBench
bash vulcan/submit.sh list                         # 所有设置：已生成、已评测、队列里的作业
bash vulcan/submit.sh qwen3.8-27b 3.1 openhands    # 提交一个 agent 设置（生成，GPU；完成后自动评测）
bash vulcan/submit.sh qwen3.8-27b 1.3              # 提交一个 oneshot 设置
bash vulcan/submit.sh eval qwen3.8-27b 3.1 openhands   # 只提交评测（CPU）
bash vulcan/submit.sh table                        # 看数字
N=12 CHAIN=0 bash vulcan/submit.sh glm-4.7-flash 3.2 mini_swe --time=0:30:00   # 小规模试跑：前 12 个任务
```

## 流程

1. **一次性准备**（已做过）：`wine_bench/vulcan/setup_vulcan.sh`（vLLM 环境）、`download_models.sh`（权重）、
   `container/build_wine.sbatch`（在容器里编译 Wine 11.18，含全部测试）。
2. **打包树**（一次；Wine 构建、容器或 `make_swe_trees.sh` 变了要重做）：`cd wine_agent && sbatch vulcan/pack_trees.sbatch`
   → `~/scratch/winebench-w/swe-pair.tar`（agent 用的受限树：无测试、无历史）和 `eval-pair.tar`（评测用的干净树，含测试）。
3. **生成**（GPU 作业 `wb-<场景>-<harness>-<模型>`）：vLLM 在作业节点上；agent 设置把受限树解到节点本地盘，每个 worker 一对。
4. **评测**（CPU 作业 `wb-eval-<场景>-<harness>-<模型>`，生成完成后自动提交）：把干净树解到节点本地盘，把每个任务生成的代码
   放进去，编译所在模块，运行 Wine 自己的测试，与干净树上同一测试的结果（baseline）比较。

## 结果在哪

| 内容 | 位置 |
|---|---|
| 生成结果 | `<包>/runs/scenario<S>/<stage>/responses/<模型>/<编号>.json`（agent 另有 `.patch`、`.traj.json`；oneshot 另有 `.c`） |
| 评测结果（每个任务） | `<包>/runs/scenario<S>/<stage>/eval/<模型>/<编号>.json`，`summary.json` |
| 数字汇总表 | `<包>/results/table.txt`、`table.csv` |
| baseline（干净树上的测试结果） | `wine_agent/runs/baseline/`（所有设置共用） |
| 每个设置的作业记录 | `<包>/runs/scenario<S>/<stage>/jobs/<模型>.jsonl` |
| 作业日志 | `<包>/vulcan/logs/<作业名>-<作业号>.out`，vLLM 日志同目录 |

`<包>` = `wine_agent`（3.x）或 `wine_bench`（1.x）；`<stage>` = harness 名，oneshot 是 `programmer`（两次采样：`<模型>-s1`、`-s2`）。
评测状态：`no_code` 没有代码 | `splice_fail` 放不进源文件 | `compile_fail` | `test_fail` | `crash` | `timeout` | `pass` | `no_tests`。

## 要点

- 所有设置和每个生成作业申请的资源在 `vulcan/experiments.tsv`；`submit.sh` 只接受表里有的设置。
- 断点续跑：任务结束才写结果，评测也一样。重新提交同一个设置只做还没有结果的任务。作业在时限前 10 分钟停下并自动
  提交下一个（`CHAIN=0` 关闭）；`REDO=1` 重跑出错的任务。
- 评测只在设置生成完整后进行（否则没结果的任务会被记成 `no_code`）；`FORCE=1` 可强制。
- 数据集：`wine_agent/dataset/wine500_doc`，464 条（`wine_bench/dataset` 是指向它的链接）。移出的 36 条没有编译目标的记录
  在 `wine500_doc_excluded/`，清单 `excluded_no_build_target.tsv`。
- 旧架构下的全部结果在 `archive/2026-11-20_before-restructure/`。旧脚本在各包的 `vulcan/legacy/`，不要再用。

## 商业模型（通过厂商接口，不占 GPU）

入口是 `vulcan/submit_api.sh`，作业脚本是 `vulcan/run_api.sbatch`，数据集、提示词、评测都和本地模型相同。

```bash
bash vulcan/submit_api.sh probe                               # 密钥是否有效、接口实际提供的模型编号
bash vulcan/submit_api.sh claude-haiku-5-5 1.4                # 单次生成（1.3 | 1.4），每个任务一个回复
bash vulcan/submit_api.sh openai-gpt-6-luna 3.2 mini_swe      # agent（mini_swe | openhands）
N=5 CHAIN=0 bash vulcan/submit_api.sh claude-haiku-5-5 3.2 openhands --time=0:40:00    # 试跑前 5 个任务
bash vulcan/submit_api.sh list                                # 各设置的进度、重试数、生成失败数
```

- 模型：`scenarios/models.toml` 里的 `claude-haiku-5-5`、`openai-gpt-6-luna`、`deepseek-v4-flash`（都关闭了思考）。
- 密钥：`~/.config/winebench/secrets.toml`（权限 600，格式同 `wine_bench/secrets.toml.example`），不放在项目目录里，
  因为项目目录全组可读。
- 网络：计算节点只能经集群代理出网，代理是白名单：`api.openai.com`、`api.anthropic.com` 可达，
  `api.deepseek.com` 被拒绝（403，2026-11-25 测）。代理只给调用模型的进程；agent 自己的命令行里代理是清空的。
- 在集群以外、能直接联网的机器上跑 agent（例如 DeepSeek）：设 `WB_AGENT_OFFLINE=1`，agent 命令行里的代理会被指向
  一个不存在的地址（`127.0.0.1:9`），`curl`、`wget`、`pip`、`git`、Python 的网络请求都出不去，调用模型的进程不受影响。
  用 `apptainer exec --containall` 时变量要传进容器：运行前 `export APPTAINERENV_WB_AGENT_OFFLINE=1`。这不是防火墙，
  不理会代理变量的程序拦不住。每个任务的结果里 `agent_network` 记下了当时的方式
  （`dead_proxy` / `proxy_blanked` / `unchanged`）。
- 每个任务最多生成两次（`GEN_ATTEMPTS=2`）：第一次因接口、网络或运行器出错而没有拿到结果时才有第二次；
  第二次仍失败则记 `generation_failed = true`，以后不再重试。回复里没有可用代码、回复被截断、agent 撞到步数/
  时间/编译次数上限、对话超出模型上下文，都算任务的结果而不是生成失败。第一次的结果保留为 `<id>.attempt1.json`。
- 结果：单次生成在 `wine_bench/runs/scenario<S>/programmer/responses/<模型>/`，agent 在
  `wine_agent/runs/scenario<S>/<框架>/responses/<模型>/`；`results/metrics_tasks.csv` 里单次生成的框架名是 `oneshot1`，
  另有 `attempts`、`generation_failed` 两列。

## 评测的内存上限

`evaluate.py`（两个包各一份）会监视它启动的每个编译和测试：进程合计常驻内存超过 4096 MB（`--mem-limit-mb`，或环境变量
`WB_MEM_LIMIT_MB`，0 为关闭）就整组杀掉，测试记为 `crash`（测试结果里带 `mem_killed`），编译记为失败；作业内存
（匿名加共享）超过上限的 90% 时杀掉占用最大的那个命令。日志里以 `[mem]` 开头的行记录每次处理。加它的原因：生成的
代码偶尔会无限吃内存，整个评测进程会被系统杀掉（2026-11-25，gpt-oss 1.3 的一个分片连续三次）。
