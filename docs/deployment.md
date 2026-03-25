# ParkAssist deployment notes

## Target platform

- Runtime: Infinity internal service
- Region: `eu-west-1`
- Identity: Okta OIDC with MFA
- Database: Aurora PostgreSQL in private subnets
- Notifications: Slack in phase 1, optional SMTP afterwards
- Exposure: `loadBalancerExposure: 'internal'`

## Runtime modes

- Local development
  - `AUTH_MODE=local`
  - SQLite database under `runtime/data/parking.db`
  - Demo seed data enabled by default
- Internal AWS
  - `AUTH_MODE=okta`
  - PostgreSQL connection from `DATABASE_URL` or `DATABASE_SECRET_ID`
  - Demo seed data disabled

## Config split

Use Infinity `containerEnvironment` only for non-sensitive values:

- `APP_ENV`
- `HOST`
- `PORT`
- `BASE_URL`
- `AUTH_MODE`
- `AWS_REGION`
- `OKTA_ISSUER`
- `OKTA_CLIENT_ID`
- `OKTA_REDIRECT_URI`
- `BOOTSTRAP_ADMIN_EMAILS`
- `PARKING_GUIDE_URL`

Do not put secrets into `containerEnvironment`.

Infinity already injects:

- `DD_AGENT_HOST`
- `DD_ENTITY_ID`

Use AWS SSM Parameter Store or Secrets Manager for:

- `SESSION_SECRET`
- `OKTA_CLIENT_SECRET`
- `SLACK_WEBHOOK_URL`
- SMTP password, if SMTP is enabled
- Aurora PostgreSQL credentials

## Supported secret patterns

The app can resolve secrets from either direct values or AWS references:

- direct env vars such as `SESSION_SECRET`
- SSM parameter references such as `SESSION_SECRET_PARAMETER`
- a Secrets Manager JSON document via `DATABASE_SECRET_ID`

`DATABASE_SECRET_ID` expects a JSON payload with at least:

- `host`
- `port`
- `dbname` or `database`
- `username`
- `password`

## Docker

Build locally:

```bash
docker build -t parkassist:local .
```

Run locally with Okta disabled:

```bash
docker run --rm -p 8000:8000 \
  -e APP_ENV=local \
  -e AUTH_MODE=local \
  -e SESSION_SECRET=dev-session-secret \
  parkassist:local
```

## GitHub Actions

- `ci.yaml` runs the Python checks, builds the Docker image, pushes it to ECR when AWS variables are configured, and synthesizes the CDK app.
- `cd.yaml` deploys the Infinity and Aurora stacks after CI succeeds on `main`, or on manual trigger.
- `bootstrap.yaml` is the one-time workflow for GitHub Actions OIDC roles.

The scripts the workflows call live under `scripts/`.

## Deploy structure

- `deploy/bin/index.ts` bootstraps the CDK app
- `deploy/lib/service.ts` defines the Infinity service
- `deploy/lib/database.ts` defines Aurora PostgreSQL
- `deploy/lib/github-actions-roles.ts` defines GitHub Actions roles

These files follow the platform team’s recommended shape and may need small final alignment against the exact current `as24-templates` or `@autoscout24/aws-cdk` version in your target account.

## Health endpoint

The container exposes:

- `GET /health`
- `GET /health/liveness`
- `GET /health/readiness`

The response includes:

- runtime status
- probe path
- auth mode
- database backend
- environment label
