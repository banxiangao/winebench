#!/usr/bin/env bash
# LEGACY: written for the earlier two-stage design (architect -> programmer).  Scenario numbers in the comments below are
# those of that design, not the current scenarios 1.1 / 1.2 (one-shot) and 2.1 / 2.2 (agent).  Not used by the Vulcan jobs.
# run_all.sh - the whole benchmark for every enabled model in scenarios/models.toml:
#   1.1 architect -> 1.1 programmer (each model implements its OWN specs)
#   1.2 architect -> 1.2 programmer (same)
#   2.1 programmer (from the Microsoft docs)
# Everything is resumable: replies that already exist are skipped, so re-running this script only fills the gaps.
#
#   bash scripts/run_all.sh                       # all enabled models
#   bash scripts/run_all.sh claude-haiku-5-5      # one model (or a comma-separated list)
#   LIMIT=5 bash scripts/run_all.sh               # trial: first 5 records of every stage
set -e
cd "$(dirname "$0")/.."
PY=${PY:-python3}                                 # e.g. PY=~/wine_fuzz/venv/bin/python
[ -n "$LIMIT" ] && LIM="--limit $LIMIT" || LIM=""

# enabled models with a key (same rule as run_llm.py)
MODELS=${1:-$($PY - <<'EOF'
import sys; sys.path.insert(0, 'scripts')
from bench.config import load_scenario
from bench import llm
scn = load_scenario('1.1'); llm.SECRETS = scn.secrets()
print(','.join(m['name'] for m in scn.models if not llm.usable(m)))
EOF
)}
echo "models: $MODELS"

run() {  # run <models> <scenario> <stage> [--from-model X] : query, then re-query the bad ones once
    $PY scripts/run_llm.py --scenario "$2" --stage "$3" --models "$1" $LIM "${@:4}"
    $PY scripts/run_llm.py --scenario "$2" --stage "$3" --models "$1" $LIM "${@:4}" --redo-bad
}

echo "===== 1.1 architect";  run "$MODELS" 1.1 architect
echo "===== 1.2 architect";  run "$MODELS" 1.2 architect

for M in ${MODELS//,/ }; do
    for S in 1.1 1.2; do
        echo "===== $S programmer, specs by $M"
        $PY scripts/build_prompts.py --scenario $S --stage programmer --from-model "$M" $LIM
        run "$M" $S programmer --from-model "$M"
    done
done

echo "===== 2.1 programmer";  run "$MODELS" 2.1 programmer

$PY scripts/summary_table.py
