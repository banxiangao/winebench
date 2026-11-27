#!/bin/bash
#SBATCH --job-name=wb-leak-prompts
#SBATCH --account=aip-zhouyang
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=0:15:00
#SBATCH --output=vulcan/logs/%x-%j.out
# build_prompts.sbatch - the prompts of every scenario of the leakage experiment (the agent jobs would build theirs on
# start; the one-shot sampling jobs need them beforehand).   cd .../WineBench && sbatch leakage/build_prompts.sbatch
type module >/dev/null 2>&1 || source /cvmfs/soft.computecanada.ca/config/profile/bash.sh
module load apptainer
R=$(realpath "${SLURM_SUBMIT_DIR:-$PWD}"); SIF=$R/container/wine-agent.sif
py() { apptainer exec --containall --pwd "$1" --bind "$R" --env "PYTHONDONTWRITEBYTECODE=1" "$SIF" python "${@:2}"; }
for g in new old; do
    for s in 1.1 1.2; do py "$R/wine_bench" scripts/build_prompts.py --scenario "$s-$g" --stage programmer | tail -1; done
    for s in 2.1 2.2; do for h in mini_swe openhands; do py "$R/wine_agent" scripts/build_prompts.py --scenario "$s-$g" --stage "$h" | tail -1; done; done
done
