#!/usr/bin/env bash
# run_eval_ubuntu.sh - one-shot evaluation on this Ubuntu box: setup (only if the build is missing) -> tree copies for
# the workers -> eval_all -> save tables.
#
#   WORKERS=4 bash scripts/run_eval_ubuntu.sh                  # everything, 4 records at once
#   WORKERS=4 LIMIT=20 bash scripts/run_eval_ubuntu.sh         # quick look: first 20 records of every run
#   WORKERS=4 bash scripts/run_eval_ubuntu.sh glm-4-7-flashx   # one model (or comma-separated list)
#
# Wine source/build default to a clean wine-11.18 in ~/wine and ~/wine-build (NOT ~/Desktop/wine_fuzz/wine, which is
# 11.19 and used for mutation testing).  Override with WINE_SRC / WINE_BUILD.
set -e
cd "$(dirname "$0")/.."
export WINE_SRC=${WINE_SRC:-$HOME/wine} WINE_BUILD=${WINE_BUILD:-$HOME/wine-build} WORKERS=${WORKERS:-1}
mkdir -p results
TS=$(date +%Y%m%d_%H%M%S)

if [ ! -f "$WINE_BUILD/Makefile" ] || [ ! -e "$WINE_BUILD/wine" ]; then
    echo "== $WINE_BUILD not built yet: running setup_eval_ubuntu.sh (30-90 min)"
    bash scripts/setup_eval_ubuntu.sh 2>&1 | tee "results/setup_$TS.log"
    [ "${PIPESTATUS[0]}" -eq 0 ] || { echo "setup failed, see results/setup_$TS.log"; exit 1; }
else
    echo "== $WINE_BUILD already built: setup skipped"
fi

if [ "$WORKERS" -gt 1 ]; then
    echo "== tree copies for $WORKERS workers"
    bash scripts/make_eval_trees.sh "$WORKERS"
fi

echo "== eval_all, $WORKERS worker(s) (log: results/eval_$TS.log)"
bash scripts/eval_all.sh "$@" 2>&1 | tee "results/eval_$TS.log"

python3 scripts/evaluate.py --table       | tee "results/table_$TS.txt"
python3 scripts/evaluate.py --table --csv  >   "results/table_$TS.csv"
echo "== saved results/table_$TS.txt and results/table_$TS.csv  (per-record details: runs/scenario*/programmer/**/eval/<model>/*.json)"
