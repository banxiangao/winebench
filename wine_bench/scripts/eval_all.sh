#!/usr/bin/env bash
# LEGACY: written for the earlier two-stage design (architect -> programmer).  Scenario numbers in the comments below are
# those of that design, not the current scenarios 1.1 / 1.2 (one-shot) and 2.1 / 2.2 (agent).  Not used by the Vulcan jobs.
# eval_all.sh - run scripts/evaluate.py for every model and scenario that has programmer replies (Linux, after
# scripts/setup_eval_ubuntu.sh).  Resumable: records that already have a result are skipped.
#
#   bash scripts/eval_all.sh                      # everything
#   LIMIT=20 bash scripts/eval_all.sh             # the first 20 records of every run (a quick look at the success rates)
#   bash scripts/eval_all.sh claude-haiku-5-5     # one model (or a comma-separated list)
#   WINE_SRC=~/wine WINE_BUILD=~/wine-build EVAL_OPTS="--timeout 300" bash scripts/eval_all.sh
#   WORKERS=4 bash scripts/eval_all.sh            # 4 records at once (after: bash scripts/make_eval_trees.sh 4)
#   SCENARIOS="1.1 1.2" bash scripts/eval_all.sh  # only these scenarios
set -e
cd "$(dirname "$0")/.."
SRC=${WINE_SRC:-$HOME/wine}; BUILD=${WINE_BUILD:-$HOME/wine-build}; PY=${PY:-python3}
[ -n "$LIMIT" ] && LIM="--limit $LIMIT" || LIM=""
WORKERS=${WORKERS:-1}                                       # >1: needs scripts/make_eval_trees.sh $WORKERS first
if [ "$WORKERS" -gt 1 ]; then XVFB=""                       # evaluate.py starts one Xvfb per worker itself
elif command -v xvfb-run >/dev/null; then XVFB="xvfb-run -a"; else XVFB=""; echo "warning: xvfb-run not found; tests that need a display will fail"; fi
W="--src $SRC --build $BUILD --workers $WORKERS $LIM $EVAL_OPTS"

if [ -n "$1" ]; then MODELS=${1//,/ }
else MODELS=$(ls -d runs/scenario*/programmer/from_*/responses/* runs/scenario*/programmer/responses/* 2>/dev/null | xargs -n1 basename | sort -u); fi
echo "models: $MODELS"

SCENARIOS=${SCENARIOS:-"1.1 1.2"}               # e.g. SCENARIOS="1.1"
for M in $MODELS; do
    for S in $SCENARIOS; do
        if [ -d runs/scenario$S/programmer/from_$M/responses/$M ]; then      # 1.1 / 1.2: each model implements its own specs
            echo "===== scenario $S, programmer $M (specs by $M)"
            $XVFB $PY scripts/evaluate.py $W --scenario $S --stage programmer --from-model "$M" --models "$M"
        elif [ -d runs/scenario$S/programmer/responses/$M ]; then             # 1.1 / 1.2 / 2.1: no upstream stage
            echo "===== scenario $S, programmer $M"
            $XVFB $PY scripts/evaluate.py $W --scenario $S --stage programmer --models "$M"
        fi
    done
done
$PY scripts/evaluate.py --table
