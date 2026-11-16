#!/usr/bin/env bash
# Install (or update) the ceh-biomonitoring environment with the pipelines you want.
#
#   ./install.sh bats             just the bat pipeline
#   ./install.sh birds bats       birds + bats
#   ./install.sh all              everything
#   ./install.sh                  just the core (add pipelines later the same way)
#
# Run it again any time to add pipelines or get the newest model packages.
set -euo pipefail

ENV_NAME="${CEHBIO_ENV:-ceh-biomonitoring}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXTRAS="$(IFS=,; echo "$*")"

# JASMIN sci servers only allow 512 MB in /tmp, which is too small for PyTorch/TensorFlow,
# and network scratch breaks pip's clean-up. The local /var/tmp disk works.
if [[ -d /var/tmp && ( -d /gws || "$(hostname -f 2>/dev/null)" == *jasmin* ) ]]; then
  export TMPDIR="/var/tmp/${USER}/cehbio-install"
  mkdir -p "$TMPDIR"
  trap 'rm -rf "$TMPDIR"' EXIT
fi

CONDA=""
for c in mamba conda; do command -v "$c" >/dev/null 2>&1 && { CONDA="$c"; break; }; done
if [[ -z "$CONDA" ]]; then
  for d in "$HOME/miniforge3" "$HOME/mambaforge" "$HOME/miniconda3"; do
    [[ -x "$d/bin/conda" ]] && { CONDA="$d/bin/conda"; break; }
  done
fi
[[ -z "$CONDA" ]] && { echo "No conda/mamba found. Install Miniforge first: https://github.com/conda-forge/miniforge"; exit 1; }

ENV_PY="$("$CONDA" run -n "$ENV_NAME" python -c 'import sys; print(sys.executable)' 2>/dev/null || true)"
if [[ -z "$ENV_PY" ]]; then
  echo "Creating environment '$ENV_NAME' (Python 3.11)..."
  "$CONDA" env create -q -f "$HERE/environment.yml" -n "$ENV_NAME"
  ENV_PY="$("$CONDA" run -n "$ENV_NAME" python -c 'import sys; print(sys.executable)')"
fi

TARGET="$HERE"
[[ -n "$EXTRAS" ]] && TARGET="$HERE[$EXTRAS]"
echo "Installing: ${EXTRAS:-core only}"
"$ENV_PY" -m pip install --upgrade --upgrade-strategy eager --resume-retries 10 --timeout 120 -e "$TARGET"

echo
"$ENV_PY" -m ceh_biomonitoring.cli pipelines
echo "Done. Activate with:  conda activate $ENV_NAME    then try:  cehbio check"
