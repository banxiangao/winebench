#!/bin/bash
#SBATCH --job-name=wb-api
#SBATCH --account=aip-zhouyang
#SBATCH --cpus-per-task=12
#SBATCH --mem=32G
#SBATCH --time=3:00:00
#SBATCH --output=vulcan/logs/%x-%j.out
# run_api.sbatch - ONE setting of a COMMERCIAL model (queried over its vendor's API) per job.  CPU only: no GPU, no vLLM.
# Submit it through vulcan/submit_api.sh, which sets the resources and the job name:
#
#   cd .../WineBench
#   bash vulcan/submit_api.sh claude-haiku-5-5 1.2                 # one-shot: one reply per task (scenario 1.1 | 1.2)
#   bash vulcan/submit_api.sh openai-gpt-6-luna 2.2 mini_swe       # agent in the source tree (mini_swe | openhands)
#   N=5 CHAIN=0 EVAL=0 bash vulcan/submit_api.sh claude-haiku-5-5 2.2 openhands --time=0:40:00     # a trial: first 5 tasks
#   bash vulcan/submit_api.sh probe                                # one tiny request per model: is the key valid, which model id is served
#
# The model names are the entries of scenarios/models.toml (claude-haiku-5-5, openai-gpt-6-luna, deepseek-v4-flash).
#
# Keys: ~/.config/winebench/secrets.toml (mode 600, outside the project tree, which the whole group can read), in the
# form of wine_bench/secrets.toml.example.  The job hands the file to the container read-only; nothing prints a key.
#
# Network: compute nodes reach the outside only through the cluster's proxy (https_proxy, set by the job prolog), and
# the proxy has an allow-list: api.openai.com and api.anthropic.com pass, api.deepseek.com is refused (403, checked
# 2026-11-25).  The proxy is given to the Python process that calls the model; the agent's own shell commands get it
# blanked (bench/swe.py: offline_env), so the agent is as offline as in the local-model runs.
#
# One generation per task, at most GEN_ATTEMPTS=2: a second one only if the first got no reply because of an API /
# network / runner error (one-shot: request failed or empty reply; agent: the run was cut short by such an error).  If
# the second fails too the task is stored with generation_failed = true and is not tried again.  A reply without usable
# code, a truncated reply, an agent that hits one of the bench's limits: those are results, not failures.
#
# Recovery and chaining as in run_setting.sbatch: tasks with a result are skipped; the job stops 10 minutes before its
# limit and submits its successor if tasks are left and it finished at least one (CHAIN=0: no).  When the setting is
# complete its evaluation is submitted (vulcan/eval_setting.sbatch; EVAL=0: no).
# Tunable: N (first N tasks), GEN_ATTEMPTS, WORKERS=4 (one-shot: requests in parallel), AGENT_WORKERS=6 (agent: tasks in
# parallel = tree pairs).
set -e
NAME=${1:?model (entry of scenarios/models.toml), or: probe}; S=${2:-}; H=${3:-oneshot}
PKG=$(realpath "${SLURM_SUBMIT_DIR:-$PWD}"); ROOT=${PROJ:-$(dirname "$PKG")}; SIF=${SIF:-$ROOT/container/wine-agent.sif}
SECRETS=${WB_SECRETS_FILE:-$HOME/.config/winebench/secrets.toml}
[ -f "$SIF" ] || { echo "$SIF: no container image"; exit 1; }
[ -f "$SECRETS" ] || { echo "$SECRETS: no key file (copy wine_bench/secrets.toml.example there, fill in the keys, chmod 600)"; exit 1; }
[ "$(stat -c %a "$SECRETS")" = 600 ] || { echo "$SECRETS must be readable by you only: chmod 600 $SECRETS"; exit 1; }
[ -n "$https_proxy" ] || echo "WARNING: https_proxy is not set in this job: the vendor APIs are not reachable from a compute node without it"
type module >/dev/null 2>&1 || { set +e; source /cvmfs/soft.computecanada.ca/config/profile/bash.sh; set -e; }
module load apptainer
LOCAL=${SLURM_TMPDIR:-/tmp}/wb-$SLURM_JOB_ID; mkdir -p "$LOCAL/tmp"; trap 'set +e; rm -rf "$LOCAL"' EXIT
echo 'unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY' > "$LOCAL/noproxy.sh"      # BASH_ENV: every `bash -c` of the agent
export APPTAINERENV_no_proxy=localhost,127.0.0.1 APPTAINERENV_NO_PROXY=localhost,127.0.0.1                 # (a value with a comma cannot go through --env)
PROXY=(--env "https_proxy=$https_proxy" --env "http_proxy=$http_proxy" --env "HTTPS_PROXY=$https_proxy" --env "HTTP_PROXY=$http_proxy")
CENV="LITELLM_LOCAL_MODEL_COST_MAP=True,MSWEA_SILENT_STARTUP=1,MSWEA_COST_TRACKING=ignore_errors,OPENHANDS_SUPPRESS_BANNER=1,TMPDIR=/t/tmp,PYTHONUNBUFFERED=1,PYTHONDONTWRITEBYTECODE=1,WB_JOB_ID=$SLURM_JOB_ID,WB_SECRETS=/secrets.toml,BASH_ENV=/t/noproxy.sh"
run() { apptainer exec --containall --pwd "$PKG" --bind "$PKG" --bind "$LOCAL":/t --bind "$SECRETS":/secrets.toml:ro --env "$CENV" "${PROXY[@]}" "$SIF" "$@"; }

if [ "$NAME" = probe ]; then                                         # which keys work, which model ids are served
    cd "$ROOT/wine_bench"; PKG=$PWD
    run python scripts/run_llm.py --scenario 1.1 --stage programmer --probe --models "${S:-claude-haiku-5-5,openai-gpt-6-luna,deepseek-v4-flash}"
    exit 0
fi
[ -n "$S" ] || { echo "usage: run_api.sbatch <model> <scenario> [mini_swe | openhands]"; exit 1; }
if [ "$H" = oneshot ]; then STAGE=programmer; SCRIPT=scripts/run_llm.py
else STAGE=$H; SCRIPT=scripts/run_$H.py; PACK=${PACK:-$(realpath -m ~/scratch/winebench-w/swe-pair.tar)}
     [ -f "$PACK" ] || { echo "$PACK: no packed trees (cd wine_agent && sbatch vulcan/pack_trees.sbatch)"; exit 1; }; fi
[ -f "$PKG/$SCRIPT" ] || { echo "$PKG has no $SCRIPT: submit from wine_bench (one-shot) or wine_agent (agent) - bash vulcan/submit_api.sh does"; exit 1; }
[ -f "$PKG/scenarios/scenario$S/config.toml" ] || { echo "$PKG: no scenario $S"; exit 1; }
grep -qE "^name *= *\"$NAME\"" "$PKG/scenarios/models.toml" || { echo "$NAME: not in $PKG/scenarios/models.toml"; exit 1; }
cd "$PKG"; SD="runs/scenario$S/$STAGE"; OUT="$SD/responses/$NAME"; mkdir -p vulcan/logs "$SD/jobs"
N=${N:-100000}; GEN_ATTEMPTS=${GEN_ATTEMPTS:-2}; WORKERS=${WORKERS:-4}; AGENT_WORKERS=${AGENT_WORKERS:-6}; STOP_MARGIN=${STOP_MARGIN:-600}
export N GEN_ATTEMPTS WORKERS AGENT_WORKERS STOP_MARGIN CHAIN EVAL EVAL_TIME EVAL_WORKERS SIF PACK PROJ WB_SECRETS_FILE
T0=$SECONDS
LIMIT=$(squeue -h -j "$SLURM_JOB_ID" -o %l 2>/dev/null | head -1); LIMIT=${LIMIT:-3:00:00}
limit_seconds() { echo "$1" | awk -F'[-:]' '{ if (NF == 4) print $1*86400 + $2*3600 + $3*60 + $4; else if (NF == 3) print $1*3600 + $2*60 + $3; else if (NF == 2) print $1*60 + $2; else print $1*60 }'; }
BUDGET=$(( $(limit_seconds "$LIMIT") - STOP_MARGIN ))
count_done() {                                                                       # -> "<tasks with a result> <tasks wanted>"
    local c p
    c=$(ls "$OUT" 2>/dev/null | grep -cE '^[0-9]{4}\.json$' || true); p=$(ls "$SD/prompts" 2>/dev/null | grep -cE '^[0-9]{4}\.json$' || true)
    [ "$p" -eq 0 ] && p=$N; [ "$p" -gt "$N" ] && p=$N; [ "$c" -gt "$p" ] && c=$p; echo "$c $p"
}
jobline() { printf '{"job": "%s", "event": "%s", "time": "%s", "model": "%s", "scenario": "%s", "harness": "%s", %s}\n' "$SLURM_JOB_ID" "$1" "$(date '+%F %T')" "$NAME" "$S" "$H" "$2" >> "$SD/jobs/$NAME.jsonl"; }
submit_eval() {      # the setting is complete: its evaluation (CPU job) follows, unless EVAL=0 or one is already queued
    [ "${EVAL:-1}" = 0 ] && return 0
    local en="wb-eval-${SLURM_JOB_NAME#wb-}" id
    if [ -n "$(squeue -h -u "$USER" -n "$en" -o %i 2>/dev/null | head -1)" ]; then echo "evaluation job already in the queue ($en)"; return 0; fi
    # RUNS="" : a one-shot API setting is one result folder <model>, not the <model>-s1 / -s2 samples of the local runs
    id=$(env -u REDO -u FORCE -u TMPDIR -u N RUNS= sbatch --parsable --job-name="$en" ${EVAL_TIME:+--time=$EVAL_TIME} "$ROOT/vulcan/eval_setting.sbatch" "$NAME" "$S" "$H" 2>&1) \
        && echo "evaluation job submitted: $id ($en)" || echo "could not submit the evaluation ($id)"
}
read DONE0 TOTAL < <(count_done)
echo "setting: API model $NAME, scenario $S, harness $H; at most $GEN_ATTEMPTS generations per task; job $SLURM_JOB_ID ($SLURM_JOB_NAME), time limit $LIMIT"
echo "progress at start: $DONE0 / $TOTAL tasks"
if [ "$DONE0" -ge "$TOTAL" ] && [ "$TOTAL" -lt 100000 ]; then echo "nothing left to do for this setting"; [ "$N" -ge 100000 ] && submit_eval; exit 0; fi
CPUS=${SLURM_CPUS_PER_TASK:-1}
echo "node $(hostname), $CPUS CPUs; proxy ${https_proxy:-<none>}; local disk $LOCAL: $(df -h --output=avail "$LOCAL" | tail -1 | tr -d ' ') free"
W=$WORKERS; [ "$H" = oneshot ] || W=$AGENT_WORKERS
jobline start "\"node\": \"$(hostname)\", \"gpus\": 0, \"cpus\": $CPUS, \"mem_mb\": ${SLURM_MEM_PER_NODE:-0}, \"time_limit\": \"$LIMIT\", \"workers\": $W, \"gen_attempts\": $GEN_ATTEMPTS, \"image\": \"$(sha256sum "$SIF" | cut -c1-16)\", \"done_at_start\": $DONE0, \"tasks\": $TOTAL"
RC=0
if [ "$H" = oneshot ]; then
    [ "$TOTAL" -gt 0 ] && [ -d "$SD/prompts" ] || { echo "$SD/prompts: no prompts"; jobline end "\"result\": \"no prompts\""; exit 1; }
    LEFT=$((BUDGET - SECONDS))
    echo "===== one-shot, scenario $S, model $NAME, $WORKERS requests in parallel ($(date '+%F %T'))"
    timeout "${LEFT}s" apptainer exec --containall --pwd "$PKG" --bind "$PKG" --bind "$LOCAL":/t --bind "$SECRETS":/secrets.toml:ro --env "$CENV" "${PROXY[@]}" "$SIF" \
        python scripts/run_llm.py --scenario "$S" --stage programmer --models "$NAME" --limit "$N" --workers "$WORKERS" --gen-attempts "$GEN_ATTEMPTS" \
        || { RC=$?; echo "run_llm.py stopped (status $RC: 124 = this job's time budget is used up)"; }
else
    JOBS=$(( CPUS / AGENT_WORKERS )); [ "$JOBS" -lt 2 ] && JOBS=2
    echo "== unpacking $AGENT_WORKERS fresh tree pairs ($(date '+%T'))"
    apptainer exec --containall --pwd "$PKG" --bind "$PKG" --bind "$PACK":/pack/swe-pair.tar:ro --bind "$LOCAL":/t --env "TMPDIR=/t/tmp" \
        "$SIF" bash scripts/unpack_swe_trees.sh /pack/swe-pair.tar "$AGENT_WORKERS" || { jobline end "\"result\": \"trees could not be unpacked\""; exit 1; }
    [ -d "$SD/prompts" ] || apptainer exec --containall --pwd "$PKG" --bind "$PKG" --bind "$LOCAL":/t --env "TMPDIR=/t/tmp,PYTHONDONTWRITEBYTECODE=1" "$SIF" python scripts/build_prompts.py --scenario "$S" --stage "$H"
    LEFT=$((BUDGET - SECONDS)); echo "trees ready after $SECONDS s; $LEFT s of work left in this job"
    if [ "$LEFT" -gt 120 ]; then
        echo "===== $H, scenario $S, model $NAME, $AGENT_WORKERS tasks in parallel (make -j$JOBS each) ($(date '+%F %T'))"
        timeout "${LEFT}s" apptainer exec --containall --pwd "$PKG" --bind "$PKG" --bind "$LOCAL":/t --bind "$SECRETS":/secrets.toml:ro --env "$CENV" "${PROXY[@]}" "$SIF" \
            python "scripts/run_$H.py" --scenario "$S" --limit "$N" --models "$NAME" --workers "$AGENT_WORKERS" --jobs "$JOBS" \
            --src /t/wine-swe --build /t/wine-build-swe --gen-attempts "$GEN_ATTEMPTS" || { RC=$?; echo "run_$H.py stopped (status $RC: 124 = this job's time budget is used up)"; }
    fi
fi
read DONE1 TOTAL < <(count_done)
FAILED=$(grep -ls '"generation_failed": true' "$OUT"/[0-9][0-9][0-9][0-9].json 2>/dev/null | wc -l); RETRIED=$(ls "$OUT" 2>/dev/null | grep -cE '^[0-9]{4}\.attempt[0-9]+\.json$' || true)
echo "progress: $DONE0 -> $DONE1 / $TOTAL tasks in $(( (SECONDS - T0) / 60 )) min ($(date '+%F %T')); second attempts so far: $RETRIED; generation failed: $FAILED"
NEXT=""
if [ "$DONE1" -ge "$TOTAL" ]; then echo "SETTING COMPLETE: $PKG/$OUT/"; [ "$N" -ge 100000 ] && submit_eval || echo "(a trial with N=$N: no evaluation submitted)"
elif [ "${CHAIN:-1}" = 0 ]; then echo "tasks left; submit the same setting again to continue"
elif [ "$DONE1" -le "$DONE0" ]; then echo "NO PROGRESS in this job: not submitting a successor - check the log above"
else
    NEXT=$(sbatch --parsable --job-name="$SLURM_JOB_NAME" --time="$LIMIT" --cpus-per-task="$CPUS" ${SLURM_MEM_PER_NODE:+--mem=${SLURM_MEM_PER_NODE}M} "$ROOT/vulcan/run_api.sbatch" "$NAME" "$S" "$H" 2>&1) \
        && echo "successor job submitted: $NEXT" || { echo "could not submit the successor ($NEXT): submit the same setting again"; NEXT=""; }
fi
jobline end "\"result\": \"ok\", \"runner_status\": $RC, \"done_at_end\": $DONE1, \"tasks\": $TOTAL, \"second_attempts\": $RETRIED, \"generation_failed\": $FAILED, \"minutes\": $(( (SECONDS - T0) / 60 )), \"successor\": \"$NEXT\""
