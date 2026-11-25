#!/usr/bin/env bash
# submit.sh - the one entry point for the experiments on Vulcan.  One setting = one job.
#
#   cd .../WineBench
#   bash vulcan/submit.sh list                                   # every setting: generated, evaluated, jobs in the queue
#   bash vulcan/submit.sh qwen3.8-27b 3.1 openhands              # an agent setting    (model, scenario, harness)
#   bash vulcan/submit.sh qwen3.8-27b 1.3                        # a one-shot setting  (model, scenario)
#   bash vulcan/submit.sh eval qwen3.8-27b 3.1 openhands         # only the evaluation of a setting (CPU job)
#   bash vulcan/submit.sh table                                  # the numbers: results/table.txt of both packages
#   N=12 CHAIN=0 bash vulcan/submit.sh glm-4.7-flash 3.2 mini_swe --time=0:30:00     # a trial: first 12 tasks, no successor
#
# A setting is a line of vulcan/experiments.tsv; the job's GPUs, CPUs, memory, time limit and worker count come from
# that line (sbatch options given after the names override them).  Jobs: wb-<scenario>-<harness>-<model> generates (GPU);
# when the setting is complete it submits wb-eval-<scenario>-<harness>-<model> (CPU), which compiles and tests the
# generated code and writes the numbers.  EVAL=0 keeps the generation job from doing that.
# Submitting a setting that is partly done continues it; one that is complete only makes sure its evaluation exists.
# Both kinds of job need the packed trees once:  cd wine_agent && sbatch vulcan/pack_trees.sbatch
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd); TABLE="$ROOT/vulcan/experiments.tsv"
rows() { grep -v '^#' "$TABLE" | awk -F'\t' 'NF >= 8'; }
place() {   # scenario harness model -> PKG (package dir), SD (stage dir), MS (result folders of the setting)
    if [ "$2" = oneshot ]; then PKG="$ROOT/wine_bench"; SD="$PKG/runs/scenario$1/programmer"; MS="$3-s1 $3-s2"
    else PKG="$ROOT/wine_agent"; SD="$PKG/runs/scenario$1/$2"; MS="$3"; fi
}
if [ "${1:-}" = list ]; then
    Q=$(squeue -u "$USER" -h -o "%j %i %T" 2>/dev/null || true)
    printf '%-9s %-10s %-15s %-10s %-10s %-26s %s\n' scenario harness model generated evaluated "gpu/cpu/mem/time" "jobs in the queue"
    rows | while IFS=$'\t' read -r S H M G C MEM T W; do
        place "$S" "$H" "$M"
        p=$(ls "$SD/prompts" 2>/dev/null | grep -cE '^[0-9]{4}\.json$' || true); c=0; e=0; k=0
        for m in $MS; do
            c=$((c + $(ls "$SD/responses/$m" 2>/dev/null | grep -cE '^[0-9]{4}\.json$' || true)))
            e=$((e + $(ls "$SD/eval/$m" 2>/dev/null | grep -cE '^[0-9]{4}\.json$' || true))); k=$((k + 1))
        done
        [ "$p" -gt 0 ] && t=$((p * k)) || t="?"
        jobs=$(echo "$Q" | awk -v n="wb-$S-$H-$M" -v e="wb-eval-$S-$H-$M" '$1 == n {printf "gen %s(%s) ", $2, $3} $1 == e {printf "eval %s(%s) ", $2, $3}')
        printf '%-9s %-10s %-15s %-10s %-10s %-26s %s\n' "$S" "$H" "$M" "$c/$t" "$e/$t" "$G/$C/$MEM/$T" "$jobs"
    done
    exit 0
fi
if [ "${1:-}" = table ]; then
    for p in wine_bench wine_agent; do echo "== $p/results/table.txt"; cat "$ROOT/$p/results/table.txt" 2>/dev/null || echo "(no evaluation yet)"; done
    exit 0
fi
ONLY_EVAL=""; if [ "${1:-}" = eval ]; then ONLY_EVAL=1; shift; fi
M=${1:?model (or: list | table | eval <model> <scenario> [harness])}; S=${2:?scenario}; shift 2
H=oneshot; if [ $# -gt 0 ] && [ "${1#-}" = "$1" ]; then H=$1; shift; fi
ROW=$(rows | awk -F'\t' -v s="$S" -v h="$H" -v m="$M" '$1 == s && $2 == h && $3 == m' | head -1)
[ -n "$ROW" ] || { echo "no such setting in $TABLE: scenario $S, harness $H, model $M   (bash vulcan/submit.sh list)"; exit 1; }
IFS=$'\t' read -r _ _ _ G C MEM T W <<< "$ROW"
place "$S" "$H" "$M"; cd "$PKG"; mkdir -p vulcan/logs
if [ -n "$ONLY_EVAL" ]; then
    sbatch --job-name="wb-eval-$S-$H-$M" "$@" "$ROOT/vulcan/eval_setting.sbatch" "$M" "$S" "$H"
elif [ "$H" = oneshot ]; then
    WORKERS=${WORKERS:-$W} sbatch --job-name="wb-$S-$H-$M" --gres="gpu:l40s:$G" --cpus-per-task="$C" --mem="$MEM" --time="$T" "$@" vulcan/run_setting.sbatch "$M" "$S"
else
    AGENT_WORKERS=${AGENT_WORKERS:-$W} sbatch --job-name="wb-$S-$H-$M" --gres="gpu:l40s:$G" --cpus-per-task="$C" --mem="$MEM" --time="$T" "$@" vulcan/run_setting.sbatch "$M" "$S" "$H"
fi
