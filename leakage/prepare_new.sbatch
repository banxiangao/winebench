#!/bin/bash
#SBATCH --job-name=wb-leak-new
#SBATCH --account=aip-zhouyang
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=0:30:00
#SBATCH --output=vulcan/logs/%x-%j.out
# prepare_new.sbatch - the NEW candidates of the leakage experiment and their documentation pages.
#   cd .../WineBench && sbatch leakage/prepare_new.sbatch
type module >/dev/null 2>&1 || source /cvmfs/soft.computecanada.ca/config/profile/bash.sh
module load StdEnv/2023 python/3.12.4
cd "${SLURM_SUBMIT_DIR:-$PWD}" && python3 leakage/select_new.py "$@" && bash leakage/fetch_docs.sh leakage/new_doc_pages.tsv leakage/msdocs
