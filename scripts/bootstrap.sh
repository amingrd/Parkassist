#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${ROOT_DIR}/scripts/parameters.sh"

cd "${ROOT_DIR}/deploy"
npm ci
npx cdk deploy GithubActionsRolesStack "${CDK_CONTEXT_ARGS[@]}" --require-approval never
