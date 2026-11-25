#!/bin/bash
# winetest.sh - tiny experiment (about 2 minutes, CPU only): does the built Wine run its own tests inside the container on a
# compute node?  Nothing is modified: the clean tree is mounted read-only, the Wine prefix lives on the node-local disk.
#   salloc --account=aip-zhouyang --cpus-per-task=4 --mem=8G --time=0:15:00 srun bash vulcan/winetest.sh
source /cvmfs/soft.computecanada.ca/config/profile/bash.sh 2>/dev/null; module load apptainer
L=${SLURM_TMPDIR:-/tmp}/wb-winetest-$SLURM_JOB_ID; mkdir -p "$L/tmp" "$L/cache"; trap 'rm -rf "$L"' EXIT
echo "node $(hostname); SLURM_TMPDIR=$SLURM_TMPDIR; local disk: $(df -h --output=fstype,size,avail "$L" | tail -1 | tr -s ' ')"
apptainer exec --containall --bind /scratch/xingan1/winebench-w:/w:ro --bind "$L":/l --env "TMPDIR=/l/tmp,XDG_CACHE_HOME=/l/cache,WINEPREFIX=/l/pfx,WINEDEBUG=-all,WINEDLLOVERRIDES=mscoree,mshtml=" \
  /project/aip-zhouyang/xingan1/WineBench/container/wine-agent.sif bash -c '
    Xvfb :77 -screen 0 1280x1024x24 -nolisten tcp >/l/xvfb.log 2>&1 & XP=$!; sleep 2; export DISPLAY=:77
    kill -0 $XP 2>/dev/null && echo "Xvfb: running" || { echo "Xvfb: FAILED"; cat /l/xvfb.log; }
    cd /w/wine-build
    t0=$SECONDS; timeout 600 ./wine wineboot -u; echo "wineboot rc=$? ($((SECONDS - t0)) s)"; timeout 120 server/wineserver -w; echo "wineserver -w rc=$?"
    ls /l/pfx | head -5
    timeout 60 ./wine cmd /c echo hello-from-wine; echo "cmd rc=$?"
    export WINEDEBUG=
    t0=$SECONDS; timeout 300 ./wine dlls/kernelbase/tests/x86_64-windows/kernelbase_test.exe path 2>&1 | tail -4; echo "kernelbase path test: rc=${PIPESTATUS[0]} ($((SECONDS - t0)) s)"
    timeout 300 ./wine dlls/user32/tests/x86_64-windows/user32_test.exe text 2>&1 | tail -2; echo "user32 text test (needs the display): rc=${PIPESTATUS[0]}"
    server/wineserver -k; kill $XP 2>/dev/null; true'
