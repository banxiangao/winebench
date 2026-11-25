#!/bin/bash
#SBATCH --job-name=wb-eval
#SBATCH --account=aip-zhouyang
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --time=3:00:00
#SBATCH --output=vulcan/logs/%x-%j.out
# eval_setting.sbatch - the numbers of ONE setting: compile every generated implementation inside Wine and run Wine's own
# tests on it (scripts/evaluate.py).  CPU only.  Normally the generation job of the setting submits it when the setting
# is complete; by hand:
#
#   cd .../WineBench && bash vulcan/submit.sh eval qwen3.8-27b 3.1 openhands      # agent setting
#   cd .../WineBench && bash vulcan/submit.sh eval qwen3.8-27b 1.3                # one-shot setting (both samples)
#
# It runs in the package directory (wine_agent for 3.x, wine_bench for 1.x).  The clean, fully built Wine comes from
# ~/scratch/winebench-w/eval-pair.tar (wine_agent/vulcan/pack_trees.sbatch), unpacked onto the node's local disk, one
# copy per worker; each worker has its own Wine prefix and Xvfb display.  Nothing of that outlives the job.
# Results:  runs/scenario<S>/<stage>/eval/<model>/<id>.json + summary.json   (stage = harness, or "programmer" for one-shot)
#           results/table.txt and table.csv of the package: one line per evaluated setting
#           runs/baseline/: the same tests on the untouched tree, computed once and shared by all settings
# Record status: no_code | splice_fail | compile_fail | test_fail | crash | timeout | pass | no_tests.
# A setting is evaluated only when its generation is complete (a task without a result would be stored as no_code and
# not looked at again); FORCE=1 evaluates what is there.  Recovery: tasks that have an evaluation are skipped, so the same
# command continues; the job stops 10 minutes before its limit and submits its successor if tasks are left (CHAIN=0: no).
# REDO=1 evaluates everything again.  Tunable: EVAL_WORKERS=6, N (first N tasks, as in the generation job), TEST_TIMEOUT=300.
set -e
NAME=${1:?model}; S=${2:?scenario}; H=${3:-oneshot}
PKG=$(realpath "${SLURM_SUBMIT_DIR:-$PWD}"); ROOT=$(dirname "$PKG"); SIF=${SIF:-$ROOT/container/wine-agent.sif}
[ -f "$PKG/scripts/evaluate.py" ] || { echo "$PKG has no scripts/evaluate.py: submit from wine_agent or wine_bench (bash vulcan/submit.sh eval ...)"; exit 1; }
PACK=${EVAL_PACK:-$(realpath -m ~/scratch/winebench-w/eval-pair.tar)}
[ -f "$PACK" ] || { echo "$PACK: no packed clean tree (cd wine_agent && sbatch vulcan/pack_trees.sbatch)"; exit 1; }
[ -f "$SIF" ] || { echo "$SIF: no container image"; exit 1; }
cd "$PKG"
if [ "$H" = oneshot ]; then
    STAGE=programmer; RUNS=${RUNS-"s1 s2"}
    MODELS=$NAME; [ -n "$RUNS" ] && MODELS=$(for r in $RUNS; do printf '%s-%s,' "$NAME" "$r"; done | sed 's/,$//')
else STAGE=$H; MODELS=$NAME; fi
SD="runs/scenario$S/$STAGE"; mkdir -p vulcan/logs "$SD/jobs" results
N=${N:-100000}; EVAL_WORKERS=${EVAL_WORKERS:-6}; STOP_MARGIN=${STOP_MARGIN:-600}
export N EVAL_WORKERS STOP_MARGIN RUNS CHAIN SIF EVAL_PACK TEST_TIMEOUT
T0=$SECONDS; K=$(echo "${MODELS//,/ }" | wc -w)
LIMIT=$(squeue -h -j "$SLURM_JOB_ID" -o %l 2>/dev/null | head -1); LIMIT=${LIMIT:-3:00:00}
limit_seconds() { echo "$1" | awk -F'[-:]' '{ if (NF == 4) print $1*86400 + $2*3600 + $3*60 + $4; else if (NF == 3) print $1*3600 + $2*60 + $3; else if (NF == 2) print $1*60 + $2; else print $1*60 }'; }
BUDGET=$(( $(limit_seconds "$LIMIT") - STOP_MARGIN ))
count() {                                                                            # $1 = responses | eval  -> files of all samples
    local c=0 m; for m in ${MODELS//,/ }; do c=$((c + $(ls "$SD/$1/$m" 2>/dev/null | grep -cE '^[0-9]{4}\.json$' || true))); done; echo "$c"
}
P=$(ls "$SD/prompts" 2>/dev/null | grep -cE '^[0-9]{4}\.json$' || true); [ "$P" -gt "$N" ] && P=$N; TOTAL=$((P * K))
GEN=$(count responses); DONE0=$(count eval); [ "$DONE0" -gt "$TOTAL" ] && DONE0=$TOTAL
jobline() { printf '{"job": "%s", "event": "%s", "time": "%s", "model": "%s", "scenario": "%s", "harness": "%s", %s}\n' "$SLURM_JOB_ID" "$1" "$(date '+%F %T')" "$NAME" "$S" "$H" "$2" >> "$SD/jobs/$NAME.jsonl"; }
echo "evaluation of the setting: model $NAME, scenario $S, harness $H (stage $STAGE, results of: $MODELS); job $SLURM_JOB_ID, time limit $LIMIT"
echo "generated: $GEN / $TOTAL; evaluated at start: $DONE0 / $TOTAL"
[ "$TOTAL" -gt 0 ] || { echo "$SD/prompts: no tasks"; exit 1; }
if [ "$GEN" -lt "$TOTAL" ] && [ -z "$FORCE" ]; then echo "the generation of this setting is not complete: not evaluating (FORCE=1 to evaluate what is there)"; exit 1; fi
if [ "$DONE0" -ge "$TOTAL" ] && [ -z "$REDO" ]; then echo "nothing left to evaluate for this setting"; exit 0; fi
type module >/dev/null 2>&1 || { set +e; source /cvmfs/soft.computecanada.ca/config/profile/bash.sh; set -e; }
module load apptainer
CPUS=${SLURM_CPUS_PER_TASK:-16}; JOBS=$(( CPUS / EVAL_WORKERS )); [ "$JOBS" -lt 2 ] && JOBS=2
LOCAL=${SLURM_TMPDIR:-/tmp}/wb-eval-$SLURM_JOB_ID; mkdir -p "$LOCAL"; trap 'set +e; rm -rf "$LOCAL"' EXIT
echo "node $(hostname), $CPUS CPUs, $EVAL_WORKERS workers (make -j$JOBS each); local disk $LOCAL: $(df -h --output=avail "$LOCAL" | tail -1 | tr -d ' ') free"
jobline eval-start "\"node\": \"$(hostname)\", \"cpus\": $CPUS, \"mem_mb\": ${SLURM_MEM_PER_NODE:-0}, \"time_limit\": \"$LIMIT\", \"workers\": $EVAL_WORKERS, \"image\": \"$(sha256sum "$SIF" | cut -c1-16)\", \"pack\": \"$(head -1 "${PACK%.tar}.info" 2>/dev/null)\", \"evaluated_at_start\": $DONE0, \"tasks\": $TOTAL"
CENV="TMPDIR=/w/tmp,XDG_CACHE_HOME=/w/cache,PYTHONUNBUFFERED=1"
echo "== unpacking $EVAL_WORKERS clean tree pairs ($(date '+%T'))"
apptainer exec --containall --pwd "$PKG" --bind "$ROOT" --bind "$PACK":/pack/eval-pair.tar:ro --bind "$LOCAL":/w --env "$CENV" \
    "$SIF" bash "$ROOT/vulcan/unpack_eval_trees.sh" /pack/eval-pair.tar "$EVAL_WORKERS" || { jobline eval-end "\"result\": \"trees could not be unpacked\""; exit 1; }
# evaluate.py keeps its crash backups and the baselines under --runs.  The backups must be private to this job (another
# evaluation running at the same time would "repair" its own trees from them and delete them); the baselines are shared.
mkdir -p "$LOCAL/evalruns" "$ROOT/wine_agent/runs/baseline"; ln -sfn "$ROOT/wine_agent/runs/baseline" "$LOCAL/evalruns/baseline"
LEFT=$((BUDGET - SECONDS)); RC=0
echo "===== evaluate: scenario $S, stage $STAGE, $MODELS ($(date '+%F %T'), $LEFT s left)"
if [ "$LEFT" -gt 120 ]; then
    timeout "${LEFT}s" apptainer exec --containall --pwd "$PKG" --bind "$ROOT" --bind "$LOCAL":/w --env "$CENV" "$SIF" \
        python scripts/evaluate.py --src /w/wine --build /w/wine-build --scenario "$S" --stage "$STAGE" --models "$MODELS" \
        --workers "$EVAL_WORKERS" --jobs "$JOBS" --prefix /w/pfx/wine --own-xvfb --runs /w/evalruns --timeout "${TEST_TIMEOUT:-300}" \
        $( [ "$N" -lt 100000 ] && echo "--limit $N" ) ${REDO:+--redo} || { RC=$?; echo "evaluate.py stopped (status $RC: 124 = this job's time budget is used up)"; }
fi
for m in ${MODELS//,/ }; do rm -f "$SD/eval/$m"/*.backup.json 2>/dev/null || true; done   # of THIS job only (their trees are gone with it); another evaluation of the same stage may be running and needs its own
apptainer exec --containall --pwd "$PKG" --bind "$ROOT" "$SIF" bash -c 'python scripts/evaluate.py --table > results/table.txt.new && mv results/table.txt.new results/table.txt; python scripts/evaluate.py --table --csv > results/table.csv.new && mv results/table.csv.new results/table.csv' || true
echo "----- results/table.txt (this setting)"; { head -1 results/table.txt; grep -E "^$S +$STAGE " results/table.txt | grep -F "$NAME"; } 2>/dev/null || true
DONE1=$(count eval); [ "$DONE1" -gt "$TOTAL" ] && DONE1=$TOTAL
echo "evaluated: $DONE0 -> $DONE1 / $TOTAL in $(( (SECONDS - T0) / 60 )) min ($(date '+%F %T'))"
NEXT=""
if [ "$DONE1" -ge "$TOTAL" ]; then echo "EVALUATION COMPLETE: $PKG/$SD/eval/, $PKG/results/table.txt"
elif [ "${CHAIN:-1}" = 0 ] || [ -n "$REDO" ]; then echo "tasks left; submit the same evaluation again to continue"
elif [ "$DONE1" -le "$DONE0" ]; then echo "NO PROGRESS in this job: not submitting a successor - check the log above"
else
    NEXT=$(sbatch --parsable --job-name="$SLURM_JOB_NAME" --time="$LIMIT" --cpus-per-task="$CPUS" ${SLURM_MEM_PER_NODE:+--mem=${SLURM_MEM_PER_NODE}M} "$ROOT/vulcan/eval_setting.sbatch" "$NAME" "$S" "$H" 2>&1) \
        && echo "successor job submitted: $NEXT" || { echo "could not submit the successor ($NEXT)"; NEXT=""; }
fi
jobline eval-end "\"result\": \"ok\", \"runner_status\": $RC, \"evaluated_at_end\": $DONE1, \"tasks\": $TOTAL, \"minutes\": $(( (SECONDS - T0) / 60 )), \"successor\": \"$NEXT\""
