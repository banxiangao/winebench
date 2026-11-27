#!/bin/bash
#SBATCH --job-name=wb-figures
#SBATCH --account=aip-zhouyang
#SBATCH --cpus-per-task=1
#SBATCH --mem=3G
#SBATCH --time=0:10:00
#SBATCH --output=vulcan/logs/%x-%j.out
# make_figures.sbatch - draw figures/*.pdf|png|svg from results/metrics_settings.csv.   cd .../WineBench && sbatch figures/make_figures.sbatch
type module >/dev/null 2>&1 || source /cvmfs/soft.computecanada.ca/config/profile/bash.sh
module load StdEnv/2023 python/3.12.4 scipy-stack/2025a
export MPLCONFIGDIR=${SLURM_TMPDIR:-/tmp}/mpl
cd "${SLURM_SUBMIT_DIR:-$PWD}" && python3 figures/make_figures.py && python3 figures/make_leakage_figure.py && python3 figures/make_venn_figures.py
