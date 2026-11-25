#!/bin/bash
#SBATCH --job-name=wb-dataset
#SBATCH --account=aip-zhouyang
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=1:00:00
#SBATCH --output=vulcan/logs/%x-%j.out
# build_dataset.sbatch - rebuild the WineBench subset dataset (one JSON per function, wine500_doc format) on Vulcan from
# the subset list, with the subset's own script (build_subset_dataset.py -> wine_bench/scripts/build_benchmark.py, libclang):
#   function list   incoming/<IN>/winebench/subset/winebench_subset.json
#   doc pages       incoming/<IN>/winebench/subset/subset_docs_cache.json (no network), index full/msdocs_index.csv
#   Wine            ~/scratch/winebench-w/wine + wine-build (container/build_wine.sbatch; the real build has every generated header)
#   libclang        the PyPI wheel unpacked in ~/scratch/pydeps/libclang (the container has none)
# Output: wine_bench/dataset/<OUT>/ (existing records are skipped; FORCE=1 redoes them).
# Other function lists: SUBSET=<json in the same format> MSDOCS=<dir with <repo>/<path> doc pages not in the cache> OUT=<new dir>.
#
#   cd .../WineBench && sbatch vulcan/build_dataset.sbatch
set -e
ROOT=$(realpath "${SLURM_SUBMIT_DIR:-$PWD}"); SIF=$ROOT/container/wine-agent.sif
IN=${IN:-$ROOT/incoming/winebench_2026-11-24/winebench}; OUT=${OUT:-$ROOT/wine_bench/dataset/winebench205_doc}
W=$(realpath ~/scratch/winebench-w); CL=$(realpath ~/scratch/pydeps/libclang/libclang-18.1.1.data/platlib)
[ -e "$W/wine-build/wine" ] || { echo "$W/wine-build: Wine is not built"; exit 1; }
[ -f "$CL/clang/native/libclang.so" ] || { echo "$CL: no libclang"; exit 1; }
type module >/dev/null 2>&1 || { set +e; source /cvmfs/soft.computecanada.ca/config/profile/bash.sh; set -e; }
module load apptainer
cd "$ROOT"; mkdir -p "$OUT"
echo "Wine: $(cat "$W/wine/VERSION"), $(git -C "$W/wine" log -1 --format=%h); output $OUT"
apptainer exec --containall --pwd "$ROOT" --bind "$ROOT" --bind "$W":/w:ro --bind "$CL":/clang:ro --env "PYTHONPATH=/clang,PYTHONUNBUFFERED=1" "$SIF" \
    python "$IN/scripts/build_subset_dataset.py" --subset "${SUBSET:-$IN/subset/winebench_subset.json}" --src /w/wine --build /w/wine-build \
    --scripts "$ROOT/wine_bench/scripts" --docs-index "$IN/full/msdocs_index.csv" --docs-cache "$IN/subset/subset_docs_cache.json" \
    ${MSDOCS:+--msdocs "$MSDOCS"} --out "$OUT" ${FORCE:+--force}
echo "records: $(ls "$OUT" | grep -cE '^[0-9]{4}_.*\.json$'); doc pages: $(ls "$OUT/docs" | wc -l)"
