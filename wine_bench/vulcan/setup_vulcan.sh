#!/usr/bin/env bash
# setup_vulcan.sh - one-time setup on the Vulcan (Alliance) LOGIN node: a venv with vLLM from the cluster wheelhouse.
#
#   bash vulcan/setup_vulcan.sh
#
# Layout (next to this package, wherever it is - NOT /home which is 50 GB):
#   <somewhere>/wine_bench   this package
#   <somewhere>/venv-vllm    the Python environment (created here)
#   ~/scratch/models/<name>  the weights (vulcan/download_models.sh)
set -e
WB=$(cd "$(dirname "$0")/.." && pwd)                   # the wine_bench directory this script lives in
PROJ=${PROJ:-$(dirname "$WB")}; VENV=${VENV:-$PROJ/venv-vllm}   # the venv goes next to wine_bench
echo "wine_bench: $WB"; echo "venv:       $VENV"
# Alliance clusters: the opencv (and gcc) modules must be loaded BEFORE the venv is created and used - vLLM's
# dependency chain includes opencv, and the wheelhouse ships a dummy wheel that fails on purpose otherwise.
module purge 2>/dev/null; module load StdEnv/2023 2>/dev/null || true
module load gcc opencv/4.11 python/3.12 2>/dev/null || module load gcc opencv python/3.12 || { echo "cannot load the opencv/python modules: module spider opencv"; exit 1; }
module list 2>&1 | grep -iE "opencv|python|gcc"
module load arrow 2>/dev/null || true                     # pyarrow is a dummy wheel too (needed by ray/datasets if pulled in)
if [ ! -x "$VENV/bin/python" ]; then
    virtualenv --no-download "$VENV"
    "$VENV/bin/pip" install --no-index --upgrade pip
fi
# vLLM asks for opencv-python-headless >= 4.13, the cluster's opencv module is 4.11 -> pip tries the dummy wheel and
# stops.  cv2 itself comes from the module at run time (vLLM only needs it for video input), so a metadata-only stub
# that says "4.13.0 is installed" satisfies pip.
SP=$("$VENV/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
D="$SP/opencv_python_headless-4.13.0.dist-info"
if [ ! -d "$D" ]; then
    mkdir -p "$D"
    printf 'Metadata-Version: 2.1\nName: opencv-python-headless\nVersion: 4.13.0\nSummary: stub - the real cv2 is the cluster opencv module\n' > "$D/METADATA"
    echo pip > "$D/INSTALLER"; : > "$D/RECORD"
fi
"$VENV/bin/pip" install --no-index vllm huggingface_hub tomli      # wheelhouse only: PyPI's vllm does not resolve here
"$VENV/bin/python" -c 'import cv2; print("cv2 from module:", cv2.__version__)' || echo "warning: cv2 not importable (module opencv not loaded?)"
"$VENV/bin/python" -c 'import vllm, huggingface_hub; print("vllm", vllm.__version__)'
mkdir -p ~/scratch/models ~/scratch/hf
echo "done.  Next:  bash vulcan/download_models.sh"
