#!/bin/bash
#SBATCH --job-name=wb-metrics
#SBATCH --account=aip-zhouyang
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=0:15:00
#SBATCH --output=vulcan/logs/%x-%j.out
# metrics.sbatch - (re)write results/metrics_tasks.csv, metrics_settings.csv/.txt (vulcan/metrics.py) and the Slurm
# accounting of every job of the experiment (results/jobs_usage.txt).   cd .../WineBench && sbatch vulcan/metrics.sbatch
ROOT=$(realpath "${SLURM_SUBMIT_DIR:-$PWD}")
type module >/dev/null 2>&1 || source /cvmfs/soft.computecanada.ca/config/profile/bash.sh
module load apptainer
apptainer exec --containall --pwd "$ROOT" --bind "$ROOT" "$ROOT/container/wine-agent.sif" python vulcan/metrics.py
ids=$(cat "$ROOT"/wine_*/runs/scenario*/*/jobs/*.jsonl 2>/dev/null | grep -o '"job": "[0-9]*"' | grep -o '[0-9]*' | sort -un | paste -sd,)
[ -n "$ids" ] && sacct -j "$ids" -X -P -o JobID,JobName,State,Start,End,Elapsed,AllocCPUS,ReqMem,AllocTRES,CPUTimeRAW > "$ROOT/results/jobs_usage.txt.new" && mv "$ROOT/results/jobs_usage.txt.new" "$ROOT/results/jobs_usage.txt"
cat "$ROOT/results/metrics_settings.txt"
