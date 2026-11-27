#!/bin/bash
#SBATCH --job-name=wb-leak-old
#SBATCH --account=aip-zhouyang
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=0:30:00
#SBATCH --output=vulcan/logs/%x-%j.out
# prepare_old.sbatch - after the NEW candidates were built and their tests run on the clean tree: mark the usable ones,
# match OLD functions to them and fetch the documentation pages of those.   cd .../WineBench && sbatch leakage/prepare_old.sbatch
# With the argument "check-old": only mark the usable OLD candidates (after their records and baselines exist).
type module >/dev/null 2>&1 || source /cvmfs/soft.computecanada.ca/config/profile/bash.sh
module load StdEnv/2023 python/3.12.4
cd "${SLURM_SUBMIT_DIR:-$PWD}"
if [ "${1:-}" = check-old ]; then python3 leakage/check_candidates.py leakage/candidates/old; exit; fi
python3 leakage/check_candidates.py leakage/candidates/new && python3 leakage/match_old.py && bash leakage/fetch_docs.sh leakage/old_doc_pages.tsv leakage/msdocs
