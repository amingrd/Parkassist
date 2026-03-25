#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${ROOT_DIR}/scripts/parameters.sh"

# Until the rollout account is wired in, feature/main CI should not attempt
# to install private deploy dependencies or synth against a real AWS account.
if [[ -z "${AWS_ACCOUNT_ID}" ]]; then
  echo "AWS_ACCOUNT_ID is not configured; skipping CDK synth until rollout infrastructure is configured."
  exit 0
fi

cd "${ROOT_DIR}/deploy"
if [[ -f package-lock.json ]]; then
  npm ci
else
  npm install
fi

npx cdk synth "${CDK_CONTEXT_ARGS[@]}"
