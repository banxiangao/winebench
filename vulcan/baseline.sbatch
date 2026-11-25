#!/bin/bash
#SBATCH --job-name=wb-baseline
#SBATCH --account=aip-zhouyang
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --time=1:30:00
#SBATCH --output=vulcan/logs/%x-%j.out
# baseline.sbatch - run every test file of the dataset once on the clean Wine tree (node-local copies) and store the
# results in wine_agent/runs/baseline/, which all evaluations compare against.  Evaluations compute a missing baseline
# on demand; running them all first shows, before any model output is judged, which test files do not run to their
# summary line on the clean tree (those are skipped by the evaluation: a record with only such tests is "no_tests").
#
#   cd .../WineBench/wine_agent && sbatch ../vulcan/baseline.sbatch
# SCN=<path of a config.toml> takes the records of another dataset (default: scenario 3.1's).
set -e
PKG=$(realpath "${SLURM_SUBMIT_DIR:-$PWD}"); ROOT=$(dirname "$PKG"); SIF=$ROOT/container/wine-agent.sif
PACK=$(realpath -m ~/scratch/winebench-w/eval-pair.tar); W=${EVAL_WORKERS:-6}
type module >/dev/null 2>&1 || { set +e; source /cvmfs/soft.computecanada.ca/config/profile/bash.sh; set -e; }
module load apptainer
cd "$PKG"; mkdir -p vulcan/logs "$ROOT/wine_agent/runs/baseline"
LOCAL=${SLURM_TMPDIR:-/tmp}/wb-baseline-$SLURM_JOB_ID; mkdir -p "$LOCAL"; trap 'set +e; rm -rf "$LOCAL"' EXIT
CENV="TMPDIR=/w/tmp,XDG_CACHE_HOME=/w/cache,PYTHONUNBUFFERED=1"
apptainer exec --containall --pwd "$PKG" --bind "$ROOT" --bind "$PACK":/pack/eval-pair.tar:ro --bind "$LOCAL":/w --env "$CENV" "$SIF" bash "$ROOT/vulcan/unpack_eval_trees.sh" /pack/eval-pair.tar "$W"
mkdir -p "$LOCAL/evalruns"; ln -sfn "$ROOT/wine_agent/runs/baseline" "$LOCAL/evalruns/baseline"
apptainer exec --containall --pwd "$PKG" --bind "$ROOT" --bind "$LOCAL":/w --env "$CENV" "$SIF" \
    python scripts/evaluate.py --src /w/wine --build /w/wine-build --scenario "${SCN:-3.1}" --stage mini_swe --baseline --workers "$W" --jobs 2 \
    --prefix /w/pfx/wine --own-xvfb --runs /w/evalruns
echo "baseline files: $(ls "$ROOT/wine_agent/runs/baseline" | wc -l)"
grep -h '"status"' "$ROOT/wine_agent/runs/baseline"/*.json | sort | uniq -c
