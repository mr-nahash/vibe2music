#!/usr/bin/env bash
# Install vibe2music for a local NVIDIA workstation or CPU/MPS development box.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV="${VENV:-${ROOT}/.venv}"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg is required. Install it with your system package manager, then rerun." >&2
  exit 1
fi

"${PYTHON_BIN}" -m venv "${VENV}"
# shellcheck disable=SC1091
source "${VENV}/bin/activate"
python -m pip install --upgrade pip wheel

if command -v nvidia-smi >/dev/null 2>&1; then
  echo "NVIDIA GPU detected; installing the CUDA 12.6 PyTorch wheels."
  python -m pip install torch torchvision torchaudio \
    --index-url "${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu126}"
else
  echo "No nvidia-smi found; installing the default PyTorch build for development."
  python -m pip install torch torchvision torchaudio
fi

python -m pip install -r "${ROOT}/requirements.txt"
python -m pip install "git+https://github.com/ace-step/ACE-Step.git${ACE_STEP_REF:+@${ACE_STEP_REF}}"

python - <<'PY'
import torch
print("torch:", torch.__version__)
print("CUDA available:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("GPU:", torch.cuda.get_device_name(0))
PY

echo
echo "Installation complete. Start the API with:"
echo "  API_TOKEN=... ${VENV}/bin/python -m uvicorn src.server:app --host 127.0.0.1 --port 8000"
