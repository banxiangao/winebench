#!/usr/bin/env bash
# redo_model.sh - re-query one model's bad replies (errors / truncated / bad format) of one scenario stage until
# nothing is left or nothing improves.  Low parallelism, for vendors with tight rate limits (HTTP 429).
#
#   bash scripts/redo_model.sh glm-4-7-flashx 2.1 programmer              # 2.1 has no upstream model
#   bash scripts/redo_model.sh glm-4-7-flashx 1.1 architect
#   bash scripts/redo_model.sh glm-4-7-flashx 1.1 programmer glm-4-7-flashx   # 4th arg = --from-model
#   WORKERS=2 ROUNDS=5 PY=~/wine_fuzz/venv/bin/python bash scripts/redo_model.sh ...
set -e
cd "$(dirname "$0")/.."
M=$1; S=$2; ST=${3:-architect}; FROM=${4:+--from-model $4}
[ -n "$M" ] && [ -n "$S" ] || { echo "usage: $0 <model> <scenario> [stage] [from-model]"; exit 1; }
PY=${PY:-python3}; WORKERS=${WORKERS:-1}; ROUNDS=${ROUNDS:-4}
for i in $(seq 1 "$ROUNDS"); do
    echo "===== round $i"
    $PY scripts/run_llm.py --scenario "$S" --stage "$ST" $FROM --models "$M" --workers "$WORKERS" --redo-bad | tee /tmp/redo_$M.log
    grep -q 'ERR \|bad-format\|TRUNCATED' /tmp/redo_$M.log || break          # nothing bad left
    grep -q 'HTTP 429' /tmp/redo_$M.log && { echo "rate limited; sleeping 120 s"; sleep 120; }
done
$PY scripts/summary_table.py | grep -E "^scenario |$M"
