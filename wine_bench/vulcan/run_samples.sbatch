#!/bin/bash
#SBATCH --job-name=wb-samples
#SBATCH --account=aip-zhouyang
#SBATCH --gres=gpu:l40s:2
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=3:00:00
#SBATCH --output=vulcan/logs/%x-%j.out
# run_samples.sbatch (one-shot scenarios, pass@k) - ONE setting per job: one model, one scenario, NS replies per task.
#
#   cd .../WineBench/wine_bench && sbatch --job-name=wb-pk-1.3-qwen3.8-27b vulcan/run_samples.sbatch qwen3.8-27b 1.3
#   N=12 CHAIN=0 sbatch --time=0:40:00 --job-name=wb-pk-1.3-gpt-oss-20b vulcan/run_samples.sbatch gpt-oss-20b 1.3     # trial
#
# The replies are asked for with the API's "n": CHUNK replies per request, WORKERS tasks in flight, so WORKERS * CHUNK
# sequences are decoded at once (vLLM's --max-num-seqs is set to that).  Defaults per model below; NS=100.
# Results: runs/scenario<S>/programmer/samples/<model>-n<NS>/<id>.json (one file per task, all NS replies).
# Recovery: a task that has its file is skipped; the job stops STOP_MARGIN s before its limit and submits its successor
# (CHAIN=0: no).  When every task is there, EVAL_SHARDS (8) CPU jobs evaluate the setting (EVAL=0: no):
# ../vulcan/eval_samples.sbatch -> samples_eval/<model>-n<NS>/<id>.json, results/pass_at_k.txt.
set -e
NAME=${1:?model (folder under ~/scratch/models)}; S=${2:?scenario: 1.3 | 1.4}
WB=${SLURM_SUBMIT_DIR:-$PWD}
[ -f "$WB/scripts/run_samples.py" ] || { echo "$WB is not the wine_bench directory"; exit 1; }
WB=$(realpath "$WB"); PROJ=${PROJ:-$(dirname "$WB")}; VENV=${VENV:-$PROJ/venv-vllm}
[ -x "$VENV/bin/vllm" ] || { echo "$VENV: no vLLM venv"; exit 1; }
[ -f "$WB/scenarios/scenario$S/config.toml" ] || { echo "no scenario $S"; exit 1; }
cd "$WB"; STAGE="runs/scenario$S/programmer"; mkdir -p vulcan/logs "$STAGE/jobs"
NS=${NS:-100}; CHUNK=${CHUNK:-20}; N=${N:-100000}; STOP_MARGIN=${STOP_MARGIN:-600}; EVAL_SHARDS=${EVAL_SHARDS:-8}
case "$NAME" in gpt-oss*) W=16 ;; qwen*) W=9 ;; *) W=10 ;; esac       # sequences in flight = WORKERS * CHUNK.  gpt-oss: KV cache 2.6M tokens, 120 sequences used 0.8% of it (trial 2502511); qwen (hybrid, no prefix cache: every sequence holds its prompt) 392k tokens, ~1% per sequence; glm 225k tokens, ~0.3-1% per sequence (jobs 2504138, 2504139)
WORKERS=${WORKERS:-$W}; SEQS=$((WORKERS * CHUNK))
export NS CHUNK N WORKERS STOP_MARGIN EVAL EVAL_SHARDS EVAL_TIME EVAL_WORKERS CHAIN PROJ VENV
PORT=${PORT:-$((20000 + SLURM_JOB_ID % 20000))}; export WB_LOCAL_PORT=$PORT
MODEL_DIR=$HOME/scratch/models/$NAME; SAMPLE="$NAME-n$NS"; OUT="$STAGE/samples/$SAMPLE"
[ -f "$MODEL_DIR/config.json" ] || { echo "$MODEL_DIR: no weights"; exit 1; }
T0=$SECONDS
LIMIT=$(squeue -h -j "$SLURM_JOB_ID" -o %l 2>/dev/null | head -1); LIMIT=${LIMIT:-3:00:00}
limit_seconds() { echo "$1" | awk -F'[-:]' '{ if (NF == 4) print $1*86400 + $2*3600 + $3*60 + $4; else if (NF == 3) print $1*3600 + $2*60 + $3; else if (NF == 2) print $1*60 + $2; else print $1*60 }'; }
BUDGET=$(( $(limit_seconds "$LIMIT") - STOP_MARGIN ))
count_done() {                                                                       # -> "<tasks with all replies> <tasks wanted>"
    local c p
    p=$(ls "$STAGE/prompts" 2>/dev/null | grep -cE '^[0-9]{4}\.json$' || true); [ "$p" -gt "$N" ] && p=$N
    c=$(ls "$OUT" 2>/dev/null | grep -cE '^[0-9]{4}\.json$' || true); [ "$c" -gt "$p" ] && c=$p; echo "$c $p"
}
jobline() { printf '{"job": "%s", "event": "%s", "time": "%s", "model": "%s", "scenario": "%s", "harness": "samples", %s}\n' "$SLURM_JOB_ID" "$1" "$(date '+%F %T')" "$SAMPLE" "$S" "$2" >> "$STAGE/jobs/$SAMPLE.jsonl"; }
submit_eval() {      # the setting is complete: EVAL_SHARDS CPU jobs evaluate it, unless EVAL=0 or they are already queued
    [ "${EVAL:-1}" = 0 ] && return 0
    local en="wb-pkeval-$S-$NAME" id i
    if [ -n "$(squeue -h -u "$USER" -n "$en" -o %i 2>/dev/null | head -1)" ]; then echo "evaluation jobs already in the queue ($en)"; return 0; fi
    for i in $(seq 0 $((EVAL_SHARDS - 1))); do
        id=$(env -u REDO -u FORCE -u TMPDIR sbatch --parsable --job-name="$en" ${EVAL_TIME:+--time=$EVAL_TIME} "$PROJ/vulcan/eval_samples.sbatch" "$NAME" "$S" "$i" "$EVAL_SHARDS" 2>&1) \
            && echo "evaluation job submitted: $id ($en, shard $i/$EVAL_SHARDS)" || echo "could not submit the evaluation shard $i ($id)"
    done
}
read DONE0 TOTAL < <(count_done)
echo "setting: model $NAME, scenario $S, one-shot, $NS replies per task ($SAMPLE); job $SLURM_JOB_ID ($SLURM_JOB_NAME), time limit $LIMIT"
echo "progress at start: $DONE0 / $TOTAL tasks"
[ "$TOTAL" -gt 0 ] || { echo "$STAGE/prompts: no prompts"; exit 1; }
if [ "$DONE0" -ge "$TOTAL" ]; then echo "nothing left to do for this setting"; submit_eval; exit 0; fi
type module >/dev/null 2>&1 || { set +e; source /cvmfs/soft.computecanada.ca/config/profile/bash.sh; set -e; }
module purge 2>/dev/null; module load StdEnv/2023 2>/dev/null || true
module load gcc opencv/4.11 python/3.12 2>/dev/null || module load gcc opencv python/3.12
module load cuda 2>/dev/null || module load cuda/12.6 || true
module load arrow 2>/dev/null || true      # the same modules the venv was built with
export HF_HOME=$HOME/scratch/hf HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 VLLM_LOGGING_LEVEL=${VLLM_LOGGING_LEVEL:-INFO}
export TMPDIR=${SLURM_TMPDIR:-/tmp}
NGPU=$(nvidia-smi -L | wc -l); CPUS=${SLURM_CPUS_PER_TASK:-4}
echo "node $(hostname), $NGPU GPU(s), $CPUS CPUs; $WORKERS tasks x $CHUNK replies per request = $SEQS sequences in flight"
jobline start "\"node\": \"$(hostname)\", \"gpus\": $NGPU, \"cpus\": $CPUS, \"mem_mb\": ${SLURM_MEM_PER_NODE:-0}, \"time_limit\": \"$LIMIT\", \"n\": $NS, \"chunk\": $CHUNK, \"workers\": $WORKERS, \"done_at_start\": $DONE0, \"tasks\": $TOTAL"
VLOG="vulcan/logs/vllm-$SAMPLE-$SLURM_JOB_ID.log"
"$VENV/bin/vllm" serve "$MODEL_DIR" --served-model-name "$NAME" --port "$PORT" --tensor-parallel-size "$NGPU" \
    --dtype bfloat16 --max-model-len "${MAX_MODEL_LEN:-32768}" --gpu-memory-utilization 0.92 --max-num-seqs "$SEQS" \
    --trust-remote-code > "$VLOG" 2>&1 &
VPID=$!
trap 'set +e; kill $VPID 2>/dev/null; wait $VPID 2>/dev/null' EXIT
for i in $(seq 1 120); do
    curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && break
    kill -0 $VPID 2>/dev/null || { echo "vLLM died, see $VLOG"; tail -30 "$VLOG"; jobline end "\"result\": \"vLLM died\""; exit 1; }
    sleep 10
done
curl -sf "http://127.0.0.1:$PORT/health" >/dev/null || { echo "vLLM did not come up in 20 min"; jobline end "\"result\": \"vLLM did not start\""; exit 1; }
echo "model ready after $((SECONDS - T0)) s"
grep -iE "KV cache|Maximum concurrency|max_num_seqs" "$VLOG" | sed -E 's/^.*\] //' | tail -4 || true
LEFT=$((BUDGET - SECONDS)); RC=0
echo "===== scenario $S, one-shot, $SAMPLE ($(date '+%F %T'), $LEFT s of work in this job)"
if [ "$LEFT" -gt 120 ]; then
    "$VENV/bin/python" scripts/run_samples.py --scenario "$S" --model "$NAME" --n "$NS" --chunk "$CHUNK" --workers "$WORKERS" --seconds "$LEFT" \
        $( [ "$N" -lt 100000 ] && echo "--limit $N" ) || { RC=$?; echo "run_samples.py ended with status $RC"; }
fi
grep -E "Avg generation throughput" "$VLOG" | sed -E 's/^.*\] //' | tail -2 || true
read DONE1 TOTAL < <(count_done)
echo "progress: $DONE0 -> $DONE1 / $TOTAL tasks in $(( (SECONDS - T0) / 60 )) min ($(date '+%F %T'))"
NEXT=""; RESULT=ok
if [ "$DONE1" -ge "$TOTAL" ]; then echo "SETTING COMPLETE: $OUT/"; submit_eval
elif [ "${CHAIN:-1}" = 0 ]; then echo "tasks left; submit the same setting again to continue"; RESULT=incomplete
elif [ "$DONE1" -le "$DONE0" ]; then echo "NO PROGRESS in this job: not submitting a successor - check the log above"; RESULT=no-progress
else
    NEXT=$(sbatch --parsable --job-name="$SLURM_JOB_NAME" --time="$LIMIT" vulcan/run_samples.sbatch "$NAME" "$S" 2>&1) \
        && echo "successor job submitted: $NEXT" || { echo "could not submit the successor ($NEXT): submit the same setting again"; NEXT=""; }
fi
jobline end "\"result\": \"$RESULT\", \"runner_status\": $RC, \"done_at_end\": $DONE1, \"tasks\": $TOTAL, \"minutes\": $(( (SECONDS - T0) / 60 )), \"successor\": \"$NEXT\""
[ "$RESULT" = ok ] || exit 1
