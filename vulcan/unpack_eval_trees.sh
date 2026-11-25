#!/usr/bin/env bash
# unpack_eval_trees.sh - fresh copies of the CLEAN, fully built Wine (with its tests) for ONE evaluation job.
#
#   bash vulcan/unpack_eval_trees.sh /pack/eval-pair.tar 6      (inside the container; /w = the job's node-local disk)
#
# The tarball (wine_agent/vulcan/pack_trees.sbatch) holds /w/wine and /w/wine-build as they were configured and built.
# evaluate.py --workers N wants worker 0 = /w/wine + /w/wine-build and worker i = /w/wine-w<i> + /w/wine-build-w<i>
# (what scripts/make_eval_trees.sh makes with cp -a): the copies get their own paths in Makefile / config.status,
# timestamps kept, and every pair is checked with make -q (nothing may want a rebuild).
set -e
TAR=${1:?tarball}; N=${2:?workers}; OUT=${EVAL_ROOT:-/w}
[ -f "$TAR" ] || { echo "$TAR: no tarball (cd wine_agent && sbatch vulcan/pack_trees.sbatch)"; exit 1; }
mkdir -p "$OUT/tmp" "$OUT/pfx" "$OUT/cache"
relink() {   # $1 = build dir, $2 = old source prefix, $3 = new one: the build has absolute symlinks into the source it was configured from
    local l t; find "$1" -type l -lname "$2/*" -print0 | while IFS= read -r -d "" l; do t=$(readlink "$l"); ln -sfn "$3${t#"$2"}" "$l"; done
}
one() {
    local i=$1 sfx="" d S B
    [ "$i" -gt 0 ] && sfx="-w$i"
    d="$OUT/.unpack$i"; S="$OUT/wine$sfx"; B="$OUT/wine-build$sfx"
    rm -rf "$d" "$S" "$B"; mkdir -p "$d"
    tar -xf "$TAR" -C "$d"
    mv "$d/wine" "$S"; mv "$d/wine-build" "$B"; rmdir "$d"
    if [ -n "$sfx" ]; then
        for f in Makefile config.status; do
            python3 - "$B/$f" "$OUT/wine" "$S" "$OUT/wine-build" "$B" <<'PY'
import os, re, sys
f, old_src, new_src, old_build, new_build = sys.argv[1:]
st = os.stat(f); s = open(f, encoding='utf-8', errors='surrogateescape').read()
s = re.sub(re.escape(old_src) + r'(?=[/\s:\'"]|$)', new_src.replace('\\', r'\\'), s, flags=re.M)
s = re.sub(re.escape(old_build) + r'(?=[/\s:\'"]|$)', new_build.replace('\\', r'\\'), s, flags=re.M)
open(f, 'w', encoding='utf-8', errors='surrogateescape').write(s); os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))
PY
        done
    fi
    grep -q "^srcdir = $S\$" "$B/Makefile" || { echo "worker $i: path fix-up failed"; return 1; }
    [ -n "$sfx" ] && relink "$B" "$OUT/wine" "$S"
    [ -e "$B/wine" ] || { echo "worker $i: $B/wine missing"; return 1; }
    ( cd "$B" && make -q dlls/kernelbase/all >/dev/null 2>&1 ) || { echo "worker $i: make wants to rebuild something"; return 1; }
    echo "worker $i: $S, $B ok"
}
pids=(); for i in $(seq 0 $((N - 1))); do one "$i" & pids+=($!); done
bad=0; for p in "${pids[@]}"; do wait "$p" || bad=1; done
[ "$bad" = 0 ] || { echo "unpacking FAILED"; exit 1; }
echo "unpacked $N clean tree pairs in $OUT ($(du -sh "$OUT" 2>/dev/null | cut -f1))"
