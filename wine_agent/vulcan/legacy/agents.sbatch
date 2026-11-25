#!/usr/bin/env bash
#SBATCH --job-name=winebench-agents
#SBATCH --gres=gpu:l40s:2
#SBATCH --cpus-per-task=12
#SBATCH --mem=64G
#SBATCH --time=3:00:00
#SBATCH --output=vulcan/logs/%x-%j.out
# agents.sbatch - scenarios 3.1 / 3.2 with mini-swe-agent and OpenHands driven by a LOCAL model on Vulcan.
#
#   cd .../WineBench/wine_agent            (sbatch must be run from the wine_agent directory)
#   N=500 sbatch vulcan/agents.sbatch qwen3.8-27b                    # submit ONCE per model: see "Short jobs" below
#   N=5 CHAIN=0 sbatch vulcan/agents.sbatch gpt-oss-20b              # a single short job, no follow-up
#   N=500 AGENTS=mini_swe SCENARIOS=3.1 sbatch vulcan/agents.sbatch glm-4.7-flash
#
# Short jobs: the time limit is 3 hours (short jobs start much sooner than day-long ones).  The job stops working
# 10 minutes before its limit and, if records are left and it made progress, submits its own successor with the same
# settings - so one sbatch per model is enough.  CHAIN=0 switches that off; `scancel` on the last job ends the chain.
# A job that finds nothing left to do exits at once, before loading the model.
#
# What runs where:
#   host (modules + ../venv-vllm)        vLLM serving ~/scratch/models/<name> on 2 L40S, with tool calling
#   container (../container/wine-agent.sif: Ubuntu 22.04, mingw, agents)   the agent loop and every command it issues,
#       working in restricted Wine trees under /t (= ~/scratch/winebench-trees/<name>): no tests, no git history, the
#       target function stubbed, ./compile.  The clean Wine tree (/w) is NOT mounted while agents run.
# The trees are created on first use from ~/scratch/winebench-w/{wine,wine-build} (container/build_wine.sbatch).
# Results: runs/scenario3.x/<agent>/responses/<name>/<id>.{json,patch,traj.json}; evaluate them on the Ubuntu box.
# Re-submitting continues where the last job stopped; REDO=1 re-runs records that errored or produced nothing.
set -e
NAME=${1:?model name (folder under ~/scratch/models, entry in scenarios/models.toml)}
WA=${SLURM_SUBMIT_DIR:-$PWD}
[ -f "$WA/scripts/run_mini_swe.py" ] || { echo "$WA is not the wine_agent directory: cd into it and sbatch again"; exit 1; }
WA=$(realpath "$WA"); PROJ=${PROJ:-$(dirname "$WA")}; VENV=${VENV:-$PROJ/venv-vllm}; SIF=${SIF:-$PROJ/container/wine-agent.sif}
N=${N:-5}; AGENTS=${AGENTS:-"mini_swe openhands"}; SCENARIOS=${SCENARIOS:-"3.1 3.2"}; AGENT_WORKERS=${AGENT_WORKERS:-4}
PORT=${PORT:-$((20000 + SLURM_JOB_ID % 20000))}; MAX_MODEL_LEN=${MAX_MODEL_LEN:-65536}
MODEL_DIR=$HOME/scratch/models/$NAME
W=$(realpath -m ~/scratch/winebench-w); TREES=$(realpath -m ~/scratch/winebench-trees/$NAME)
[ -f "$MODEL_DIR/config.json" ] || { echo "$MODEL_DIR: no weights"; exit 1; }
[ -x "$VENV/bin/vllm" ] || { echo "$VENV: no vLLM venv"; exit 1; }
[ -f "$SIF" ] || { echo "$SIF: no container image"; exit 1; }
[ -e "$W/wine-build/wine" ] || { echo "$W/wine-build: Wine is not built (container/build_wine.sbatch)"; exit 1; }
cd "$WA"; mkdir -p vulcan/logs "$TREES/tmp"
# gpt-oss answers with harmony tool calls whatever the prompt asks for; without declared tools the server rejects them
# (HarmonyError "unexpected tokens remaining in message header", or an empty reply), so text mode cannot work for it.
# It runs with native tool calls and vLLM's "openai" parser; the runners repair the tool names this vLLM returns with
# "json" glued to them (bench/swe.py: install_tool_name_fix).  Every other local model stays in text mode.
case "$NAME" in gpt-oss*) SWE_LOCAL_TOOL_MODE=${SWE_LOCAL_TOOL_MODE:-native}; TOOL_PARSER=${TOOL_PARSER:-openai} ;; esac
export N AGENTS SCENARIOS AGENT_WORKERS MAX_MODEL_LEN PROJ VENV SIF SWE_LOCAL_TOOL_MODE TOOL_PARSER                 # the successor job inherits them
T0=$SECONDS
LIMIT=$(squeue -h -j "$SLURM_JOB_ID" -o %l 2>/dev/null | head -1); LIMIT=${LIMIT:-3:00:00}       # [D-]HH:MM:SS
limit_seconds() { echo "$1" | awk -F'[-:]' '{ if (NF == 4) print $1*86400 + $2*3600 + $3*60 + $4; else if (NF == 3) print $1*3600 + $2*60 + $3; else if (NF == 2) print $1*60 + $2; else print $1*60 }'; }
BUDGET=$(( $(limit_seconds "$LIMIT") - 600 ))                                       # stop 10 minutes before the limit
count_done() {                                                                       # -> "<records done> <records wanted>"
    local n=0 t=0 S A c p want
    for S in $SCENARIOS; do for A in $AGENTS; do
        c=$(grep -lsE "\"tool_mode\": \"${SWE_LOCAL_TOOL_MODE:-text}\"|\"exit_status\": \"DatasetMismatch\"" "runs/scenario$S/$A/responses/$NAME"/[0-9][0-9][0-9][0-9].json 2>/dev/null | wc -l)
        p=$(ls "runs/scenario$S/$A/prompts" 2>/dev/null | grep -cE '^[0-9]{4}\.json$' || true)
        [ "$p" -eq 0 ] && p=$N; want=$(( p < N ? p : N )); [ "$c" -gt "$want" ] && c=$want
        n=$((n + c)); t=$((t + want))
    done; done
    echo "$n $t"
}
read DONE0 TOTAL < <(count_done)
echo "progress at start: $DONE0 / $TOTAL records; time limit $LIMIT"
if [ "$DONE0" -ge "$TOTAL" ] && [ -z "$REDO" ]; then echo "nothing left to do for $NAME"; exit 0; fi
type module >/dev/null 2>&1 || { set +e; source /cvmfs/soft.computecanada.ca/config/profile/bash.sh; set -e; }   # sbatch from a shell that does not export the module function
module purge 2>/dev/null; module load StdEnv/2023 2>/dev/null || true
module load gcc opencv/4.11 python/3.12 2>/dev/null || module load gcc opencv python/3.12
module load cuda 2>/dev/null || module load cuda/12.6 || true
module load arrow 2>/dev/null || true
module load apptainer
export HF_HOME=$HOME/scratch/hf HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 VLLM_LOGGING_LEVEL=WARNING
NGPU=$(nvidia-smi -L | wc -l); echo "node $(hostname), $NGPU GPU(s), model $NAME, N=$N, agents: $AGENTS, scenarios: $SCENARIOS, workers $AGENT_WORKERS"
CENV="LITELLM_LOCAL_MODEL_COST_MAP=True,MSWEA_SILENT_STARTUP=1,MSWEA_COST_TRACKING=ignore_errors,OPENHANDS_SUPPRESS_BANNER=1,TMPDIR=/t/tmp,PYTHONUNBUFFERED=1"

# ---- restricted trees for this model (once): the clean tree is mounted only for this step
ntrees() { ls -d "$TREES"/wine-build-swe* 2>/dev/null | wc -l; }
if { [ ! -d "$TREES/wine-swe.gitdir" ] && [ ! -d "$TREES/wine-swe/.git" ]; } || [ "$(ntrees)" -lt "$AGENT_WORKERS" ]; then
    echo "== creating $AGENT_WORKERS restricted tree pairs in $TREES (a few minutes each)"
    apptainer exec --containall --pwd "$WA" --bind "$WA" --bind "$W":/w --bind "$TREES":/t \
        --env "WINE_SRC=/w/wine,WINE_BUILD=/w/wine-build,SWE_SRC=/t/wine-swe,SWE_BUILD=/t/wine-build-swe" \
        "$SIF" bash scripts/make_swe_trees.sh "$AGENT_WORKERS" 2>&1 | grep -v "^done\." || true
    [ "$(ntrees)" -ge "$AGENT_WORKERS" ] || { echo "the restricted trees could not be created"; exit 1; }
fi

# ---- the model.  The agents drive local models in TEXT mode (the action is parsed from the reply text: mini-swe-agent's
# text-based model class, OpenHands' prompt-based function calling), so vLLM needs no tool-call parser - except gpt-oss
# (see above).  To force a mode for any model: SWE_LOCAL_TOOL_MODE=native TOOL_PARSER=<name>, or SWE_LOCAL_TOOL_MODE=text.
TOOLFLAGS=""; [ -n "$TOOL_PARSER" ] && TOOLFLAGS="--enable-auto-tool-choice --tool-call-parser $TOOL_PARSER"
MODE=${SWE_LOCAL_TOOL_MODE:-text}; echo "tool mode for both agents: $MODE${TOOL_PARSER:+ (vLLM tool-call parser: $TOOL_PARSER)}"
echo "sampling defaults of the model (generation_config.json): $(tr -d '\n ' < "$MODEL_DIR/generation_config.json" 2>/dev/null || echo none)"
VLOG="vulcan/logs/vllm-$NAME-$SLURM_JOB_ID.log"
"$VENV/bin/vllm" serve "$MODEL_DIR" --served-model-name "$NAME" --port "$PORT" --tensor-parallel-size "$NGPU" \
    --dtype bfloat16 --max-model-len "$MAX_MODEL_LEN" --gpu-memory-utilization 0.92 --trust-remote-code $TOOLFLAGS > "$VLOG" 2>&1 &
VPID=$!
trap 'kill $VPID 2>/dev/null; wait $VPID 2>/dev/null' EXIT
T_LOAD=$SECONDS
for i in $(seq 1 120); do
    curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && break
    kill -0 $VPID 2>/dev/null || { echo "vLLM died, see $VLOG"; grep -v "APIServer pid" "$VLOG" | grep -E "Error|error" | tail -8; tail -5 "$VLOG"; exit 1; }
    sleep 10
done
curl -sf "http://127.0.0.1:$PORT/health" >/dev/null || { echo "vLLM did not come up in 20 min"; exit 1; }

# ---- prompts (once) and the agent runs, inside the container; only the restricted trees are mounted
run() { apptainer exec --containall --pwd "$WA" --bind "$WA" --bind "$TREES":/t --env "$CENV,WB_LOCAL_PORT=$PORT,SWE_LOCAL_TOOL_MODE=$MODE" "$SIF" "$@"; }
for S in $SCENARIOS; do for A in $AGENTS; do
    [ -d "runs/scenario$S/$A/prompts" ] || run python scripts/build_prompts.py --scenario "$S" --stage "$A"
done; done
echo "model ready after $((SECONDS - T_LOAD)) s; $((BUDGET - SECONDS)) s of work left in this job"
for S in $SCENARIOS; do for A in $AGENTS; do
    LEFT=$((BUDGET - SECONDS)); [ "$LEFT" -gt 120 ] || break 2
    echo "===== $A, scenario $S, first $N records, model $NAME ($(date '+%F %T'), $LEFT s left)"
    timeout "${LEFT}s" apptainer exec --containall --pwd "$WA" --bind "$WA" --bind "$TREES":/t --env "$CENV,WB_LOCAL_PORT=$PORT,SWE_LOCAL_TOOL_MODE=$MODE" "$SIF" \
        python "scripts/run_$A.py" --scenario "$S" --limit "$N" --models "$NAME" --workers "$AGENT_WORKERS" \
        --src /t/wine-swe --build /t/wine-build-swe ${REDO:+--redo-bad} \
        || echo "run_$A.py stopped (status $?: 124 = this job's time budget is used up) for scenario $S"
done; done
run python scripts/summary_table.py | grep -E "^scenario |$NAME" || true
read DONE1 TOTAL < <(count_done)
echo "progress: $DONE0 -> $DONE1 / $TOTAL records in $(( (SECONDS - T0) / 60 )) min ($(date '+%F %T'))"
kill $VPID 2>/dev/null || true
if [ "$DONE1" -ge "$TOTAL" ]; then echo "ALL DONE: runs/scenario3.*/{mini_swe,openhands}/responses/$NAME/"
elif [ "${CHAIN:-1}" = 0 ] || [ -n "$REDO" ]; then echo "records left; submit again to continue"
elif [ "$DONE1" -le "$DONE0" ]; then echo "NO PROGRESS in this job: not submitting a successor - check the log above"
else
    NEXT=$(sbatch --parsable --gres=gpu:l40s:$NGPU --time="$LIMIT" --cpus-per-task="${SLURM_CPUS_PER_TASK:-12}" ${SLURM_MEM_PER_NODE:+--mem=${SLURM_MEM_PER_NODE}M} vulcan/agents.sbatch "$NAME" 2>&1) \
        && echo "successor job submitted: $NEXT" || echo "could not submit the successor ($NEXT): run  sbatch vulcan/agents.sbatch $NAME  again"
fi
