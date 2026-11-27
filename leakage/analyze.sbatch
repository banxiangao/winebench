#!/bin/bash
# analyze.sbatch - leakage/analyze.py as a job (no Python on the login node).   sbatch leakage/analyze.sbatch
#SBATCH --job-name=wb-leak-an
#SBATCH --account=aip-zhouyang
#SBATCH --cpus-per-task=1
#SBATCH --mem=1G
#SBATCH --time=0:15:00
#SBATCH --output=/scratch/%u/wb-tmp/leak/an-%j.out
type module >/dev/null 2>&1 || source /cvmfs/soft.computecanada.ca/config/profile/bash.sh
module load StdEnv/2023 python/3.12.4
cd "${WB_ROOT:-/project/aip-zhouyang/xingan1/WineBench}"
python3 leakage/analyze.py "$@"
