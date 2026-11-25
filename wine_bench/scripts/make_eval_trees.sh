#!/usr/bin/env bash
# make_eval_trees.sh - copies of the built Wine tree for evaluate.py --workers N (worker 0 uses the original).
#
#   bash scripts/make_eval_trees.sh 4          # creates ~/wine-w1..3 and ~/wine-build-w1..3 (no rebuild needed)
#   WINE_SRC=~/wine WINE_BUILD=~/wine-build bash scripts/make_eval_trees.sh 4
#   bash scripts/make_eval_trees.sh --remove   # delete all copies
#
# A copy is a plain `cp -a` (timestamps kept, so make sees everything as up to date) plus the source path in the
# copied Makefile / config.status pointed at the copied source.  Each copy costs as much disk as the original.
set -e
SRC=$(realpath -m "${WINE_SRC:-$HOME/wine}"); BUILD=$(realpath -m "${WINE_BUILD:-$HOME/wine-build}")
PFX=${WINE_PREFIX_BASE:-$HOME/.wine-bench}

if [ "$1" = "--remove" ]; then
    for d in "$SRC"-w* "$BUILD"-w* "$PFX"-w*; do [ -d "$d" ] && { echo "rm -rf $d"; rm -rf "$d"; }; done; exit 0
fi
N=${1:?usage: $0 <workers> | --remove}
[ -f "$BUILD/Makefile" ] || { echo "$BUILD has no Makefile: build Wine first (scripts/setup_eval_ubuntu.sh)"; exit 1; }
grep -q "^srcdir = $SRC\$" "$BUILD/Makefile" || { echo "$BUILD/Makefile was not configured from $SRC:"; grep '^srcdir' "$BUILD/Makefile"; exit 1; }

need=0
for i in $(seq 1 $((N - 1))); do [ -d "$SRC-w$i" ] || need=1; done
if [ $need = 1 ]; then
    size=$(du -sk "$SRC" "$BUILD" | awk '{s += $1} END {print s}')
    free=$(df -k --output=avail "$(dirname "$BUILD")" | tail -1)
    echo "one copy = $((size / 1024 / 1024)) GB, free = $((free / 1024 / 1024)) GB"
fi

for i in $(seq 1 $((N - 1))); do
    S="$SRC-w$i"; B="$BUILD-w$i"
    if [ -f "$B/Makefile" ] && grep -q "^srcdir = $S\$" "$B/Makefile"; then echo "worker $i: $S, $B (exists)"; continue; fi
    size=$(du -sk "$SRC" "$BUILD" | awk '{s += $1} END {print s}')
    free=$(df -k --output=avail "$(dirname "$BUILD")" | tail -1)
    [ "$free" -gt $((size + 5 * 1024 * 1024)) ] || { echo "not enough disk for worker $i (need $((size / 1024 / 1024)) GB + 5 GB spare)"; exit 1; }
    echo "worker $i: copying to $S, $B ..."
    rm -rf "$S" "$B"
    cp -a "$SRC" "$S"
    cp -a "$BUILD" "$B"
    rm -rf "$B/.eval_snapshot"
    for f in Makefile config.status; do                     # point the copy at its own source, keep the timestamp
        python3 - "$B/$f" "$SRC" "$S" <<'EOF'
import os, re, sys
f, old, new = sys.argv[1:]
st = os.stat(f); s = open(f, encoding='utf-8', errors='surrogateescape').read()
s = re.sub(re.escape(old) + r'(?=[/\s:\'"]|$)', new.replace('\\', r'\\'), s, flags=re.M)
open(f, 'w', encoding='utf-8', errors='surrogateescape').write(s); os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))
EOF
    done
    grep -q "^srcdir = $S\$" "$B/Makefile" || { echo "path fix-up failed in $B/Makefile"; exit 1; }
done

echo "checking that the copies are up to date (make -q, no rebuild) ..."
for i in $(seq 1 $((N - 1))); do
    ( cd "$BUILD-w$i" && make -q ${CHECK_TARGET:-dlls/kernelbase/all} >/dev/null 2>&1 ) && echo "  worker $i ok" \
        || echo "  worker $i: make thinks something is out of date; the first record there will rebuild it (slow once)"
done
echo "done.  Now:  WORKERS=$N bash scripts/run_eval_ubuntu.sh"
