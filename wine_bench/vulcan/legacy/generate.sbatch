#!/usr/bin/env bash
#SBATCH --job-name=winebench-gen
#SBATCH --gres=gpu:l40s:2
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=3:00:00
#SBATCH --output=vulcan/logs/%x-%j.out
# generate.sbatch - one model, scenarios 1.1 and 1.2 (name only / name + Microsoft docs), one-shot, no repository, no
# compiling: exactly the programmer stage of the API runs, served by vLLM on 2 L40S (bf16, tensor parallel).
#
#   cd .../wine_bench            (sbatch must be run from the wine_bench directory)
#   sbatch vulcan/generate.sbatch qwen3.8-27b                 # <name> = folder under ~/scratch/models and the model name
#   sbatch vulcan/generate.sbatch gpt-oss-20b
#   SCENARIOS="1.1" sbatch vulcan/generate.sbatch glm-4.7-flash
#   squeue -u $USER;  tail -f vulcan/logs/winebench-gen-<jobid>.out
#
# Results: runs/scenario1.x/programmer/responses/<name>/<id>.{json,c} - copy back to the Ubuntu box for evaluation.
# Re-running the same job skips records that already have a reply (skip_existing); REDO=1 re-queries bad ones.
set -e
NAME=${1:?model name (folder under ~/scratch/models)}
WB=${SLURM_SUBMIT_DIR:-$PWD}                             # sbatch is run from the wine_bench directory
[ -f "$WB/scripts/run_llm.py" ] || { echo "$WB is not the wine_bench directory: cd into it and sbatch again"; exit 1; }
PROJ=${PROJ:-$(dirname "$WB")}; VENV=${VENV:-$PROJ/venv-vllm}
[ -x "$VENV/bin/vllm" ] || { echo "$VENV: no vLLM venv (bash vulcan/setup_vulcan.sh)"; exit 1; }
cd "$WB"
SCENARIOS=${SCENARIOS:-"1.1 1.2"}; WORKERS=${WORKERS:-32}; PORT=${PORT:-$((20000 + SLURM_JOB_ID % 20000))}; export WB_LOCAL_PORT=$PORT
MODEL_DIR=$HOME/scratch/models/$NAME
[ -f "$MODEL_DIR/config.json" ] || { echo "$MODEL_DIR: no weights (vulcan/download_models.sh $NAME)"; exit 1; }
module purge 2>/dev/null; module load StdEnv/2023 2>/dev/null || true
module load gcc opencv/4.11 python/3.12 2>/dev/null || module load gcc opencv python/3.12
module load cuda 2>/dev/null || module load cuda/12.6 || true
module load arrow 2>/dev/null || true      # the same modules the venv was built with
export HF_HOME=$HOME/scratch/hf HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 VLLM_LOGGING_LEVEL=WARNING
export TMPDIR=${SLURM_TMPDIR:-/tmp}
NGPU=$(nvidia-smi -L | wc -l); echo "node $(hostname), $NGPU GPU(s): $(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)"

echo "== vLLM serve $NAME from $MODEL_DIR (tp=$NGPU)"
"$VENV/bin/vllm" serve "$MODEL_DIR" --served-model-name "$NAME" --port "$PORT" --tensor-parallel-size "$NGPU" \
    --dtype bfloat16 --max-model-len "${MAX_MODEL_LEN:-32768}" --gpu-memory-utilization 0.92 --trust-remote-code \
    > "vulcan/logs/vllm-$NAME-$SLURM_JOB_ID.log" 2>&1 &
VPID=$!
trap 'kill $VPID 2>/dev/null; wait $VPID 2>/dev/null' EXIT
for i in $(seq 1 120); do                                      # loading 27B takes a few minutes
    curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && break
    kill -0 $VPID 2>/dev/null || { echo "vLLM died, see vulcan/logs/vllm-$NAME-$SLURM_JOB_ID.log"; tail -30 "vulcan/logs/vllm-$NAME-$SLURM_JOB_ID.log"; exit 1; }
    sleep 10
done
curl -sf "http://127.0.0.1:$PORT/health" >/dev/null || { echo "vLLM did not come up in 20 min"; exit 1; }
curl -s "http://127.0.0.1:$PORT/v1/models" | head -c 300; echo

RUNS=${RUNS-"s1 s2"}
MODELS=$NAME; [ -n "$RUNS" ] && MODELS=$(for r in $RUNS; do printf '%s-%s,' "$NAME" "$r"; done | sed 's/,$//')
echo "sampling defaults of the model (generation_config.json): $(tr -d '\n ' < "$MODEL_DIR/generation_config.json" 2>/dev/null || echo none)"
for S in $SCENARIOS; do
    echo "===== scenario $S, programmer $MODELS"
    "$VENV/bin/python" scripts/run_llm.py --scenario "$S" --stage programmer --models "$MODELS" --workers "$WORKERS" ${REDO:+--redo-bad}
done
"$VENV/bin/python" scripts/summary_table.py | grep -E "^scenario |$NAME"
echo "done: runs/scenario{1.1,1.2}/programmer/responses/$NAME/"
