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
