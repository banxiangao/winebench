#!/usr/bin/env bash
# make_swe_trees.sh - the restricted Wine trees the off-the-shelf agents (mini-swe-agent, OpenHands) work in.
#
#   bash scripts/make_swe_trees.sh 2            # ~/wine-swe + ~/wine-build-swe (worker 0), ~/wine-swe-w1 + ~/wine-build-swe-w1
#   WINE_SRC=~/wine WINE_BUILD=~/wine-build bash scripts/make_swe_trees.sh 2
#   bash scripts/make_swe_trees.sh --remove
#
# Each pair is: the source WITHOUT .git and WITHOUT test sources (dlls/*/tests and programs/*/tests keep only their
# Makefile.in, so make still works but no test can be built or run), made into a fresh git repo whose only commit is the
# clean tree; and a copy of the build directory (timestamps kept, Makefile pointed at the copy) with every test build
# output removed.  The agent therefore cannot read tests, cannot build or run them, and cannot recover the original
# implementation from git.  One pair costs about as much disk as the source + build.
set -e
SRC=$(realpath -m "${WINE_SRC:-$HOME/wine}"); BUILD=$(realpath -m "${WINE_BUILD:-$HOME/wine-build}")
OUT_SRC=${SWE_SRC:-$HOME/wine-swe}; OUT_BUILD=${SWE_BUILD:-$HOME/wine-build-swe}

if [ "$1" = "--remove" ]; then
    for d in "$OUT_SRC" "$OUT_SRC".gitdir "$OUT_SRC"-w* "$OUT_BUILD" "$OUT_BUILD"-w*; do [ -d "$d" ] && { echo "rm -rf $d"; rm -rf "$d"; }; done; exit 0
fi
N=${1:?usage: $0 <workers> | --remove}
[ -f "$BUILD/Makefile" ] || { echo "$BUILD has no Makefile: build Wine first (scripts/setup_eval_ubuntu.sh)"; exit 1; }
grep -q "^srcdir = $SRC\$" "$BUILD/Makefile" || { echo "$BUILD/Makefile was not configured from $SRC:"; grep '^srcdir' "$BUILD/Makefile"; exit 1; }
grep -q 11.19 "$SRC/VERSION" || { echo "$SRC is not Wine 11.19"; exit 1; }
command -v git >/dev/null || { echo "git is needed"; exit 1; }

for i in $(seq 0 $((N - 1))); do
    sfx=""; [ "$i" -gt 0 ] && sfx="-w$i"
    S="$OUT_SRC$sfx"; B="$OUT_BUILD$sfx"
    if { [ -d "$S.gitdir" ] || [ -d "$S/.git" ]; } && [ -d "$S/dlls" ] && grep -q "^srcdir = $S\$" "$B/Makefile" 2>/dev/null; then echo "worker $i: $S, $B (exists)"; continue; fi
    size=$(du -sk "$SRC" "$BUILD" | awk '{s += $1} END {print s}'); free=$(df -k --output=avail "$(dirname "$B")" | tail -1)
    [ "$free" -gt $((size + 3 * 1024 * 1024)) ] || { echo "not enough disk for worker $i (need $((size / 1024 / 1024)) GB + 3 GB spare)"; exit 1; }
    echo "worker $i: $S, $B ..."
    rm -rf "$S" "$B" "$S.gitdir"
    cp -a "$SRC" "$S"; rm -rf "$S/.git"
    # tests: keep only Makefile.in (the top Makefile depends on every Makefile.in), delete the sources
    find "$S/dlls" "$S/programs" -type d -name tests | while read -r d; do find "$d" -mindepth 1 ! -name Makefile.in -delete; done
    rm -rf "$S/.git" "$S/.gitlab-ci.yml"
    # the repository is kept outside the tree ($S.gitdir; the tree only has a .git file pointing to it), so an agent that
    # deletes or re-creates .git cannot destroy the clean commit the tree is reset to between tasks
    ( cd "$S" && git init -q --separate-git-dir "$S.gitdir" && git -c user.name=bench -c user.email=bench@localhost add -A && git -c user.name=bench -c user.email=bench@localhost commit -qm "clean tree (tests removed)" )
    cp -a "$BUILD" "$B"
    rm -rf "$B/.eval_snapshot"
    find "$B/dlls" "$B/programs" -type d -name tests | while read -r d; do find "$d" -mindepth 1 -delete; done     # no test binaries either
    for f in Makefile config.status; do
        python3 - "$B/$f" "$SRC" "$S" "$BUILD" "$B" <<'EOF'
import os, re, sys
f, old_src, new_src, old_build, new_build = sys.argv[1:]
st = os.stat(f); s = open(f, encoding='utf-8', errors='surrogateescape').read()
s = re.sub(re.escape(old_src) + r'(?=[/\s:\'"]|$)', new_src.replace('\\', r'\\'), s, flags=re.M)
s = re.sub(re.escape(old_build) + r'(?=[/\s:\'"]|$)', new_build.replace('\\', r'\\'), s, flags=re.M)
open(f, 'w', encoding='utf-8', errors='surrogateescape').write(s); os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))
EOF
    done
    grep -q "^srcdir = $S\$" "$B/Makefile" || { echo "path fix-up failed in $B/Makefile"; exit 1; }
    ( cd "$B" && make -q dlls/kernelbase/x86_64-windows/kernelbase.dll >/dev/null 2>&1 ) && echo "  up to date (no rebuild needed)" \
        || echo "  note: make wants to rebuild something; the first ./compile will take longer"
done
echo "done.  Now:  N=5 bash scripts/run_swe_ubuntu.sh"
