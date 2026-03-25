# ParkAssist

ParkAssist is an internal parking booking tool for LeasingMarkt. The app supports:

- week-based parking reservations
- rule enforcement for weekly and consecutive booking limits
- guest bookings and waitlists
- admin management for users and rules
- Slack notifications
- local development with SQLite
- internal AWS deployment with Okta and PostgreSQL

## Local development

The default local mode keeps the existing prototype experience:

- local sign-in and registration
- SQLite database under `runtime/data/parking.db`
- demo data enabled by default

Start the app:

```bash
python3 app.py
```

Optional environment file:

```bash
cp .env.example .env
```

## Runtime modes

### Local

Recommended for feature work:

```bash
AUTH_MODE=local
APP_ENV=local
SEED_DEMO_DATA=true
```

### Internal AWS

Recommended for Infinity:

```bash
AUTH_MODE=okta
APP_ENV=production
AWS_REGION=eu-west-1
```

Use:

- `DATABASE_URL` or `DATABASE_SECRET_ID` for Aurora PostgreSQL
- `SESSION_SECRET` or `SESSION_SECRET_PARAMETER`
- `OKTA_CLIENT_SECRET` or `OKTA_CLIENT_SECRET_PARAMETER`
- `BOOTSTRAP_ADMIN_EMAILS` for the first admin assignment after SSO login
- `SLACK_WEBHOOK_URL` or `SLACK_WEBHOOK_URL_PARAMETER`

Non-secret config belongs in Infinity `containerEnvironment`. Secrets should stay in AWS SSM Parameter Store or Secrets Manager.

## Docker

Build:

```bash
docker build -t parkassist:local .
```

Run:

```bash
docker run --rm -p 8000:8000 \
  -e APP_ENV=local \
  -e AUTH_MODE=local \
  -e SESSION_SECRET=dev-session-secret \
  parkassist:local
```

## Health and tests

Health endpoint:

```text
GET /health
```

Tests:

```bash
python3 -m py_compile app.py parking_app/*.py tests/*.py
python3 -m unittest discover -s tests -v
```

## Deployment support files

- `Dockerfile`
- `deploy/bin/index.ts`
- `deploy/lib/service.ts`
- `deploy/lib/database.ts`
- `deploy/lib/github-actions-roles.ts`
- `scripts/parameters.sh`
- `scripts/build.sh`
- `scripts/synth.sh`
- `scripts/deploy.sh`
- `.github/workflows/ci.yaml`
- `.github/workflows/cd.yaml`
- `.github/workflows/bootstrap.yaml`
- `catalog-info.yaml`
- `docs/deployment.md`
- `docs/runbook.md`
- `docs/launch-readiness.md`

## Current AWS rollout posture

This repo is now prepared for the platform-recommended path:

- Infinity-hosted internal runtime
- Okta SSO
- Aurora PostgreSQL in private subnets
- Slack notifications for phase 1
- secrets from SSM / Secrets Manager
- Infinity CDK scaffolding under `deploy/`
- GitHub Actions split into `ci`, `cd`, and `bootstrap`

The remaining gaps are values, not structure: Okta registration details, actual secret/parameter names, dashboard/alarm targets, and final validation of the exact `@autoscout24/aws-cdk` construct props against the current template version in your AWS account.
