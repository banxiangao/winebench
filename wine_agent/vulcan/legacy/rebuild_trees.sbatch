#!/bin/bash
#SBATCH --job-name=winebench-rebuild
#SBATCH --account=aip-zhouyang
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=1:00:00
#SBATCH --output=vulcan/logs/%x-%j.out
# rebuild_trees.sbatch - replace broken restricted tree pairs of one model by fresh copies of the clean, built Wine
# (~/scratch/winebench-w; nothing is compiled), then smoke-test every pair (scripts/smoke_tree.py).  No GPU, no model.
#
#   cd .../WineBench/wine_agent
#   sbatch vulcan/rebuild_trees.sbatch glm-4.7-flash                 # pairs whose Makefile wants to be regenerated
#   FORCE="1 2 3 4" sbatch vulcan/rebuild_trees.sbatch glm-4.7-flash # these workers in any case
# A pair is broken when tools/makedep is newer than the Makefile: every ./compile then tries to regenerate the makefiles
# and fails (the test sources are gone).  Do not run it while an agents job of the same model is running.
set -e
NAME=${1:?model name}
WA=$(realpath "${SLURM_SUBMIT_DIR:-$PWD}"); PROJ=${PROJ:-$(dirname "$WA")}; SIF=${SIF:-$PROJ/container/wine-agent.sif}
W=$(realpath -m ~/scratch/winebench-w); TREES=$(realpath -m ~/scratch/winebench-trees/$NAME)
[ -f "$WA/scripts/make_swe_trees.sh" ] || { echo "$WA is not the wine_agent directory"; exit 1; }
[ -d "$TREES" ] || { echo "$TREES: no trees"; exit 1; }
cd "$WA"
type module >/dev/null 2>&1 || { set +e; source /cvmfs/soft.computecanada.ca/config/profile/bash.sh; set -e; }   # sbatch from a shell that does not export the module function
module load apptainer
N=$(ls -d "$TREES"/wine-build-swe* | wc -l); echo "$NAME: $N tree pairs in $TREES; forced: ${FORCE:-none}"
for i in $(seq 0 $((N - 1))); do
    sfx=""; [ "$i" -gt 0 ] && sfx="-w$i"; S="$TREES/wine-swe$sfx"; B="$TREES/wine-build-swe$sfx"; why=""
    case " $FORCE " in *" $i "*) why="forced" ;; esac
    [ -f "$B/Makefile" ] || why="no Makefile"
    [ -z "$why" ] && [ "$B/tools/makedep" -nt "$B/Makefile" ] && why="tools/makedep is newer than Makefile"
    if [ -n "$why" ]; then echo "worker $i: $why -> removing ($(date '+%T'))"; rm -rf "$S" "$S.gitdir" "$S.taskgit" "$B"; else echo "worker $i: kept"; fi
done
echo "== copying ($(date '+%T'))"
apptainer exec --containall --pwd "$WA" --bind "$WA" --bind "$W":/w --bind "$TREES":/t \
    --env "WINE_SRC=/w/wine,WINE_BUILD=/w/wine-build,SWE_SRC=/t/wine-swe,SWE_BUILD=/t/wine-build-swe,TMPDIR=/t/tmp" \
    "$SIF" bash scripts/make_swe_trees.sh "$N" 2>&1 | grep -v "^done\."
echo "== smoke test ($(date '+%T'))"
apptainer exec --containall --pwd "$WA" --bind "$WA" --bind "$TREES":/t --env "TMPDIR=/t/tmp,PYTHONUNBUFFERED=1" \
    "$SIF" bash -c 'echo "home: $HOME ($(df -h --output=fstype,size "$HOME" | tail -1 | tr -s " "))"; python scripts/smoke_tree.py --src /t/wine-swe --build /t/wine-build-swe --workers '"$N"
echo "REBUILD-OK ($(date '+%T'))"
