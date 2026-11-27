#!/bin/bash
#SBATCH --job-name=wb-run
#SBATCH --account=aip-zhouyang
#SBATCH --gres=gpu:l40s:2
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=1:00:00
#SBATCH --output=vulcan/logs/%x-%j.out
# run_setting.sbatch (one-shot scenarios) - ONE setting per job: one model, one scenario (1.1 = name only, 1.2 = name +
# Microsoft docs), over the whole benchmark.  One reply per task, no repository, no compiling.
# Submit it through the common entry point, which takes the resources from ../vulcan/experiments.tsv:
#
#   cd .../WineBench && bash vulcan/submit.sh qwen3.8-27b 1.1
#
# The setting is sampled RUNS times (default "s1 s2": the models <name>-s1, <name>-s2 of scenarios/models.toml, fixed
# seeds 1 and 2); RUNS="" queries the plain <name> once.  Results: runs/scenario<S>/programmer/responses/<name>[-sK]/.
# Recovery: tasks that already have a reply are skipped, so submitting the same setting again continues it; a job that
# finds every reply present exits before it loads the model.  REDO=1 re-queries replies that errored or had no code.
# Every job appends a line to runs/scenario<S>/programmer/jobs/<name>.jsonl when it starts and when it ends.
set -e
NAME=${1:?model (folder under ~/scratch/models)}; S=${2:?scenario: 1.1 | 1.2}
WB=${SLURM_SUBMIT_DIR:-$PWD}
[ -f "$WB/scripts/run_llm.py" ] || { echo "$WB is not the wine_bench directory"; exit 1; }
WB=$(realpath "$WB"); PROJ=${PROJ:-$(dirname "$WB")}; VENV=${VENV:-$PROJ/venv-vllm}
[ -x "$VENV/bin/vllm" ] || { echo "$VENV: no vLLM venv (bash vulcan/setup_vulcan.sh)"; exit 1; }
[ -f "$WB/scenarios/scenario$S/config.toml" ] || { echo "no scenario $S"; exit 1; }
cd "$WB"; STAGE="runs/scenario$S/programmer"; mkdir -p vulcan/logs "$STAGE/jobs"
N=${N:-100000}; export N RUNS EVAL EVAL_TIME EVAL_WORKERS
WORKERS=${WORKERS:-32}; PORT=${PORT:-$((20000 + SLURM_JOB_ID % 20000))}; export WB_LOCAL_PORT=$PORT
MODEL_DIR=$HOME/scratch/models/$NAME
[ -f "$MODEL_DIR/config.json" ] || { echo "$MODEL_DIR: no weights (vulcan/download_models.sh $NAME)"; exit 1; }
RUNS=${RUNS-"s1 s2"}
MODELS=$NAME; [ -n "$RUNS" ] && MODELS=$(for r in $RUNS; do printf '%s-%s,' "$NAME" "$r"; done | sed 's/,$//')
T0=$SECONDS
count_done() {                                                                       # -> "<replies present> <replies wanted>"
    local c=0 p m
    p=$(ls "$STAGE/prompts" 2>/dev/null | grep -cE '^[0-9]{4}\.json$' || true)
    for m in ${MODELS//,/ }; do c=$((c + $(ls "$STAGE/responses/$m" 2>/dev/null | grep -cE '^[0-9]{4}\.json$' || true))); done
    [ "$p" -gt "$N" ] && p=$N; local k; k=$(echo "${MODELS//,/ }" | wc -w); [ "$c" -gt $((p * k)) ] && c=$((p * k)); echo "$c $((p * k))"
}
jobline() { printf '{"job": "%s", "event": "%s", "time": "%s", "model": "%s", "scenario": "%s", "harness": "none", %s}\n' "$SLURM_JOB_ID" "$1" "$(date '+%F %T')" "$NAME" "$S" "$2" >> "$STAGE/jobs/$NAME.jsonl"; }
submit_eval() {      # the setting is complete: its evaluation (CPU job) follows, unless EVAL=0 or one is already queued
    [ "${EVAL:-1}" = 0 ] && return 0
    local en="wb-eval-${SLURM_JOB_NAME#wb-}" id
    if [ -n "$(squeue -h -u "$USER" -n "$en" -o %i 2>/dev/null | head -1)" ]; then echo "evaluation job already in the queue ($en)"; return 0; fi
    id=$(env -u REDO -u FORCE -u TMPDIR sbatch --parsable --job-name="$en" ${EVAL_TIME:+--time=$EVAL_TIME} "$PROJ/vulcan/eval_setting.sbatch" "$@" 2>&1)         && echo "evaluation job submitted: $id ($en)" || echo "could not submit the evaluation ($id): bash vulcan/submit.sh eval $*"
}
read DONE0 TOTAL < <(count_done)
echo "setting: model $NAME, scenario $S, one-shot, samples: $MODELS; job $SLURM_JOB_ID ($SLURM_JOB_NAME)"
echo "progress at start: $DONE0 / $TOTAL replies"
[ "$TOTAL" -gt 0 ] || { echo "$STAGE/prompts: no prompts"; exit 1; }
if [ "$DONE0" -ge "$TOTAL" ] && [ -z "$REDO" ]; then echo "nothing left to do for this setting"; submit_eval "$NAME" "$S"; exit 0; fi
type module >/dev/null 2>&1 || { set +e; source /cvmfs/soft.computecanada.ca/config/profile/bash.sh; set -e; }   # sbatch from a shell that does not export the module function
module purge 2>/dev/null; module load StdEnv/2023 2>/dev/null || true
module load gcc opencv/4.11 python/3.12 2>/dev/null || module load gcc opencv python/3.12
module load cuda 2>/dev/null || module load cuda/12.6 || true
module load arrow 2>/dev/null || true      # the same modules the venv was built with
export HF_HOME=$HOME/scratch/hf HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 VLLM_LOGGING_LEVEL=${VLLM_LOGGING_LEVEL:-WARNING}
export TMPDIR=${SLURM_TMPDIR:-/tmp}
NGPU=$(nvidia-smi -L | wc -l); CPUS=${SLURM_CPUS_PER_TASK:-4}
echo "node $(hostname), $NGPU GPU(s), $CPUS CPUs, $WORKERS requests in parallel"
jobline start "\"node\": \"$(hostname)\", \"gpus\": $NGPU, \"cpus\": $CPUS, \"mem_mb\": ${SLURM_MEM_PER_NODE:-0}, \"samples\": \"$MODELS\", \"workers\": $WORKERS, \"done_at_start\": $DONE0, \"replies\": $TOTAL"
VLOG="vulcan/logs/vllm-$NAME-$SLURM_JOB_ID.log"
"$VENV/bin/vllm" serve "$MODEL_DIR" --served-model-name "$NAME" --port "$PORT" --tensor-parallel-size "$NGPU" \
    --dtype bfloat16 --max-model-len "${MAX_MODEL_LEN:-32768}" --gpu-memory-utilization 0.92 --trust-remote-code > "$VLOG" 2>&1 &
VPID=$!
trap 'set +e; kill $VPID 2>/dev/null; wait $VPID 2>/dev/null' EXIT
for i in $(seq 1 120); do
    curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && break
    kill -0 $VPID 2>/dev/null || { echo "vLLM died, see $VLOG"; tail -30 "$VLOG"; jobline end "\"result\": \"vLLM died\""; exit 1; }
    sleep 10
done
curl -sf "http://127.0.0.1:$PORT/health" >/dev/null || { echo "vLLM did not come up in 20 min"; jobline end "\"result\": \"vLLM did not start\""; exit 1; }
echo "model ready after $((SECONDS - T0)) s; sampling defaults (generation_config.json): $(tr -d '\n ' < "$MODEL_DIR/generation_config.json" 2>/dev/null || echo none)"
echo "===== scenario $S, one-shot, $MODELS ($(date '+%F %T'))"
RC=0
"$VENV/bin/python" scripts/run_llm.py --scenario "$S" --stage programmer --models "$MODELS" --workers "$WORKERS" $( [ "$N" -lt 100000 ] && echo "--limit $N" ) ${REDO:+--redo-bad} || { RC=$?; echo "run_llm.py stopped (status $RC)"; }
"$VENV/bin/python" scripts/summary_table.py | grep -E "^scenario |$NAME" || true
read DONE1 TOTAL < <(count_done)
echo "progress: $DONE0 -> $DONE1 / $TOTAL replies in $(( (SECONDS - T0) / 60 )) min ($(date '+%F %T'))"
[ "$DONE1" -ge "$TOTAL" ] && { echo "SETTING COMPLETE: $STAGE/responses/{${MODELS}}/"; submit_eval "$NAME" "$S"; } || echo "replies missing; submit the same setting again to continue"
jobline end "\"result\": \"ok\", \"runner_status\": $RC, \"done_at_end\": $DONE1, \"replies\": $TOTAL, \"minutes\": $(( (SECONDS - T0) / 60 ))"
