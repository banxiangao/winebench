#!/bin/bash
#SBATCH --job-name=wb-pkeval
#SBATCH --account=aip-zhouyang
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --time=3:00:00
#SBATCH --output=vulcan/logs/%x-%j.out
# eval_samples.sbatch - evaluate the NS replies per task of one pass@k setting (CPU job, node-local clean trees).
#
#   cd .../WineBench/wine_bench && sbatch --job-name=wb-pkeval-1.1-qwen3.8-27b ../vulcan/eval_samples.sbatch qwen3.8-27b 1.1 0 4
#
# Arguments: MODEL SCENARIO [SHARD SHARDS]: shard i of m takes every m-th task, so m jobs share the setting (run_samples.sbatch
# submits them).  Each reply is judged as in eval_setting.sbatch (scripts/evaluate.py's evaluate_record); identical code of
# a task is built once.  Results: runs/scenario<S>/programmer/samples_eval/<model>-n<NS>/<id>.json (one file per task),
# results/pass_at_k.txt.  Recovery: tasks that have their file are skipped; the job stops STOP_MARGIN s before its limit
# and submits its successor (CHAIN=0: no).  Tunable: NS=100, EVAL_WORKERS=6, N (first N tasks), TEST_TIMEOUT=300.
set -e
NAME=${1:?model}; S=${2:?scenario}; SHARD=${3:-0}; SHARDS=${4:-1}
PKG=$(realpath "${SLURM_SUBMIT_DIR:-$PWD}"); ROOT=$(dirname "$PKG"); SIF=${SIF:-$ROOT/container/wine-agent.sif}
[ -f "$PKG/scripts/eval_samples.py" ] || { echo "$PKG has no scripts/eval_samples.py: submit from wine_bench"; exit 1; }
PACK=${EVAL_PACK:-$(realpath -m ~/scratch/winebench-w/eval-pair.tar)}
[ -f "$PACK" ] || { echo "$PACK: no packed clean tree (cd wine_agent && sbatch vulcan/pack_trees.sbatch)"; exit 1; }
[ -f "$SIF" ] || { echo "$SIF: no container image"; exit 1; }
cd "$PKG"
NS=${NS:-100}; SAMPLE="$NAME-n$NS"; SD="runs/scenario$S/programmer"; mkdir -p vulcan/logs "$SD/jobs" results
N=${N:-100000}; EVAL_WORKERS=${EVAL_WORKERS:-6}; STOP_MARGIN=${STOP_MARGIN:-600}
export NS N EVAL_WORKERS STOP_MARGIN CHAIN SIF EVAL_PACK TEST_TIMEOUT
T0=$SECONDS
LIMIT=$(squeue -h -j "$SLURM_JOB_ID" -o %l 2>/dev/null | head -1); LIMIT=${LIMIT:-3:00:00}
limit_seconds() { echo "$1" | awk -F'[-:]' '{ if (NF == 4) print $1*86400 + $2*3600 + $3*60 + $4; else if (NF == 3) print $1*3600 + $2*60 + $3; else if (NF == 2) print $1*60 + $2; else print $1*60 }'; }
BUDGET=$(( $(limit_seconds "$LIMIT") - STOP_MARGIN ))
# the tasks of this shard = positions SHARD, SHARD+SHARDS, ... of the sorted task list (as eval_samples.py --shard)
shard_ids() { ls "$SD/prompts" | grep -E '^[0-9]{4}\.json$' | sort | head -n "$N" | awk -v i="$SHARD" -v m="$SHARDS" '(NR - 1) % m == i' | cut -c1-4; }
count() { local c=0 i; for i in $(shard_ids); do [ -f "$SD/$1/$SAMPLE/$i.json" ] && c=$((c + 1)); done; echo "$c"; }
partial() { local c=0 i f; for i in $(shard_ids); do f="$SD/samples_eval/$SAMPLE/partial/$i.jsonl"; [ -f "$f" ] && c=$((c + $(wc -l < "$f"))); done; echo "$c"; }   # codes judged of unfinished tasks
TOTAL=$(shard_ids | wc -l); GEN=$(count samples); DONE0=$(count samples_eval); PART0=$(partial)
jobline() { printf '{"job": "%s", "event": "%s", "time": "%s", "model": "%s", "scenario": "%s", "harness": "samples", "shard": "%s/%s", %s}\n' "$SLURM_JOB_ID" "$1" "$(date '+%F %T')" "$SAMPLE" "$S" "$SHARD" "$SHARDS" "$2" >> "$SD/jobs/$SAMPLE.jsonl"; }
echo "evaluation of the pass@k setting: $SAMPLE, scenario $S, shard $SHARD/$SHARDS; job $SLURM_JOB_ID, time limit $LIMIT"
echo "tasks of this shard: $TOTAL; sampled: $GEN; evaluated at start: $DONE0"
[ "$TOTAL" -gt 0 ] || { echo "no tasks in this shard"; exit 0; }
if [ "$GEN" -lt "$TOTAL" ] && [ -z "$FORCE" ]; then echo "the sampling of this setting is not complete: not evaluating (FORCE=1 to evaluate what is there)"; exit 1; fi
if [ "$DONE0" -ge "$TOTAL" ]; then echo "nothing left to evaluate in this shard"; exit 0; fi
type module >/dev/null 2>&1 || { set +e; source /cvmfs/soft.computecanada.ca/config/profile/bash.sh; set -e; }
module load apptainer
CPUS=${SLURM_CPUS_PER_TASK:-16}; JOBS=$(( CPUS / EVAL_WORKERS )); [ "$JOBS" -lt 2 ] && JOBS=2
LOCAL=${SLURM_TMPDIR:-/tmp}/wb-pkeval-$SLURM_JOB_ID; mkdir -p "$LOCAL"; trap 'set +e; rm -rf "$LOCAL"' EXIT
echo "node $(hostname), $CPUS CPUs, $EVAL_WORKERS workers (make -j$JOBS each); local disk $LOCAL: $(df -h --output=avail "$LOCAL" | tail -1 | tr -d ' ') free"
jobline eval-start "\"node\": \"$(hostname)\", \"cpus\": $CPUS, \"mem_mb\": ${SLURM_MEM_PER_NODE:-0}, \"time_limit\": \"$LIMIT\", \"workers\": $EVAL_WORKERS, \"image\": \"$(sha256sum "$SIF" | cut -c1-16)\", \"pack\": \"$(head -1 "${PACK%.tar}.info" 2>/dev/null)\", \"evaluated_at_start\": $DONE0, \"tasks\": $TOTAL"
CENV="TMPDIR=/w/tmp,XDG_CACHE_HOME=/w/cache,PYTHONUNBUFFERED=1"
echo "== unpacking $EVAL_WORKERS clean tree pairs ($(date '+%T'))"
apptainer exec --containall --pwd "$PKG" --bind "$ROOT" --bind "$PACK":/pack/eval-pair.tar:ro --bind "$LOCAL":/w --env "$CENV" \
    "$SIF" bash "$ROOT/vulcan/unpack_eval_trees.sh" /pack/eval-pair.tar "$EVAL_WORKERS" || { jobline eval-end "\"result\": \"trees could not be unpacked\""; exit 1; }
# baselines are shared by all evaluations; the crash backups stay on this job's local disk
mkdir -p "$LOCAL/evalruns" "$ROOT/wine_agent/runs/baseline"; ln -sfn "$ROOT/wine_agent/runs/baseline" "$LOCAL/evalruns/baseline"
LEFT=$((BUDGET - SECONDS)); RC=0
echo "===== evaluate: scenario $S, $SAMPLE, shard $SHARD/$SHARDS ($(date '+%F %T'), $LEFT s left)"
if [ "$LEFT" -gt 300 ]; then
    timeout "$((LEFT + 480))s" apptainer exec --containall --pwd "$PKG" --bind "$ROOT" --bind "$LOCAL":/w --env "$CENV" "$SIF" \
        python scripts/eval_samples.py --src /w/wine --build /w/wine-build --scenario "$S" --model "$SAMPLE" --shard "$SHARD/$SHARDS" \
        --workers "$EVAL_WORKERS" --jobs "$JOBS" --prefix /w/pfx/wine --own-xvfb --runs /w/evalruns --timeout "${TEST_TIMEOUT:-300}" --seconds "$((LEFT - 300))" \
        $( [ "$N" -lt 100000 ] && echo "--limit $N" ) || { RC=$?; echo "eval_samples.py stopped (status $RC)"; }
fi
apptainer exec --containall --pwd "$PKG" --bind "$ROOT" "$SIF" bash -c 'python scripts/pass_at_k.py > results/pass_at_k.txt.new.$$ && mv results/pass_at_k.txt.new.$$ results/pass_at_k.txt; python scripts/pass_at_k.py --csv > results/pass_at_k.csv.new.$$ && mv results/pass_at_k.csv.new.$$ results/pass_at_k.csv' || true
echo "----- results/pass_at_k.txt"; cat results/pass_at_k.txt 2>/dev/null || true
DONE1=$(count samples_eval); PART1=$(partial)
echo "evaluated: $DONE0 -> $DONE1 / $TOTAL tasks of shard $SHARD/$SHARDS (codes judged of unfinished tasks: $PART0 -> $PART1) in $(( (SECONDS - T0) / 60 )) min ($(date '+%F %T'))"
NEXT=""; RESULT=ok
if [ "$DONE1" -ge "$TOTAL" ]; then echo "SHARD COMPLETE: $PKG/$SD/samples_eval/$SAMPLE/"
elif [ "${CHAIN:-1}" = 0 ]; then echo "tasks left; submit the same shard again to continue"
elif [ "$DONE1" -le "$DONE0" ] && [ "$PART1" -le "$PART0" ]; then echo "NO PROGRESS in this job: not submitting a successor - check the log above"; RESULT=no-progress
else
    NEXT=$(sbatch --parsable --job-name="$SLURM_JOB_NAME" --time="$LIMIT" --cpus-per-task="$CPUS" ${SLURM_MEM_PER_NODE:+--mem=${SLURM_MEM_PER_NODE}M} "$ROOT/vulcan/eval_samples.sbatch" "$NAME" "$S" "$SHARD" "$SHARDS" 2>&1) \
        && echo "successor job submitted: $NEXT" || { echo "could not submit the successor ($NEXT)"; NEXT=""; }
fi
jobline eval-end "\"result\": \"$RESULT\", \"runner_status\": $RC, \"evaluated_at_end\": $DONE1, \"tasks\": $TOTAL, \"minutes\": $(( (SECONDS - T0) / 60 )), \"successor\": \"$NEXT\""
[ "$RESULT" = ok ] || exit 1
