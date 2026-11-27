#!/usr/bin/env bash
# run_api_local.sh - ONE agent setting of a COMMERCIAL model on a workstation, for a vendor the cluster's proxy refuses
# (api.deepseek.com: 403 from the compute nodes, see run_api.sbatch).  It is the agent branch of vulcan/run_api.sbatch
# without Slurm: the same container image, the same packed restricted trees, the same runner call, the same limits.
#
#   cd .../winebench                                              (the repository root)
#   N=3 bash vulcan/run_api_local.sh deepseek-v4-flash 2.2 mini_swe     # a trial: the first 3 tasks
#   bash vulcan/run_api_local.sh deepseek-v4-flash 2.2 mini_swe         # the setting (205 tasks); run it again to continue
#   bash vulcan/run_api_local.sh deepseek-v4-flash 2.2 openhands
#
# What must be on this machine (copied from Vulcan, NOT rebuilt here - the results are only comparable with the other
# models if the image and the trees are the very same files):
#   SIF   container/wine-agent.sif                  <- .../WineBench/container/wine-agent.sif
#   PACK  ~/winebench-pack/swe-pair.tar             <- ~/scratch/winebench-w/swe-pair.tar   (Wine 11.19, restricted pair)
#   apptainer (sudo add-apt-repository -y ppa:apptainer/ppa && sudo apt install -y apptainer)
#   the key: ~/.config/winebench/secrets.toml, chmod 600 (form: wine_bench/secrets.toml.example), or WB_SECRETS_FILE=...
#   the prompts of the setting: zstd -dc --long=27 runs_archive/agent_<S>_<harness>_prompts.tar.zst | tar -xf -
#
# LOCAL (default ~/wb-local) is the scratch directory the trees are unpacked into, one pair per worker, on a Linux file
# system (not NTFS / exFAT: the trees need symlinks and exec bits).  It is emptied and filled again by every run.
#
# Differences from the cluster runs, to be reported with the results:
#   - hardware: this machine's CPUs (the 1800 s per task include the compile times);
#   - network: on Vulcan the agent's shell has no route out at all.  This machine is online, so the runners' switch
#     WB_AGENT_OFFLINE=1 (bench/swe.py, on by default here) gives the agent's shell a proxy that does not exist: curl,
#     wget, pip, git and Python's urllib fail, the model calls are not affected.  It is not a firewall - a program that
#     ignores the proxy variables still gets out - so every command stays recorded (a "network" violation in <id>.json
#     for curl / wget / pip / git clone / apt) and this script counts them at the end.
#     Before the run the switch is TESTED in the container: a command of the agent's shell, run through sh and through
#     bash, must not reach the vendor.  (The cluster's BASH_ENV file, which unsets the proxy variables in every bash, would
#     undo the switch for everything started through bash while the results still said "dead_proxy": here that file
#     sets the dead proxy instead.)  WB_AGENT_OFFLINE=0 switches all of this off.
# Tunable: N (first N tasks), AGENT_WORKERS (default 4), GEN_ATTEMPTS (2, as on the cluster), JOBS (make -j per compile).
set -e
NAME=${1:?model (entry of wine_agent/scenarios/models.toml), e.g. deepseek-v4-flash}; S=${2:?scenario: 2.1 | 2.2}; H=${3:?harness: mini_swe | openhands}
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd); PKG=$ROOT/wine_agent
SIF=${SIF:-$ROOT/container/wine-agent.sif}; PACK=${PACK:-$HOME/winebench-pack/swe-pair.tar}
SECRETS=${WB_SECRETS_FILE:-$HOME/.config/winebench/secrets.toml}; LOCAL=${LOCAL:-$HOME/wb-local}
N=${N:-100000}; GEN_ATTEMPTS=${GEN_ATTEMPTS:-2}; AGENT_WORKERS=${AGENT_WORKERS:-4}; OFFLINE=${WB_AGENT_OFFLINE:-1}
case "$H" in mini_swe|openhands) ;; *) echo "harness must be mini_swe or openhands"; exit 1;; esac
command -v apptainer >/dev/null || { echo "apptainer is not installed (see the head of this script)"; exit 1; }
[ -f "$SIF" ] || { echo "$SIF: no container image - copy container/wine-agent.sif from Vulcan (or SIF=...)"; exit 1; }
[ -f "$PACK" ] || { echo "$PACK: no packed trees - copy ~/scratch/winebench-w/swe-pair.tar from Vulcan (or PACK=...)"; exit 1; }
[ -f "$SECRETS" ] || { echo "$SECRETS: no key file (copy wine_bench/secrets.toml.example there, fill in the key, chmod 600)"; exit 1; }
[ "$(stat -c %a "$SECRETS")" = 600 ] || { echo "$SECRETS must be readable by you only: chmod 600 $SECRETS"; exit 1; }
[ -f "$PKG/scripts/run_$H.py" ] || { echo "$PKG/scripts/run_$H.py is missing: is this the repository?"; exit 1; }
grep -qE "^name *= *\"$NAME\"" "$PKG/scenarios/models.toml" || { echo "$NAME: not in $PKG/scenarios/models.toml"; exit 1; }
[ "$OFFLINE" != 1 ] || grep -q WB_AGENT_OFFLINE "$PKG/scripts/bench/swe.py" || { echo "this checkout has no WB_AGENT_OFFLINE switch (commit 6aebc5d or later): git -C $ROOT pull"; exit 1; }
cd "$PKG"; SD="runs/scenario$S/$H"; OUT="$SD/responses/$NAME"; mkdir -p vulcan/logs "$SD/jobs"
[ -n "$(ls "$SD/prompts" 2>/dev/null | grep -E '^[0-9]{4}\.json$' | head -1)" ] || {
    echo "$PKG/$SD/prompts: no prompts.  Unpack the ones the other models got (in $ROOT):"
    echo "    zstd -dc --long=27 runs_archive/agent_${S}_${H}_prompts.tar.zst | tar -xf -"; exit 1; }
case "$(stat -f -c %T "$(mkdir -p "$LOCAL" && echo "$LOCAL")")" in
    fuseblk|ntfs*|exfat|vfat|msdos) echo "$LOCAL is on a Windows file system: set LOCAL to a directory on ext4 / xfs / btrfs"; exit 1;; esac
exec 9> "$LOCAL/.lock"; flock -n 9 || { echo "$LOCAL is in use by another run of this script: wait for it, or give this one its own LOCAL=..."; exit 1; }
JOB="local-$(date +%Y%m%d-%H%M%S)"; LOG="vulcan/logs/wb-$S-$H-$NAME-$JOB.out"
exec > >(tee -a "$LOG") 2>&1
T0=$SECONDS; CPUS=$(nproc); JOBS=${JOBS:-$(( CPUS / AGENT_WORKERS ))}; [ "$JOBS" -lt 2 ] && JOBS=2
count_done() {                                                                       # -> "<tasks with a result> <tasks wanted>"
    local c p
    c=$(ls "$OUT" 2>/dev/null | grep -cE '^[0-9]{4}\.json$' || true); p=$(ls "$SD/prompts" 2>/dev/null | grep -cE '^[0-9]{4}\.json$' || true)
    [ "$p" -gt "$N" ] && p=$N; [ "$c" -gt "$p" ] && c=$p; echo "$c $p"
}
jobline() { printf '{"job": "%s", "event": "%s", "time": "%s", "model": "%s", "scenario": "%s", "harness": "%s", %s}\n' "$JOB" "$1" "$(date '+%F %T')" "$NAME" "$S" "$H" "$2" >> "$SD/jobs/$NAME.jsonl"; }
read DONE0 TOTAL < <(count_done)
echo "setting: API model $NAME, scenario $S, harness $H; at most $GEN_ATTEMPTS generations per task; run $JOB on $(hostname) (NOT a cluster job)"
echo "progress at start: $DONE0 / $TOTAL tasks; $CPUS CPUs, $AGENT_WORKERS tasks in parallel, make -j$JOBS; trees in $LOCAL: $(df -h --output=avail "$LOCAL" | tail -1 | tr -d ' ') free"
if [ "$DONE0" -ge "$TOTAL" ]; then echo "nothing left to do for this setting"; exit 0; fi
IMG=$(sha256sum "$SIF" | cut -c1-16); echo "image $IMG (must be the one of the cluster runs: compare with \"image\" in the other models' $SD/jobs/*.jsonl)"
jobline start "\"node\": \"$(hostname)\", \"site\": \"workstation\", \"agent_offline\": \"$OFFLINE\", \"gpus\": 0, \"cpus\": $CPUS, \"mem_mb\": $(awk '/MemTotal/ {print int($2 / 1024)}' /proc/meminfo), \"time_limit\": \"none\", \"workers\": $AGENT_WORKERS, \"gen_attempts\": $GEN_ATTEMPTS, \"image\": \"$IMG\", \"done_at_start\": $DONE0, \"tasks\": $TOTAL"

wipe() { find "$LOCAL" -mindepth 1 -maxdepth 1 ! -name .lock -exec chmod -R u+rwX {} + 2>/dev/null; find "$LOCAL" -mindepth 1 -maxdepth 1 ! -name .lock -exec rm -rf {} +; }
wipe                                                                   # a fresh start, as every cluster job has
mkdir -p "$LOCAL/tmp"
# BASH_ENV: read by every non-interactive bash the agent starts.  On the cluster it unsets the proxy variables; with the
# dead-proxy switch it must set them, or `bash -c "curl ..."` would have a direct connection again
if [ "$OFFLINE" = 1 ]; then echo 'export http_proxy=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9 HTTP_PROXY=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9 all_proxy=http://127.0.0.1:9 ALL_PROXY=http://127.0.0.1:9 no_proxy= NO_PROXY=' > "$LOCAL/noproxy.sh"
else echo 'unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY' > "$LOCAL/noproxy.sh"; fi
CENV="LITELLM_LOCAL_MODEL_COST_MAP=True,MSWEA_SILENT_STARTUP=1,MSWEA_COST_TRACKING=ignore_errors,OPENHANDS_SUPPRESS_BANNER=1,TMPDIR=/t/tmp,PYTHONUNBUFFERED=1,PYTHONDONTWRITEBYTECODE=1,WB_JOB_ID=$JOB,WB_SECRETS=/secrets.toml,BASH_ENV=/t/noproxy.sh,WB_AGENT_OFFLINE=$OFFLINE"
PROXY=(); [ -n "$https_proxy" ] && PROXY=(--env "https_proxy=$https_proxy" --env "http_proxy=$http_proxy" --env "HTTPS_PROXY=$https_proxy" --env "HTTP_PROXY=$http_proxy")

if [ "$OFFLINE" = 1 ]; then
    echo "== network check in the container: the agent's shell must NOT reach the vendor, the runner must"
    apptainer exec --containall --pwd "$PKG" --bind "$PKG" --bind "$LOCAL":/t --env "$CENV" "${PROXY[@]}" "$SIF" python - "$NAME" "$S" <<'PYEOF' || { echo "NETWORK CHECK FAILED: not starting.  (WB_AGENT_OFFLINE=0 runs without the switch - then say so with the results.)"; jobline end "\"result\": \"network check failed\""; exit 1; }
import os, subprocess, sys, urllib.request, urllib.error
sys.path.insert(0, 'scripts'); from bench import swe
from bench.config import load_scenario
URL = next(m['base_url'] for m in load_scenario(sys.argv[2]).models if m['name'] == sys.argv[1])      # the vendor's endpoint
mode = swe.agent_network(); env = {**os.environ, **swe.offline_env()}; bad = mode != 'dead_proxy'
print(f'  agent_network = {mode}')
for shell in ('sh -c', 'bash -c'):
    v = subprocess.run(f"{shell} 'echo $https_proxy'", shell=True, env=env, capture_output=True, text=True).stdout.strip()
    rc = subprocess.run(f"{shell} 'curl -sS -m 10 -o /dev/null {URL}'", shell=True, env=env, capture_output=True, text=True).returncode
    print(f'  agent command through {shell:8}: https_proxy = {v or "<unset>"}; curl {URL}: {"fails (as it must)" if rc else "WORKS - the agent is online"}')
    bad = bad or rc == 0
try: urllib.request.urlopen(URL, timeout=20); ok = True
except urllib.error.HTTPError: ok = True                              # an HTTP answer of any kind: the host was reached
except Exception as e: ok = False; print(f'  the runner itself cannot reach {URL}: {type(e).__name__}: {e}')
print(f'  runner process (the model calls): {"reaches the vendor" if ok else "NO CONNECTION"}')
sys.exit(1 if bad or not ok else 0)
PYEOF
else echo "== WB_AGENT_OFFLINE=0: the agent's shell has this machine's network (results will say agent_network = unchanged)"; fi

echo "== unpacking $AGENT_WORKERS fresh tree pairs ($(date '+%T'))"
apptainer exec --containall --pwd "$PKG" --bind "$PKG" --bind "$PACK":/pack/swe-pair.tar:ro --bind "$LOCAL":/t --env "TMPDIR=/t/tmp" \
    "$SIF" bash scripts/unpack_swe_trees.sh /pack/swe-pair.tar "$AGENT_WORKERS" || { jobline end "\"result\": \"trees could not be unpacked\""; exit 1; }
echo "trees ready after $((SECONDS - T0)) s"
echo "===== $H, scenario $S, model $NAME, $AGENT_WORKERS tasks in parallel (make -j$JOBS each) ($(date '+%F %T'))"
RC=0
apptainer exec --containall --pwd "$PKG" --bind "$PKG" --bind "$LOCAL":/t --bind "$SECRETS":/secrets.toml:ro --env "$CENV" "${PROXY[@]}" "$SIF" \
    python "scripts/run_$H.py" --scenario "$S" --limit "$N" --models "$NAME" --workers "$AGENT_WORKERS" --jobs "$JOBS" \
    --src /t/wine-swe --build /t/wine-build-swe --gen-attempts "$GEN_ATTEMPTS" || { RC=$?; echo "run_$H.py stopped (status $RC)"; }

read DONE1 TOTAL < <(count_done)
FAILED=$(grep -ls '"generation_failed": true' "$OUT"/[0-9][0-9][0-9][0-9].json 2>/dev/null | wc -l); RETRIED=$(ls "$OUT" 2>/dev/null | grep -cE '^[0-9]{4}\.attempt[0-9]+\.json$' || true)
NET=$(grep -ls '"rule": "network"' "$OUT"/[0-9][0-9][0-9][0-9].json 2>/dev/null | wc -l)
echo "progress: $DONE0 -> $DONE1 / $TOTAL tasks in $(( (SECONDS - T0) / 60 )) min ($(date '+%F %T')); second attempts so far: $RETRIED; generation failed: $FAILED"
echo "tasks in which the agent typed a network command (curl / wget / pip / git clone / apt): $NET  - to be looked at before the results are used"
echo "agent_network recorded in the results: $(grep -hos '"agent_network": "[a-z_]*"' "$OUT"/[0-9][0-9][0-9][0-9].json | sort | uniq -c | tr -s ' ' | tr '\n' ';')"
jobline end "\"result\": \"ok\", \"runner_status\": $RC, \"done_at_end\": $DONE1, \"tasks\": $TOTAL, \"second_attempts\": $RETRIED, \"generation_failed\": $FAILED, \"network_command_tasks\": $NET, \"minutes\": $(( (SECONDS - T0) / 60 )), \"successor\": \"\""
if [ "$DONE1" -ge "$TOTAL" ]; then echo "SETTING COMPLETE: $PKG/$OUT/  (evaluate it on Vulcan: copy this folder and $SD/jobs/$NAME.jsonl there)"
else echo "tasks left: run the same command again to continue"; fi
wipe 2>/dev/null || true
