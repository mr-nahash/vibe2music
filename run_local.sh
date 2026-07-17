#!/usr/bin/env bash
# Start the durable local GPU worker and its API.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${VENV:-${ROOT}/.venv}"
cd "${ROOT}"
if [[ ! -x "${VENV}/bin/python" ]]; then
  echo "Missing ${VENV}. Run ./setup_local.sh first." >&2
  exit 1
fi

# shellcheck disable=SC1091
source "${VENV}/bin/activate"
if [[ -z "${API_TOKEN:-}" ]]; then
  API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
  export API_TOKEN
  echo "Generated API_TOKEN for this session: ${API_TOKEN}"
fi

exec python -m uvicorn src.server:app \
  --host "${HOST:-127.0.0.1}" \
  --port "${PORT:-8000}"
