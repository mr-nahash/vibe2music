#!/usr/bin/env bash
# vibe2music -- setup for a LOCAL machine with an NVIDIA GPU (Linux or WSL2).
#
# Windows users: run this inside WSL2 (Ubuntu). Native Windows works too if
# you install ffmpeg + Python manually and run the pip lines below.
#
# Requirements: NVIDIA driver already installed (`nvidia-smi` must work).
# Model weights (~7 GB) auto-download from HuggingFace on first generation.
set -euo pipefail

cd "$(dirname "$0")/.."

# --- sanity: GPU visible? -------------------------------------------------
if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "warning: nvidia-smi not found -- install the NVIDIA driver first."
    echo "         (generation will fall back to CPU, which is very slow)"
else
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
fi

# --- system deps ----------------------------------------------------------
if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg git python3-venv
elif ! command -v ffmpeg >/dev/null 2>&1; then
    echo "install ffmpeg with your package manager, then re-run" && exit 1
fi

# --- isolated venv (don't pollute the system python) ----------------------
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip

# --- torch: pick the CUDA wheel matching the local driver -----------------
# cu121 wheels run on any driver >= 530; use cu118 for older drivers.
CUDA_INDEX="https://download.pytorch.org/whl/cu121"
if command -v nvidia-smi >/dev/null 2>&1; then
    DRIVER=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1 | cut -d. -f1)
    if [ "${DRIVER:-0}" -lt 530 ] 2>/dev/null; then
        echo "driver $DRIVER is old -- using cu118 wheels"
        CUDA_INDEX="https://download.pytorch.org/whl/cu118"
    fi
fi
pip install torch --index-url "$CUDA_INDEX"

pip install "git+https://github.com/ace-step/ACE-Step.git"
pip install -r requirements.txt

# --- verify ---------------------------------------------------------------
python - <<'PY'
import torch
if torch.cuda.is_available():
    p = torch.cuda.get_device_properties(0)
    vram = p.total_memory / 1e9
    print(f"OK: {p.name} ({vram:.0f} GB VRAM)")
    if vram < 12:
        print("note: under 12 GB -- run with --low-vram (auto-enabled by generate.py)")
else:
    print("WARNING: torch cannot see a CUDA GPU. Check driver / WSL2 GPU passthrough.")
PY

echo
echo "setup complete. next:"
echo "  source .venv/bin/activate"
echo "  export ANTHROPIC_API_KEY=sk-ant-..."
echo "  python src/run_all.py \"rainy tokyo cafe\" --instruments piano,vinyl \\"
echo "      --image cover.jpg --target-minutes 45"
