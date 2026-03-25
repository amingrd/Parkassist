#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${ROOT_DIR}/scripts/parameters.sh"

cd "${ROOT_DIR}/deploy"
if [[ -f package-lock.json ]]; then
  npm ci
else
  npm install
fi

# Feature branches can validate the deploy code before the AWS account,
# OIDC bootstrap, and lookup permissions are wired in. Once the rollout
# variables exist, we synthesize against the real target account.
if [[ -z "${AWS_ACCOUNT_ID}" ]]; then
  echo "AWS_ACCOUNT_ID is not configured; running TypeScript validation and skipping CDK synth."
  npm run build
  exit 0
fi

npx cdk synth "${CDK_CONTEXT_ARGS[@]}"
