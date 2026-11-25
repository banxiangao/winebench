"""Shared pieces of the benchmark tooling.

config.py   scenario config, paths, model list, secrets
dataset.py  reading dataset records
prompt.py   building prompts from a record + templates (section registry = the extension point)
llm.py      calling models (OpenAI-compatible, Anthropic), retries, truncation
report.py   checking / parsing replies, per-model summaries
"""
