#!/usr/bin/env bash
# vibe2music -- setup for a fresh RunPod RTX 4090 pod (Ubuntu + CUDA 12.x).
# Model weights auto-download from HuggingFace on first generation run.
set -euo pipefail

apt-get update -qq && apt-get install -y -qq ffmpeg git

pip install --upgrade pip
pip install torch --index-url https://download.pytorch.org/whl/cu121
pip install "git+https://github.com/ace-step/ACE-Step.git"
pip install -r "$(dirname "$0")/../requirements.txt"

echo "setup complete"
echo "next: export ANTHROPIC_API_KEY=...; export API_TOKEN=<pick-a-secret>"
echo "      cd src && uvicorn server:app --host 0.0.0.0 --port 8000"
