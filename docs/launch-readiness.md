# Launch readiness

Use this list before moving ParkAssist from prototype to internal production use.

## Platform and delivery

- Infinity runtime is provisioned in `eu-west-1`
- internal-only exposure is confirmed
- CI/CD deploys from GitHub Actions with no manual production edits
- ECR image publishing is working

## Identity and security

- Okta app registration is complete
- MFA is enforced through Okta
- session secret is stored outside the repo
- runtime secrets are stored in SSM or Secrets Manager
- Infinity role has least-privilege IAM access only

## Database

- Aurora PostgreSQL is provisioned in private subnets
- `publiclyAccessible` is `false`
- snapshots are private
- auto minor version upgrades are enabled
- backup retention and restore testing are documented

## Operations

- `catalog-info.yaml` is registered
- `/health` is monitored
- logs are retained centrally
- alarms are defined and routed
- runbook exists and has rollback steps
- SLOs are defined

## Product readiness

- Slack notifications are configured
- local demo auth is disabled in deployed environments
- seed data is disabled in deployed environments
- booking, waitlist, and admin flows are tested against PostgreSQL

## Compliance and ownership

- service owner is confirmed
- cost ownership is defined
- GDPR review is complete
- guest email handling has been reviewed internally
