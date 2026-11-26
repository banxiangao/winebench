# 图

两张开销图，数据全部取自 `results/metrics_settings.csv`，每根柱子是一个设置 205 个任务的平均值。
每张图有三种格式：`.pdf`（矢量，论文用）、`.png`（300 dpi）、`.svg`。

| 文件 | 内容 |
|---|---|
| `cost_agent` | agent 实验每个任务的开销：耗时、输入 token、输出 token、步数。上半是场景 3.2（五个模型），下半是场景 3.1（三个本地模型），两种框架并排。 |
| `cost_oneshot` | 单次生成的开销：每次回复的耗时、提示词 token、每次回复的输出 token。六个模型，场景 1.3 和 1.4 并排。 |

重新生成（需要 matplotlib；在 Vulcan 上用集群自带的）：

```bash
sbatch figures/make_figures.sbatch        # 或者本地：python3 figures/make_figures.py
```

读图时注意：

- **耗时在本地模型和商业模型之间不能直接比。** 本地模型是两张 L40S 上多个任务并行，商业模型走厂商接口。
- **单次生成里本地模型的"每次回复耗时"** 是一个任务 100 次采样的总耗时除以 100，是吞吐量意义上的平均，不是单个请求的延迟。
- **agent 的输入 token** 是每一步重发历史累加的结果，所以远大于单次生成。
- deepseek-v4-flash 只有单次生成，没有 agent 的数据。
