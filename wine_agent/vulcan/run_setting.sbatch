#!/bin/bash
#SBATCH --job-name=wb-run
#SBATCH --account=aip-zhouyang
#SBATCH --gres=gpu:l40s:2
#SBATCH --cpus-per-task=12
#SBATCH --mem=64G
#SBATCH --time=3:00:00
#SBATCH --output=vulcan/logs/%x-%j.out
# run_setting.sbatch - ONE setting per job: one model, one scenario, one harness, over the whole benchmark.
#
# Submit it through the common entry point, which takes the resources from ../vulcan/experiments.tsv:
#
#   cd .../WineBench
#   bash vulcan/submit.sh qwen3.8-27b 2.1 openhands
#   bash vulcan/submit.sh glm-4.7-flash 2.1 mini_swe --time=12:00:00   # extra sbatch options after the three names
#   N=20 CHAIN=0 bash vulcan/submit.sh gpt-oss-20b 2.2 mini_swe --time=1:00:00      # a short trial: first 20 tasks, no follow-up job
#
# A setting = model + scenario + harness (mini_swe | openhands), plus what the scenario's config.toml fixes (step, time
# and compile limits) and the dataset.  Its results are runs/scenario<S>/<harness>/responses/<model>/, nothing else.
#
# Fresh trees: the job unpacks the packed tree pair (vulcan/pack_trees.sbatch -> ~/scratch/winebench-w/swe-pair.tar) onto
# the node's local disk, one pair per worker, and throws them away at the end.  No job inherits a tree from another one,
# and compiling / searching does not touch the shared filesystem.
#
# Recovery: a task's result is written only when the task has ended, so a job that stops for any reason (time limit,
# crash, scancel, node failure) loses only the tasks that were running.  Submitting the same setting again continues with
# the tasks that have no result; nothing is done twice.  This job does that itself: it stops 10 minutes before its time
# limit and, if tasks are left and it finished at least one, submits its successor (CHAIN=0 switches that off).  A job that
# finds nothing left exits before it loads the model.  REDO=1 also re-runs tasks that errored or submitted nothing.
# Every job appends a line to runs/scenario<S>/<harness>/jobs/<model>.jsonl when it starts and when it ends; every task
# result carries the id of the job that produced it ("job").
#
# Tunable (environment): N (first N tasks; default all), AGENT_WORKERS=6 (tasks in parallel = tree pairs), MAX_MODEL_LEN,
# CHAIN, REDO, SWE_LOCAL_TOOL_MODE / TOOL_PARSER (see scripts/bench/swe.py: tool_mode).
set -e
NAME=${1:?model (folder under ~/scratch/models, entry in scenarios/models.toml)}; S=${2:?scenario, e.g. 2.1}; A=${3:?harness: mini_swe | openhands}
WA=${SLURM_SUBMIT_DIR:-$PWD}
[ -f "$WA/scripts/run_$A.py" ] || { echo "$WA is not the wine_agent directory, or '$A' is not a harness (mini_swe | openhands)"; exit 1; }
WA=$(realpath "$WA"); PROJ=${PROJ:-$(dirname "$WA")}; VENV=${VENV:-$PROJ/venv-vllm}; SIF=${SIF:-$PROJ/container/wine-agent.sif}
N=${N:-100000}; AGENT_WORKERS=${AGENT_WORKERS:-6}; MAX_MODEL_LEN=${MAX_MODEL_LEN:-65536}
PORT=${PORT:-$((20000 + SLURM_JOB_ID % 20000))}
MODEL_DIR=$HOME/scratch/models/$NAME; PACK=${PACK:-$(realpath -m ~/scratch/winebench-w/swe-pair.tar)}
[ -f "$MODEL_DIR/config.json" ] || { echo "$MODEL_DIR: no weights"; exit 1; }
[ -x "$VENV/bin/vllm" ] || { echo "$VENV: no vLLM venv"; exit 1; }
[ -f "$SIF" ] || { echo "$SIF: no container image"; exit 1; }
[ -f "$PACK" ] || { echo "$PACK: no packed trees (sbatch vulcan/pack_trees.sbatch)"; exit 1; }
[ -f "scenarios/scenario$S/config.toml" ] || [ -f "$WA/scenarios/scenario$S/config.toml" ] || { echo "no scenario $S"; exit 1; }
cd "$WA"; STAGE="runs/scenario$S/$A"; OUT="$STAGE/responses/$NAME"; mkdir -p vulcan/logs "$STAGE/jobs"
case "$NAME" in gpt-oss*) SWE_LOCAL_TOOL_MODE=${SWE_LOCAL_TOOL_MODE:-native}; TOOL_PARSER=${TOOL_PARSER:-openai} ;; esac     # see agents.sbatch
MODE=${SWE_LOCAL_TOOL_MODE:-text}
export N AGENT_WORKERS MAX_MODEL_LEN PROJ VENV SIF PACK SWE_LOCAL_TOOL_MODE TOOL_PARSER CHAIN STOP_MARGIN EVAL EVAL_TIME EVAL_WORKERS                        # the successor job inherits them
T0=$SECONDS
LIMIT=$(squeue -h -j "$SLURM_JOB_ID" -o %l 2>/dev/null | head -1); LIMIT=${LIMIT:-3:00:00}       # [D-]HH:MM:SS
limit_seconds() { echo "$1" | awk -F'[-:]' '{ if (NF == 4) print $1*86400 + $2*3600 + $3*60 + $4; else if (NF == 3) print $1*3600 + $2*60 + $3; else if (NF == 2) print $1*60 + $2; else print $1*60 }'; }
STOP_MARGIN=${STOP_MARGIN:-600}; BUDGET=$(( $(limit_seconds "$LIMIT") - STOP_MARGIN ))            # stop this long before the limit (default 10 minutes)
count_done() {                                                                       # -> "<tasks with a result> <tasks wanted>"
    local c p want
    c=$(grep -lsE "\"tool_mode\": \"$MODE\"|\"exit_status\": \"DatasetMismatch\"" "$OUT"/[0-9][0-9][0-9][0-9].json 2>/dev/null | wc -l)
    p=$(ls "$STAGE/prompts" 2>/dev/null | grep -cE '^[0-9]{4}\.json$' || true)
    [ "$p" -eq 0 ] && p=$N; want=$(( p < N ? p : N )); [ "$c" -gt "$want" ] && c=$want
    echo "$c $want"
}
jobline() { printf '{"job": "%s", "event": "%s", "time": "%s", "model": "%s", "scenario": "%s", "harness": "%s", %s}\n' "$SLURM_JOB_ID" "$1" "$(date '+%F %T')" "$NAME" "$S" "$A" "$2" >> "$STAGE/jobs/$NAME.jsonl"; }
submit_eval() {      # the setting is complete: its evaluation (CPU job) follows, unless EVAL=0 or one is already queued
    [ "${EVAL:-1}" = 0 ] && return 0
    local en="wb-eval-${SLURM_JOB_NAME#wb-}" id
    if [ -n "$(squeue -h -u "$USER" -n "$en" -o %i 2>/dev/null | head -1)" ]; then echo "evaluation job already in the queue ($en)"; return 0; fi
    id=$(env -u REDO -u FORCE -u TMPDIR sbatch --parsable --job-name="$en" ${EVAL_TIME:+--time=$EVAL_TIME} "$PROJ/vulcan/eval_setting.sbatch" "$@" 2>&1)         && echo "evaluation job submitted: $id ($en)" || echo "could not submit the evaluation ($id): bash vulcan/submit.sh eval $*"
}
read DONE0 TOTAL < <(count_done)
echo "setting: model $NAME, scenario $S, harness $A, tool mode $MODE; job $SLURM_JOB_ID ($SLURM_JOB_NAME), time limit $LIMIT"
echo "progress at start: $DONE0 / $TOTAL tasks"
if [ "$DONE0" -ge "$TOTAL" ] && [ -z "$REDO" ]; then echo "nothing left to do for this setting"; submit_eval "$NAME" "$S" "$A"; exit 0; fi
type module >/dev/null 2>&1 || { set +e; source /cvmfs/soft.computecanada.ca/config/profile/bash.sh; set -e; }   # sbatch from a shell that does not export the module function
module purge 2>/dev/null; module load StdEnv/2023 2>/dev/null || true
module load gcc opencv/4.11 python/3.12 2>/dev/null || module load gcc opencv python/3.12
module load cuda 2>/dev/null || module load cuda/12.6 || true
module load arrow 2>/dev/null || true
module load apptainer
export HF_HOME=$HOME/scratch/hf HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 VLLM_LOGGING_LEVEL=${VLLM_LOGGING_LEVEL:-WARNING}
NGPU=$(nvidia-smi -L | wc -l); CPUS=${SLURM_CPUS_PER_TASK:-12}; JOBS=$(( CPUS / AGENT_WORKERS )); [ "$JOBS" -lt 2 ] && JOBS=2
LOCAL=${SLURM_TMPDIR:-/tmp}/wb-$SLURM_JOB_ID; mkdir -p "$LOCAL/tmp"
VPID=""; trap 'set +e; [ -n "$VPID" ] && { kill $VPID; wait $VPID; } 2>/dev/null; rm -rf "$LOCAL"' EXIT        # set +e: a failing clean-up step must not become the job's exit status
echo "node $(hostname), $NGPU GPU(s), $CPUS CPUs, workers $AGENT_WORKERS (make -j$JOBS each); local disk $LOCAL: $(df -h --output=avail "$LOCAL" | tail -1 | tr -d ' ') free"
IMG=$(sha256sum "$SIF" | cut -c1-16)
jobline start "\"node\": \"$(hostname)\", \"gpus\": $NGPU, \"cpus\": $CPUS, \"mem_mb\": ${SLURM_MEM_PER_NODE:-0}, \"time_limit\": \"$LIMIT\", \"workers\": $AGENT_WORKERS, \"tool_mode\": \"$MODE\", \"max_model_len\": $MAX_MODEL_LEN, \"image\": \"$IMG\", \"pack\": \"$(head -1 "${PACK%.tar}.info" 2>/dev/null)\", \"done_at_start\": $DONE0, \"tasks\": $TOTAL"
CENV="LITELLM_LOCAL_MODEL_COST_MAP=True,MSWEA_SILENT_STARTUP=1,MSWEA_COST_TRACKING=ignore_errors,OPENHANDS_SUPPRESS_BANNER=1,TMPDIR=/t/tmp,PYTHONUNBUFFERED=1,WB_JOB_ID=$SLURM_JOB_ID"
run() { apptainer exec --containall --pwd "$WA" --bind "$WA" --bind "$LOCAL":/t --env "$CENV,WB_LOCAL_PORT=$PORT,SWE_LOCAL_TOOL_MODE=$MODE" "$SIF" "$@"; }

# ---- the model first (it takes minutes to load); the trees are unpacked meanwhile
TOOLFLAGS=""; [ -n "$TOOL_PARSER" ] && TOOLFLAGS="--enable-auto-tool-choice --tool-call-parser $TOOL_PARSER"
VLOG="vulcan/logs/vllm-$NAME-$SLURM_JOB_ID.log"
"$VENV/bin/vllm" serve "$MODEL_DIR" --served-model-name "$NAME" --port "$PORT" --tensor-parallel-size "$NGPU" \
    --dtype bfloat16 --max-model-len "$MAX_MODEL_LEN" --gpu-memory-utilization 0.92 --trust-remote-code $TOOLFLAGS > "$VLOG" 2>&1 &
VPID=$!
T_LOAD=$SECONDS
echo "== unpacking $AGENT_WORKERS fresh tree pairs ($(date '+%T'))"
apptainer exec --containall --pwd "$WA" --bind "$WA" --bind "$PACK":/pack/swe-pair.tar:ro --bind "$LOCAL":/t --env "TMPDIR=/t/tmp" \
    "$SIF" bash scripts/unpack_swe_trees.sh /pack/swe-pair.tar "$AGENT_WORKERS" || { jobline end "\"result\": \"trees could not be unpacked\""; exit 1; }
echo "   trees ready after $((SECONDS - T_LOAD)) s"
for i in $(seq 1 120); do
    curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && break
    kill -0 $VPID 2>/dev/null || { echo "vLLM died, see $VLOG"; grep -v "APIServer pid" "$VLOG" | grep -E "Error|error" | tail -8; tail -5 "$VLOG"; jobline end "\"result\": \"vLLM died\""; exit 1; }
    sleep 10
done
curl -sf "http://127.0.0.1:$PORT/health" >/dev/null || { echo "vLLM did not come up in 20 min"; jobline end "\"result\": \"vLLM did not start\""; exit 1; }
[ -d "$STAGE/prompts" ] || run python scripts/build_prompts.py --scenario "$S" --stage "$A"
LEFT=$((BUDGET - SECONDS)); echo "model ready after $((SECONDS - T_LOAD)) s; $LEFT s of work left in this job"
RC=0
if [ "$LEFT" -gt 120 ]; then
    echo "===== $A, scenario $S, model $NAME ($(date '+%F %T'))"
    timeout "${LEFT}s" apptainer exec --containall --pwd "$WA" --bind "$WA" --bind "$LOCAL":/t --env "$CENV,WB_LOCAL_PORT=$PORT,SWE_LOCAL_TOOL_MODE=$MODE" "$SIF" \
        python "scripts/run_$A.py" --scenario "$S" --limit "$N" --models "$NAME" --workers "$AGENT_WORKERS" --jobs "$JOBS" \
        --src /t/wine-swe --build /t/wine-build-swe ${REDO:+--redo-bad} || { RC=$?; echo "run_$A.py stopped (status $RC: 124 = this job's time budget is used up)"; }
fi
run python scripts/summary_table.py | grep -E "^scenario |$NAME" | grep -E "^scenario |$A" || true
read DONE1 TOTAL < <(count_done)
echo "progress: $DONE0 -> $DONE1 / $TOTAL tasks in $(( (SECONDS - T0) / 60 )) min ($(date '+%F %T'))"
kill $VPID 2>/dev/null || true
NEXT=""
if [ "$DONE1" -ge "$TOTAL" ]; then echo "SETTING COMPLETE: $OUT/"; submit_eval "$NAME" "$S" "$A"
elif [ "${CHAIN:-1}" = 0 ] || [ -n "$REDO" ]; then echo "tasks left; submit the same setting again to continue"
elif [ "$DONE1" -le "$DONE0" ]; then echo "NO PROGRESS in this job: not submitting a successor - check the log above"
else
    NEXT=$(sbatch --parsable --job-name="$SLURM_JOB_NAME" --gres=gpu:l40s:$NGPU --time="$LIMIT" --cpus-per-task="$CPUS" ${SLURM_MEM_PER_NODE:+--mem=${SLURM_MEM_PER_NODE}M} vulcan/run_setting.sbatch "$NAME" "$S" "$A" 2>&1) \
        && echo "successor job submitted: $NEXT" || { echo "could not submit the successor ($NEXT): submit the same setting again"; NEXT=""; }
fi
jobline end "\"result\": \"ok\", \"runner_status\": $RC, \"done_at_end\": $DONE1, \"tasks\": $TOTAL, \"minutes\": $(( (SECONDS - T0) / 60 )), \"successor\": \"$NEXT\""
