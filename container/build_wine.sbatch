#!/usr/bin/env bash
#SBATCH --job-name=wine-build
#SBATCH --cpus-per-task=16
#SBATCH --mem=48G
#SBATCH --time=3:00:00
#SBATCH --output=container/wine-build-%j.out
#SBATCH --account=aip-zhouyang
# builds the Wine checked out in ~/scratch/winebench-w/wine (x86_64) inside the container: source /w/wine, build /w/wine-build
# (/w = ~/scratch/winebench-w; Wine 11.19 since 2026-11-24, the 11.18 of the pilot runs is ~/scratch/winebench-w-11.18)
type module >/dev/null 2>&1 || source /cvmfs/soft.computecanada.ca/config/profile/bash.sh
module load apptainer
W=$(realpath ~/scratch/winebench-w)
apptainer exec --bind "$W":/w container/wine-agent.sif bash -c '
    set -e; mkdir -p /w/wine-build; cd /w/wine-build
    [ -f Makefile ] || /w/wine/configure --enable-archs=x86_64 > configure.log 2>&1 || { tail -20 configure.log; exit 1; }
    grep -i "warning: " configure.log | sed "s/^/   /" || true
    echo "== make -j'"$SLURM_CPUS_PER_TASK"'"
    make -j'"$SLURM_CPUS_PER_TASK"' > build.log 2>&1 || { tail -30 build.log; exit 1; }
    ls -l /w/wine-build/wine; du -sh /w/wine /w/wine-build; echo BUILD-OK'
