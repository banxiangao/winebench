#!/bin/sh
# Prepare the generated headers wine_deps.py needs, WITHOUT touching the Wine source tree.
#   usage: sh setup_wine_build.sh <wine-src> <build-dir>
# needs: gcc (or cc), bison, flex, python3;  then: pip install libclang
set -e
SRC=$(cd "$1" && pwd); mkdir -p "$2"; B=$(cd "$2" && pwd)
CC=${CC:-cc}
mkdir -p "$B/include" "$B/widl"

# macOS: system headers live in the SDK, and Apple's bison 2.3 is too old for widl's grammar
SYSINC=/usr/include
if [ "$(uname -s)" = Darwin ]; then
    SYSINC="$(xcrun --show-sdk-path)/usr/include"
    for d in /opt/homebrew/opt/bison/bin /usr/local/opt/bison/bin; do [ -x "$d/bison" ] && PATH="$d:$PATH"; done
fi
case "$(bison --version | head -1)" in
    *" 1."*|*" 2."*) echo "bison >= 3 is required (found: $(bison --version | head -1)); on macOS: brew install bison" >&2; exit 1;;
esac

# 1. config.h: version + HAVE_*_H for the headers present on this system
python3 - "$SRC" "$B" "$SYSINC" <<'PY'
import re, os, sys
src, b, sysinc = sys.argv[1], sys.argv[2], sys.argv[3]
ver = open(f'{src}/VERSION').read().split()[-1]
t = open(f'{src}/include/config.h.in').read()
out = ['#ifndef __WINE_CONFIG_H', '#define __WINE_CONFIG_H', f'#define PACKAGE_VERSION "{ver}"',
       f'#define PACKAGE_STRING "Wine {ver}"', '#define PACKAGE_NAME "Wine"']
dirs = [sysinc] + [d for d in os.popen('ls -d /usr/include/*-linux-gnu 2>/dev/null').read().split()]
for macro, name in re.findall(r'#undef (HAVE_(\w+)_H)\b', t):
    for c in {name.lower().replace('_', '/') + '.h', name.lower() + '.h'}:
        if any(os.path.exists(os.path.join(d, c)) for d in dirs):
            out.append(f'#define {macro} 1'); break
out.append('#endif')
open(f'{b}/include/config.h', 'w').write('\n'.join(out) + '\n')
PY

# 2. build widl (IDL compiler) out of tree
cd "$B/widl"
bison -d -o parser.tab.c "$SRC/tools/widl/parser.y"
bison -d -o ppy.tab.c   "$SRC/tools/wrc/ppy.y"
flex -o parser.yy.c "$SRC/tools/widl/parser.l"
flex -o ppl.yy.c    "$SRC/tools/wrc/ppl.l"
W=""; for f in attribute client expr hash header metadata proxy register server typegen typelib typetree utils widl write_msft write_sltg; do W="$W $SRC/tools/widl/$f.c"; done
$CC -O1 -w -o widl -I. -I../include -I"$SRC/tools/widl" -I"$SRC/tools/wrc" -I"$SRC/tools" -I"$SRC/include" \
    -DINCLUDEDIR='"/usr/include"' -DBINDIR='"/usr/bin"' -DLIBDIR='"/usr/lib"' \
    $W "$SRC/tools/wrc/wpp.c" parser.tab.c parser.yy.c ppy.tab.c ppl.yy.c

# 3. generate headers from every .idl (include/ and module-private ones), mirrored under $B.
#    widl creates tmp* scratch dirs in the current directory, so run it from $B, never from $SRC.
cd "$B"
(cd "$SRC" && find include dlls programs -name '*.idl' -not -path '*/tests/*') | while read f; do
    d=$(dirname "$f"); mkdir -p "$B/$d"
    "$B/widl/widl" --nostdinc -I"$B/include" -I"$SRC/include" -I"$SRC/$d" -I"$B/$d" -D__WINESRC__ -h \
        -o "$B/${f%.idl}.h" "$SRC/$f" 2>/dev/null || echo "skip $f (IDL fragment included by another IDL)" >> "$B/widl.skipped"
done
rm -rf "$B"/tmp[0-9a-f]*

# 4. rmxftmpl.h (DirectX file templates)
$CC -w -o "$B/make_xftmpl" -I"$B/include" -I"$SRC/tools" -I"$SRC/include" "$SRC/tools/make_xftmpl.c"
"$B/make_xftmpl" -H -o "$B/include/rmxftmpl.h" "$SRC/include/rmxftmpl.x"

echo "done: $(find "$B" -name '*.h' | wc -l) headers in $B  ($(cat "$B/widl.skipped" 2>/dev/null | wc -l) IDL fragments skipped)"
