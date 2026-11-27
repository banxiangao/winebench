#!/usr/bin/env bash
# submit_api.sh - submit ONE setting of a commercial (API) model: vulcan/run_api.sbatch with the right directory,
# resources and job name.  CPU only.  See run_api.sbatch for keys, network, the two-attempt rule and recovery.
#
#   cd .../WineBench
#   bash vulcan/submit_api.sh probe                                   # are the keys valid, which model ids are served
#   bash vulcan/submit_api.sh claude-haiku-5-5 1.1                    # one-shot  (scenario 1.1 | 1.2)
#   bash vulcan/submit_api.sh claude-haiku-5-5 2.2 mini_swe           # agent     (harness mini_swe | openhands)
#   N=5 CHAIN=0 bash vulcan/submit_api.sh openai-gpt-6-luna 2.2 openhands --time=0:40:00      # a trial: first 5 tasks
#   bash vulcan/submit_api.sh list                                    # generated / evaluated per API setting
#
# Resources (sbatch options after the names override them):
#   one-shot   1 CPU,  2 G, 1:00   - 205 requests, 4 at a time; the job only waits for the API
#   agent     12 CPUs, 32 G, 3:00  - 6 tasks at a time, each with its own tree pair on the node's local disk and
#                                    make -j2 for ./compile (the local-model agent jobs measured ~19 G next to vLLM)
# Jobs: wb-<scenario>-<harness>-<model> generates; when the setting is complete it submits
# wb-eval-<scenario>-<harness>-<model>, which compiles and tests the code (vulcan/eval_setting.sbatch).
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
API_MODELS=${API_MODELS:-"claude-haiku-5-5 openai-gpt-6-luna deepseek-v4-flash"}
if [ "${1:-}" = probe ]; then
    shift; cd "$ROOT/wine_bench"; mkdir -p vulcan/logs
    exec sbatch --job-name=wb-api-probe --cpus-per-task=1 --mem=2G --time=0:10:00 "$@" "$ROOT/vulcan/run_api.sbatch" probe
fi
if [ "${1:-}" = list ]; then
    Q=$(squeue -u "$USER" -h -o "%j %i %T" 2>/dev/null || true)
    printf '%-9s %-10s %-20s %-10s %-10s %-8s %-7s %s\n' scenario harness model generated evaluated retried failed "jobs in the queue"
    for row in "1.1 oneshot" "1.2 oneshot" "2.2 mini_swe" "2.2 openhands" "2.1 mini_swe" "2.1 openhands"; do
        set -- $row; S=$1; H=$2
        for M in $API_MODELS; do
            if [ "$H" = oneshot ]; then SD="$ROOT/wine_bench/runs/scenario$S/programmer"; else SD="$ROOT/wine_agent/runs/scenario$S/$H"; fi
            [ -d "$SD/responses/$M" ] || continue
            p=$(ls "$SD/prompts" 2>/dev/null | grep -cE '^[0-9]{4}\.json$' || true)
            c=$(ls "$SD/responses/$M" | grep -cE '^[0-9]{4}\.json$' || true); e=$(ls "$SD/eval/$M" 2>/dev/null | grep -cE '^[0-9]{4}\.json$' || true)
            r=$(ls "$SD/responses/$M" | grep -cE '^[0-9]{4}\.attempt[0-9]+\.json$' || true)
            f=$(grep -ls '"generation_failed": true' "$SD/responses/$M"/[0-9][0-9][0-9][0-9].json 2>/dev/null | wc -l)
            jobs=$(echo "$Q" | awk -v n="wb-$S-$H-$M" -v e="wb-eval-$S-$H-$M" '$1 == n {printf "gen %s(%s) ", $2, $3} $1 == e {printf "eval %s(%s) ", $2, $3}')
            printf '%-9s %-10s %-20s %-10s %-10s %-8s %-7s %s\n' "$S" "$H" "$M" "$c/$p" "$e/$p" "$r" "$f" "$jobs"
        done
    done
    exit 0
fi
M=${1:?model (claude-haiku-5-5 | openai-gpt-6-luna | deepseek-v4-flash), or: probe | list}; S=${2:?scenario: 1.1 | 1.2 | 2.2}; shift 2
H=oneshot; if [ $# -gt 0 ] && [ "${1#-}" = "$1" ]; then H=$1; shift; fi
case "$H" in
    oneshot)            PKG="$ROOT/wine_bench"; RES=(--cpus-per-task=1 --mem=2G --time=1:00:00) ;;
    mini_swe|openhands) PKG="$ROOT/wine_agent"; RES=(--cpus-per-task=12 --mem=32G --time=3:00:00) ;;
    *) echo "harness: mini_swe | openhands (none for one-shot)"; exit 1 ;;
esac
[ -f "$PKG/scenarios/scenario$S/config.toml" ] || { echo "no scenario $S in $PKG"; exit 1; }
grep -qE "^name *= *\"$M\"" "$PKG/scenarios/models.toml" || { echo "$M: not in $PKG/scenarios/models.toml"; exit 1; }
cd "$PKG"; mkdir -p vulcan/logs
sbatch --job-name="wb-$S-$H-$M" "${RES[@]}" "$@" "$ROOT/vulcan/run_api.sbatch" "$M" "$S" "$H"
