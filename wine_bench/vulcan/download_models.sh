#!/usr/bin/env bash
# download_models.sh - fetch the weights on the LOGIN node (compute nodes may have no internet) into ~/scratch/models/<name>.
#
#   bash vulcan/download_models.sh                      # every model in MODELS below
#   bash vulcan/download_models.sh qwen3.8-27b           # one
#
# <name> is the folder name AND the model name used in scenarios/models.toml and in the results (responses/<name>/).
# Repo ids: check them on https://huggingface.co before the first run (names of 2026 models were taken from third-party
# pages).  Gated repos (Gemma, Mistral) need:  $VENV/bin/hf auth login
set -e
WB=$(cd "$(dirname "$0")/.." && pwd); PROJ=${PROJ:-$(dirname "$WB")}; VENV=${VENV:-$PROJ/venv-vllm}
[ -x "$VENV/bin/python" ] || { echo "$VENV: no venv yet - run  bash vulcan/setup_vulcan.sh  first"; exit 1; }
export HF_HOME=${HF_HOME:-$HOME/scratch/hf}
module load gcc opencv/4.11 python/3.12 2>/dev/null || module load gcc opencv python/3.12
module load arrow 2>/dev/null || true
declare -A REPO=(
    [qwen3.8-27b]="Qwen/Qwen3.8-27B"                      # Qwen, 27B dense           <-> API qwen3-8-flash
    [glm-4.7-flash]="zai-org/GLM-4.7-Flash"              # Zhipu, 30B class          <-> API glm-4-7-flashx
    [gpt-oss-20b]="openai/gpt-oss-20b"                   # OpenAI, 21B MoE           <-> API openai-gpt-6-luna
    [gemma-4-31b]="google/gemma-4-31b-it"                # Google (gated: accept the licence on HF first)
    [devstral-small-2]="mistralai/Devstral-Small-2"      # Mistral, 24B, code-specialised (check the exact repo id)
)
MODELS=${*:-qwen3.8-27b glm-4.7-flash gpt-oss-20b gemma-4-31b devstral-small-2}
for name in $MODELS; do
    repo=${REPO[$name]:?unknown model $name (edit REPO in this script)}
    dst=$HOME/scratch/models/$name
    if [ -f "$dst/config.json" ]; then echo "$name: already in $dst"; continue; fi
    echo "== $name <- $repo"
    "$VENV/bin/hf" download "$repo" --local-dir "$dst" --exclude "*.gguf" --exclude "original/*" --exclude "*.pth" \
        || "$VENV/bin/huggingface-cli" download "$repo" --local-dir "$dst" --exclude "*.gguf" --exclude "original/*" --exclude "*.pth"
    du -sh "$dst"
done
echo "done.  Next:  sbatch vulcan/generate.sbatch <name>   (one job per model)"
