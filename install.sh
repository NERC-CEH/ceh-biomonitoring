#!/usr/bin/env bash
# Install (or update) the toolkit with the pipelines you want. Nothing else to install first: no
# Miniforge or conda, no admin rights. It gets uv (a small program that fetches Python and packages),
# which gets Python 3.11, and puts everything in one folder ($CEHBIO_HOME, default
# ~/.local/share/ceh-biomonitoring). Then the `cehbio` command works in any new terminal.
#
#   ./install.sh bats             just the bat pipeline
#   ./install.sh birds bats       birds + bats
#   ./install.sh videos           videos of nights and soundscapes (add to any of the above)
#   ./install.sh all              everything
#   ./install.sh                  just the core and reports (add pipelines later the same way)
#   ./install.sh --conda bats     the old way, into a conda environment called ceh-biomonitoring
#
# Run it again any time to add pipelines or get the newest packages. R users can do the same from R
# with cehbio::cehbio_install(), which uses this same folder.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USE_CONDA=0
[[ "${1:-}" == "--conda" ]] && { USE_CONDA=1; shift; }
EXTRAS="$(IFS=,; echo "reports${*:+,$*}")"

# JASMIN sci servers only allow 512 MB in /tmp, which is too small for PyTorch/TensorFlow,
# and network scratch breaks clean-up. The local /var/tmp disk works.
if [[ -d /var/tmp && ( -d /gws || "$(hostname -f 2>/dev/null)" == *jasmin* ) ]]; then
  export TMPDIR="/var/tmp/${USER}/cehbio-install"
  mkdir -p "$TMPDIR"
  trap 'rm -rf "$TMPDIR"' EXIT
fi

if [[ "$USE_CONDA" == 1 ]]; then
  ENV_NAME="${CEHBIO_ENV:-ceh-biomonitoring}"
  CONDA=""
  for c in mamba conda; do command -v "$c" >/dev/null 2>&1 && { CONDA="$c"; break; }; done
  [[ -z "$CONDA" ]] && { echo "No conda found. Leave out --conda to install without it."; exit 1; }
  ENV_PY="$("$CONDA" run -n "$ENV_NAME" python -c 'import sys; print(sys.executable)' 2>/dev/null || true)"
  if [[ -z "$ENV_PY" ]]; then
    "$CONDA" env create -q -f "$HERE/environment.yml" -n "$ENV_NAME"
    ENV_PY="$("$CONDA" run -n "$ENV_NAME" python -c 'import sys; print(sys.executable)')"
  fi
  "$ENV_PY" -m pip install --upgrade --upgrade-strategy eager -e "$HERE[$EXTRAS]"
  "$ENV_PY" -m ceh_biomonitoring.cli pipelines
  echo "Done. Activate with:  conda activate $ENV_NAME    then try:  cehbio check"
  exit 0
fi

CEHBIO_HOME="${CEHBIO_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/ceh-biomonitoring}"
mkdir -p "$CEHBIO_HOME/uv"
export UV_PYTHON_INSTALL_DIR="$CEHBIO_HOME/python" UV_NO_MODIFY_PATH=1 UV_PYTHON_PREFERENCE=only-managed UV_LINK_MODE=copy

UV="$CEHBIO_HOME/uv/uv"
if [[ ! -x "$UV" ]]; then
  if command -v uv >/dev/null 2>&1; then UV="$(command -v uv)"
  else
    case "$(uname -s)-$(uname -m)" in
      Linux-x86_64)  F=uv-x86_64-unknown-linux-gnu ;;
      Linux-aarch64) F=uv-aarch64-unknown-linux-gnu ;;
      Darwin-arm64)  F=uv-aarch64-apple-darwin ;;
      Darwin-x86_64) F=uv-x86_64-apple-darwin ;;
      *) echo "No uv download for $(uname -s) $(uname -m). Install uv yourself (docs.astral.sh/uv), then run this again."; exit 1 ;;
    esac
    echo "Getting uv (once) ..."
    T="$(mktemp -d)"
    curl -fsSL "https://github.com/astral-sh/uv/releases/latest/download/$F.tar.gz" | tar -xz -C "$T"
    mv "$T/$F/uv" "$UV" && chmod +x "$UV" && rm -rf "$T"
  fi
fi

ENV="$CEHBIO_HOME/env"
PY="$ENV/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "Making the toolkit's Python environment (once) ..."
  "$UV" venv --seed --python 3.11 "$ENV"
fi
# the partner pack's upload tool (a .whl beside this script), else this copy of the repository
WHEEL="$(ls "$HERE"/ceh_biomonitoring-*.whl 2>/dev/null | tail -1 || true)"
if [[ -n "$WHEEL" ]]; then
  echo "Installing the upload tool ..."
  "$UV" pip install --python "$PY" --upgrade "$WHEEL"
else
  echo "Installing: $EXTRAS (the first time takes a while: the models' packages are large)"
  "$UV" pip install --python "$PY" --upgrade -e "$HERE[$EXTRAS]"
  "$PY" -m ceh_biomonitoring.reporting.getquarto >/dev/null || echo "(Quarto, for Word and PDF reports, will be fetched when first needed)"
fi

# the `cehbio` command, for every new terminal
BIN="$HOME/.local/bin"
mkdir -p "$BIN"
printf '#!/bin/sh\nexec "%s" -m ceh_biomonitoring "$@"\n' "$PY" > "$BIN/cehbio"
chmod +x "$BIN/cehbio"

echo
if [[ -n "$WHEEL" ]]; then
  # make sure new Terminal windows find `cehbio` (Mac: zsh; Linux: bash)
  for rc in "$HOME/.zshrc" "$HOME/.bashrc"; do
    if [[ -f "$rc" || "$rc" == "$HOME/.zshrc" && "$(uname -s)" == Darwin ]] && ! grep -qs '.local/bin' "$rc"; then
      echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$rc"
    fi
  done
  echo "Done. The upload tool is installed. To upload: open a NEW Terminal window and type:  cehbio upload"
  exit 0
fi
"$PY" -m ceh_biomonitoring.cli pipelines
case ":$PATH:" in
  *":$BIN:"*) echo "Done. Try:  cehbio check" ;;
  *) echo "Done. Add $BIN to your PATH (e.g. echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc),"
     echo "open a new terminal, then try:  cehbio check" ;;
esac
