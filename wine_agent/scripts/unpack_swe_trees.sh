#!/usr/bin/env bash
# unpack_swe_trees.sh - fresh restricted tree pairs for ONE job, from the packed pair (vulcan/pack_trees.sbatch).
#
#   bash scripts/unpack_swe_trees.sh /pack/swe-pair.tar 6        (inside the container; /t = the job's node-local disk)
#
# The tarball holds worker 0's pair as it must appear in the container: /t/wine-swe, /t/wine-swe.gitdir, /t/wine-build-swe.
# Worker i > 0 gets a copy under -w<i> with the paths in its Makefile / config.status changed (timestamps kept), exactly as
# make_swe_trees.sh does.  Every pair is then checked: git sees a clean tree, make sees nothing to rebuild.
set -e
TAR=${1:?tarball}; N=${2:?workers}; OUT=${SWE_ROOT:-/t}
[ -f "$TAR" ] || { echo "$TAR: no tarball (sbatch vulcan/pack_trees.sbatch)"; exit 1; }
mkdir -p "$OUT/tmp"
relink() {   # $1 = build dir, $2 = old source prefix, $3 = new one: the build has absolute symlinks into the source it was configured from
    local l t; find "$1" -type l -lname "$2/*" -print0 | while IFS= read -r -d "" l; do t=$(readlink "$l"); ln -sfn "$3${t#"$2"}" "$l"; done
}
upcheck() {   # $1 = build dir, $2 = when: nothing may want a rebuild; says what does
    local rc=0; ( cd "$1" && make -q dlls/kernelbase/x86_64-windows/kernelbase.dll >/dev/null 2>&1 ) || rc=$?
    [ $rc = 0 ] && return 0
    echo "$1: make -q fails ($2, status $rc: 1 = out of date, 2 = error); make -n says:"
    ( cd "$1" && make -n dlls/kernelbase/x86_64-windows/kernelbase.dll 2>&1 | head -6 | cut -c1-220 ); return 1
}
one() {
    local i=$1 sfx="" d S B G
    [ "$i" -gt 0 ] && sfx="-w$i"
    d="$OUT/.unpack$i"; S="$OUT/wine-swe$sfx"; B="$OUT/wine-build-swe$sfx"
    rm -rf "$d" "$S" "$S.gitdir" "$S.taskgit" "$B"; mkdir -p "$d"
    tar -xf "$TAR" -C "$d"
    mv "$d/wine-swe" "$S"; mv "$d/wine-swe.gitdir" "$S.gitdir"; mv "$d/wine-build-swe" "$B"; rmdir "$d"
    if [ -n "$sfx" ]; then
        for f in Makefile config.status; do
            python3 - "$B/$f" "$OUT/wine-swe" "$S" "$OUT/wine-build-swe" "$B" <<'PY'
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
    relink "$B" /w/wine "$S"                      # links made at build time point into the clean tree, which is not mounted here
    [ -n "$sfx" ] && relink "$B" "$OUT/wine-swe" "$S"
    n=$(find "$B" -xtype l | wc -l); [ "$n" = 0 ] || echo "worker $i: note: $n dangling symlinks in $B, e.g. $(find "$B" -xtype l | head -1) -> $(readlink "$(find "$B" -xtype l | head -1)")"
    upcheck "$B" "right after unpacking" || return 1
    G="git --git-dir $S.gitdir --work-tree $S"
    $G config core.worktree "$S"
    $G update-index -q --refresh >/dev/null 2>&1 || true            # extraction changed inode/ctime: without this, reset --hard rewrites every file and make rebuilds everything
    [ -z "$($G status --porcelain | head -1)" ] || { echo "worker $i: git sees changes after unpacking:"; $G status --porcelain | head -5; return 1; }
    $G reset -q --hard >/dev/null
    [ "$B/tools/makedep" -nt "$B/Makefile" ] && { echo "worker $i: tools/makedep is newer than the Makefile"; return 1; }
    upcheck "$B" "after git reset --hard" || return 1
    echo "worker $i: $S, $B ok"
}
pids=(); for i in $(seq 0 $((N - 1))); do one "$i" & pids+=($!); done
bad=0; for p in "${pids[@]}"; do wait "$p" || bad=1; done
[ "$bad" = 0 ] || { echo "unpacking FAILED"; exit 1; }
echo "unpacked $N tree pairs in $OUT ($(du -sh "$OUT" 2>/dev/null | cut -f1))"
