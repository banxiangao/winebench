#!/usr/bin/env bash
# setup_eval_ubuntu.sh - prepare an Ubuntu (22.04 / 24.04) machine for scripts/evaluate.py:
# build tools + Wine's optional libraries, the Wine source at the benchmark's version, a full build, all test
# executables, and a Wine prefix.  Takes 30-90 minutes depending on the CPU.  Safe to re-run (resumes).
#
#   bash scripts/setup_eval_ubuntu.sh                 # ~/wine (source)  ~/wine-build (build)  wine-11.18
#   WINE_SRC=~/src/wine WINE_BUILD=~/build WINE_VERSION=11.18 bash scripts/setup_eval_ubuntu.sh
set -e
SRC=${WINE_SRC:-$HOME/wine}; BUILD=${WINE_BUILD:-$HOME/wine-build}; VER=${WINE_VERSION:-11.18}
JOBS=${JOBS:-$(nproc)}

echo "== packages"
sudo apt-get update -qq
sudo apt-get install -y build-essential flex bison gcc-mingw-w64-x86-64 ccache git xvfb python3 python3-pip \
    libfreetype-dev libgnutls28-dev libx11-dev libxext-dev libxrender-dev libxrandr-dev libxi-dev libxcursor-dev \
    libxfixes-dev libxcomposite-dev libxinerama-dev libxxf86vm-dev libgl-dev libglu1-mesa-dev libosmesa6-dev \
    libfontconfig-dev libxml2-dev libxslt1-dev libdbus-1-dev libpulse-dev libasound2-dev libunwind-dev libkrb5-dev \
    libcups2-dev libvulkan-dev libsdl2-dev libudev-dev libusb-1.0-0-dev libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev libpcap-dev libv4l-dev libsane-dev libgphoto2-dev libcapi20-dev libldap2-dev \
    libwayland-dev libxkbcommon-dev libxkbregistry-dev
if ! python3 -c 'import tomllib' 2>/dev/null && ! python3 -c 'import tomli' 2>/dev/null; then     # Python < 3.11
    sudo apt-get install -y python3-tomli 2>/dev/null || pip3 install --user tomli 2>/dev/null \
        || pip3 install --user --break-system-packages tomli          # old pip lacks --break-system-packages, new pip needs it
fi

echo "== source $SRC (wine-$VER)"
if [ ! -d "$SRC" ]; then
    git clone --branch wine-$VER --depth 1 https://gitlab.winehq.org/wine/wine.git "$SRC" \
    || git clone --branch wine-$VER --depth 1 https://github.com/wine-mirror/wine.git "$SRC"
fi
grep -q "$VER" "$SRC/VERSION" || { echo "$SRC is not Wine $VER: $(cat "$SRC/VERSION")"; exit 1; }

echo "== configure $BUILD"
mkdir -p "$BUILD"; cd "$BUILD"
[ -f Makefile ] || CC="ccache gcc" CROSSCC="ccache x86_64-w64-mingw32-gcc" "$SRC/configure" --enable-archs=x86_64 > configure.log 2>&1 \
    || { tail -20 configure.log; exit 1; }
grep -i 'warning: ' configure.log | sed 's/^/   /' || true           # optional libraries that were not found

echo "== build (this is the long part)"
make -j"$JOBS" > build.log 2>&1 || { tail -30 build.log; exit 1; }
echo "== build the test executables"
make -j"$JOBS" buildtests > buildtests.log 2>&1 || { tail -30 buildtests.log; exit 1; }

echo "== Wine prefix ~/.wine-bench"
export WINEPREFIX=$HOME/.wine-bench WINEDEBUG=-all
# mscoree,mshtml= : skip the Wine Mono / Gecko download dialog, which nobody can click under Xvfb (hangs forever)
WINEDLLOVERRIDES="mscoree,mshtml=" timeout 600 xvfb-run -a ./wine wineboot -u > /dev/null 2>&1 || true
timeout 120 ./server/wineserver -w || ./server/wineserver -k

echo "== smoke test: kernelbase path tests on the clean tree"
rm -f dlls/kernelbase/tests/*/path.ok
xvfb-run -a make -s dlls/kernelbase/tests/x86_64-windows/path.ok | tail -3 || true
echo "done.  Now:  xvfb-run -a python3 scripts/evaluate.py --src $SRC --build $BUILD --scenario 1.1 --stage programmer --from-model <M> --models <M>"
