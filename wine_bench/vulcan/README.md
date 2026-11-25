> **2026-11-20 起：提交方式改为一个作业一个设置，见 `../../vulcan/README.md`（`bash vulcan/submit.sh ...`）。下文提到的 `agents.sbatch` / `generate.sbatch` 已移到 `legacy/`，仅供参考。**

# 在 Vulcan 上用本地模型跑场景 1.3 / 1.4

生成在 Vulcan（2× L40S，vLLM，bf16），评测回 Ubuntu 机器做。提示词用 `runs/scenario1.x/programmer/prompts/` 里已经生成好的
500 条，和 API 模型完全相同：只给函数名（1.3）或函数名 + 微软文档（1.4），一次回答，不看仓库，不编译。

```sh
# 登录节点，一次性。路径随意：venv 会建在 wine_bench 的旁边（例如 .../WineBench/venv-vllm）
cd ~/projects/aip-zhouyang/xingan1/WineBench && tar xzf wine_bench_vulcan.tgz && cd wine_bench
# （scenarios/models.toml 已经包含本地模型条目，不用再追加）
bash vulcan/setup_vulcan.sh                                  # venv + vLLM（集群轮子）
bash vulcan/download_models.sh                               # 权重 -> ~/scratch/models/<name>（Gemma/Mistral 要先 hf auth login）

# 每个模型一个作业（2 张 L40S，3 小时）。必须在 wine_bench 目录下执行 sbatch
mkdir -p vulcan/logs
sbatch vulcan/generate.sbatch qwen3.8-27b
sbatch vulcan/generate.sbatch glm-4.7-flash
sbatch vulcan/generate.sbatch gpt-oss-20b
squeue -u $USER; tail -f vulcan/logs/winebench-gen-<jobid>.out

# 结果回 Ubuntu 评测（在 Ubuntu 上运行）
rsync -av xingan1@vulcan.alliancecan.ca:projects/aip-zhouyang/xingan1/WineBench/wine_bench/runs/scenario1.3/programmer/responses/ \
      /media/banxiangao/D/wine_fuzz/wine_bench/runs/scenario1.3/programmer/responses/
rsync -av xingan1@vulcan.alliancecan.ca:projects/aip-zhouyang/xingan1/WineBench/wine_bench/runs/scenario1.4/programmer/responses/ \
      /media/banxiangao/D/wine_fuzz/wine_bench/runs/scenario1.4/programmer/responses/
cd /media/banxiangao/D/wine_fuzz/wine_bench
SCENARIOS="1.3 1.4" WORKERS=4 bash scripts/run_eval_ubuntu.sh qwen3.8-27b,glm-4.7-flash,gpt-oss-20b
```

- `<name>` 同时是权重目录名、`models.toml` 里的名字和结果目录名（`responses/<name>/`）。
- 思考模式都关掉（Qwen / GLM 用 `enable_thinking = false`，gpt-oss 只能降到 `reasoning_effort = "low"`），回复是一段代码，和 API 跑法一致。
- 作业脚本先在计算节点起 vLLM，等 `/health` 通了再跑 `run_llm.py`，结束时关掉服务。重复提交同一个作业会跳过已有结果；`REDO=1 sbatch ...` 重查出错的。
- 仓库 id 来自 2026 年 11 月的第三方汇总页，第一次用前在 Hugging Face 上确认一下，改 `download_models.sh` 里的 `REPO` 表即可。
