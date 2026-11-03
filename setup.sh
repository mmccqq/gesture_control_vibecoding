#!/bin/sh
# Create the virtualenv, install dependencies and download the hand model.
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
mkdir -p models
[ -f models/hand_landmarker.task ] || curl -fsSL -o models/hand_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task
echo "Done. Run: .venv/bin/python -m gesture_control"
