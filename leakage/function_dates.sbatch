#!/bin/bash
#SBATCH --job-name=wb-fdates
#SBATCH --account=aip-zhouyang
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --time=3:00:00
#SBATCH --output=vulcan/logs/%x-%j.out
# function_dates.sbatch - date the implementation of every WineBench function (leakage/function_dates.py).
#   cd .../WineBench && sbatch leakage/function_dates.sbatch
# Needs the full history of Wine: cloned once from the GitHub mirror (the cluster's proxy does not let gitlab.winehq.org
# through) into ~/scratch/winebench-w/wine-history.git, a bare repository next to the shallow tree the builds use.
type module >/dev/null 2>&1 || source /cvmfs/soft.computecanada.ca/config/profile/bash.sh
module load StdEnv/2023 python/3.12.4
H=$HOME/scratch/winebench-w/wine-history.git
if [ ! -d "$H" ]; then
    echo "== cloning the history ($(date '+%T'))"; git clone --bare --quiet https://github.com/wine-mirror/wine.git "$H.tmp" && mv "$H.tmp" "$H" || { echo "clone failed"; exit 1; }
fi
echo "history: $(git --git-dir "$H" rev-list --count wine-11.19) commits up to wine-11.19 = $(git --git-dir "$H" rev-parse --short 'wine-11.19^{commit}') ($(git --git-dir "$H" log -1 --format=%cs wine-11.19)); size $(du -sh "$H" | cut -f1)"
[ "$(git --git-dir "$H" rev-parse 'wine-11.19^{commit}' | cut -c1-8)" = 455e3509 ] || { echo "wine-11.19 is not commit 455e3509 in this clone"; exit 1; }
cd "${SLURM_SUBMIT_DIR:-$PWD}" && python3 leakage/function_dates.py --git "$H" --workers "${SLURM_CPUS_PER_TASK:-8}" "$@"
