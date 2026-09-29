#!/usr/bin/env sh
set -eu
. .venv/bin/activate
exec python -m faceless_video_generator.webui
