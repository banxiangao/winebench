> **2026-11-20 起：提交方式改为一个作业一个设置，见 `../../vulcan/README.md`（`bash vulcan/submit.sh ...`）。下文提到的 `agents.sbatch` / `generate.sbatch` 已移到 `legacy/`，仅供参考。**

# 在 Vulcan 上用本地模型跑 agent（场景 3.1 / 3.2）

模型由 vLLM 在作业节点上提供（2× L40S）；agent（mini-swe-agent、OpenHands）和它执行的所有命令都在容器
`../container/wine-agent.sif`（Ubuntu 22.04 + mingw + 两个 agent）里运行，工作目录是受限的 Wine 源码树
（没有测试、没有 git 历史、目标函数挖空、只有 ./compile）。任务文本、规则和上限与 API 模型的 agent 实验完全相同。

目录（都在 WineBench/ 下）：`wine_agent/`（本包）、`venv-vllm/`、`container/wine-agent.sif`；
`~/scratch/models/<name>`（权重）、`~/scratch/winebench-w/{wine,wine-build}`（干净的 Wine，container/build_wine.sbatch 编译）、
`~/scratch/winebench-trees/<name>/`（每个模型自己的受限树，第一次运行时自动创建）。

```sh
cd ~/projects/aip-zhouyang/xingan1/WineBench/wine_agent      # 必须在这个目录下 sbatch
N=500 AGENT_WORKERS=6 sbatch vulcan/agents.sbatch qwen3.8-27b   # 每个模型提交一次即可
tail -f vulcan/logs/winebench-agents-<jobid>.out
```

短作业接力：每个作业的时限是 3 小时（短作业排队快得多），资源是 2 张 L40S、12 核、64 GB。作业在到时限前 10 分钟
停止派发新任务；如果还有记录没跑完、而且这一轮有进展，它会用同样的设置自己提交下一个作业，直到全部跑完。
所以每个模型只需要 sbatch 一次。`CHAIN=0` 关闭接力；想中止就 `scancel` 掉最后那个作业。没有剩余任务的作业
会在加载模型之前直接退出。每个作业的开头和结尾都会打印进度（`progress: 已完成 / 总数`）。

可调：`N`、`AGENTS="mini_swe openhands"`、`SCENARIOS="3.1 3.2"`、`AGENT_WORKERS=4`（并行条数 = 受限树的份数）、
`MAX_MODEL_LEN=65536`、`REDO=1`（重跑出错的）。

工具调用：本地模型在两个 agent 里都用**文本模式**（mini-swe-agent 的 text-based 模型类：命令写在
`mswea_bash_command` 代码块里；OpenHands 的 prompt-based function calling），不依赖 vLLM 的工具调用解析。原因是先试过
服务端解析，在集群的 vLLM 上不可靠：Qwen3.8 的格式要换解析器，gpt-oss 的工具名会被解析成 `bashjson` / `terminaljson`，
导致 mini-swe-agent 几乎全部以 RepeatedFormatError 结束。三个本地模型统一用一种模式也便于相互比较。每条结果的
`tool_mode` 字段记录了模式；以另一种模式跑出的旧结果会自动重跑（旧文件保留为 `<id>.attemptN.json`）。
采样参数用模型自带的 generation_config.json（不发送 temperature），思考模式关闭。

受限源码树的 git 仓库放在树外（`<树>.gitdir`，树里只有一个指向它的 .git 文件）：agent 删掉或重建 .git、自己提交，
都不会破坏每条任务开始时复位用的干净提交，也不影响取 patch（patch 始终相对任务开始时的提交）。

结果在 `runs/scenario3.x/<agent>/responses/<name>/`，拷回 Ubuntu 的 wine_agent 对应位置后评测：
`N=500 AGENTS="mini_swe openhands" MODELS=<name> STEP=eval bash scripts/run_swe_ubuntu.sh`
