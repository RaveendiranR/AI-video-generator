#!/usr/bin/env sh
set -eu

PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
printf '\nInstalled. Activate with: . .venv/bin/activate\n'
printf 'Check FFmpeg with: python -m faceless_video_generator --check\n'
