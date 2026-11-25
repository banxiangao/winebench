#!/bin/bash
#SBATCH --job-name=wb-pack
#SBATCH --account=aip-zhouyang
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=1:00:00
#SBATCH --output=vulcan/logs/%x-%j.out
# pack_trees.sbatch - pack the two kinds of Wine tree every job unpacks onto its node-local disk, from the clean, built
# Wine in ~/scratch/winebench-w (container/build_wine.sbatch):
#     swe-pair.tar    /t/wine-swe, /t/wine-swe.gitdir, /t/wine-build-swe   the RESTRICTED pair the agents work in
#                     (no tests, no history; scripts/make_swe_trees.sh)            -> vulcan/run_setting.sbatch
#     eval-pair.tar   /w/wine, /w/wine-build                               the CLEAN pair with all tests built, in which
#                     the generated code is compiled and tested                    -> ../vulcan/eval_setting.sbatch
# Run it once, and again whenever the Wine build, the container or make_swe_trees.sh changes.  Each tarball is tested
# before it replaces the old one: unpacked twice; the restricted pair goes through scripts/smoke_tree.py, the clean pair
# runs one Wine test under Xvfb (which also shows that Wine itself works in the container).  No GPU, nothing is compiled.
#
#   cd .../WineBench/wine_agent && sbatch vulcan/pack_trees.sbatch
set -e
WA=$(realpath "${SLURM_SUBMIT_DIR:-$PWD}"); PROJ=${PROJ:-$(dirname "$WA")}; SIF=${SIF:-$PROJ/container/wine-agent.sif}
W=$(realpath -m ~/scratch/winebench-w); LOCAL=${SLURM_TMPDIR:-/tmp}/wb-pack-$SLURM_JOB_ID
[ -f "$WA/scripts/make_swe_trees.sh" ] || { echo "$WA is not the wine_agent directory"; exit 1; }
[ -e "$W/wine-build/wine" ] || { echo "$W/wine-build: Wine is not built (container/build_wine.sbatch)"; exit 1; }
cd "$WA"
type module >/dev/null 2>&1 || { set +e; source /cvmfs/soft.computecanada.ca/config/profile/bash.sh; set -e; }
module load apptainer
mkdir -p "$LOCAL/a/tmp" "$LOCAL/b/tmp" "$LOCAL/c"; trap 'rm -rf "$LOCAL"' EXIT
echo "node $(hostname); local disk $LOCAL: $(df -h --output=size,avail "$LOCAL" | tail -1 | tr -s ' ') (size, free)"
IMG=$(sha256sum "$SIF" | cut -c1-16)

echo "== 1/2 restricted pair: making it ($(date '+%T'))"
apptainer exec --containall --pwd "$WA" --bind "$WA" --bind "$W":/w --bind "$LOCAL/a":/t \
    --env "WINE_SRC=/w/wine,WINE_BUILD=/w/wine-build,SWE_SRC=/t/wine-swe,SWE_BUILD=/t/wine-build-swe,TMPDIR=/t/tmp" "$SIF" bash -c '
    set -e; bash scripts/make_swe_trees.sh 1 | grep -v "^done\."
    git --git-dir /t/wine-swe.gitdir config core.checkStat minimal      # an unpacked copy has other inodes / ctimes: compare mtime and size only
    git --git-dir /t/wine-swe.gitdir config core.trustctime false
    echo "   packing ($(date +%T))"
    tar --format=posix -cf /w/swe-pair.tar.new -C /t wine-swe wine-swe.gitdir wine-build-swe'
echo "   testing the tarball ($(date '+%T'))"
apptainer exec --containall --pwd "$WA" --bind "$WA" --bind "$W/swe-pair.tar.new":/pack/swe-pair.tar:ro --bind "$LOCAL/b":/t \
    --env "TMPDIR=/t/tmp,PYTHONUNBUFFERED=1" "$SIF" bash -c '
    set -e; bash scripts/unpack_swe_trees.sh /pack/swe-pair.tar 2
    python scripts/smoke_tree.py --src /t/wine-swe --build /t/wine-build-swe --workers 2'
mv "$W/swe-pair.tar.new" "$W/swe-pair.tar"
{ echo "packed $(date '+%F %T') by job $SLURM_JOB_ID, image $IMG"; ls -l "$W/swe-pair.tar"; } > "$W/swe-pair.info"; cat "$W/swe-pair.info"
rm -rf "$LOCAL/a" "$LOCAL/b"

echo "== 2/2 clean pair: packing ($(date '+%T'))"
apptainer exec --containall --bind "$W":/w "$SIF" tar --format=posix -cf /w/eval-pair.tar.new --exclude=wine/.git --exclude=wine-build/.eval_snapshot --exclude=wine-build/.eval.lock -C /w wine wine-build
echo "   testing the tarball: two copies, one Wine test ($(date '+%T'))"
apptainer exec --containall --pwd "$WA" --bind "$PROJ" --bind "$W/eval-pair.tar.new":/pack/eval-pair.tar:ro --bind "$LOCAL/c":/w \
    --env "TMPDIR=/w/tmp,XDG_CACHE_HOME=/w/cache,PYTHONUNBUFFERED=1" "$SIF" bash -c '
    set -e; bash ../vulcan/unpack_eval_trees.sh /pack/eval-pair.tar 2
    python scripts/evaluate.py --src /w/wine --build /w/wine-build --scenario 3.1 --stage mini_swe --baseline --ids 0001 \
        --workers 2 --jobs 2 --prefix /w/pfx/wine --runs /w/smoke-runs
    cat /w/smoke-runs/baseline/*.json | head -12
    grep -q "\"status\": \"ok\"" /w/smoke-runs/baseline/*.json || { echo "the Wine test did not run to its summary line"; exit 1; }'
mv "$W/eval-pair.tar.new" "$W/eval-pair.tar"
{ echo "packed $(date '+%F %T') by job $SLURM_JOB_ID, image $IMG"; ls -l "$W/eval-pair.tar"; } > "$W/eval-pair.info"; cat "$W/eval-pair.info"
echo "PACK-OK ($(date '+%T'))"
