#!/usr/bin/env bash
# Backwards-compatible installer for a RunPod/Vast.ai GPU box.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if command -v apt-get >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y -qq ffmpeg git python3-venv
fi

bash "${ROOT}/setup_local.sh"

echo
echo "GPU worker ready. Start it with:"
echo "  API_TOKEN=<long-secret> ${ROOT}/run_local.sh"
echo "Then expose port 8000 through the provider's HTTPS proxy or a secure tunnel."
