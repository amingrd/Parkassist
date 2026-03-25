#!/usr/bin/env bash
set -euo pipefail

export SERVICE_NAME="${SERVICE_NAME:-parkassist}"
export APP_ENV="${APP_ENV:-dev}"
export AWS_REGION="${AWS_REGION:-eu-west-1}"
export AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-}"
export IMAGE_TAG="${IMAGE_TAG:-${GITHUB_SHA:-local-dev}}"
export ECR_REPOSITORY="${ECR_REPOSITORY:-$SERVICE_NAME}"
export GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-amingrd/Parkassist}"
export CDK_CONTEXT_ARGS=(
  -c "serviceName=${SERVICE_NAME}"
  -c "environment=${APP_ENV}"
  -c "region=${AWS_REGION}"
  -c "awsAccountId=${AWS_ACCOUNT_ID}"
  -c "imageTag=${IMAGE_TAG}"
  -c "repositoryFullName=${GITHUB_REPOSITORY}"
)
