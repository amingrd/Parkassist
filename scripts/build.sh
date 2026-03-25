#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${ROOT_DIR}/scripts/parameters.sh"

cd "${ROOT_DIR}"
python3 -m py_compile app.py parking_app/*.py tests/*.py
python3 -m unittest discover -s tests -v
docker build -t "${SERVICE_NAME}:${IMAGE_TAG}" .
