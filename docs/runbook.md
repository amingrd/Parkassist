# ParkAssist runbook

## Service summary

ParkAssist is an internal parking booking service for LeasingMarkt employees. It manages parking inventory, booking rules, waitlists, and operational notifications.

## Dependencies

- Infinity runtime
- Okta OIDC
- Aurora PostgreSQL
- Slack webhook for notifications
- Optional SMTP relay

## Primary user flows

- employee authentication through Okta
- booking creation and cancellation
- waitlist promotion after cancellations
- admin rule and user management

## Health checks

- `GET /health`
- `GET /health/liveness`
- `GET /health/readiness`

Expected response:

```json
{
  "status": "ok",
  "probe": "/health",
  "auth_mode": "okta",
  "database_backend": "postgresql",
  "app_env": "production"
}
```

## Logs

HTTP access logging is emitted as JSON to standard error. Infinity should collect and retain these logs centrally.

## SLO starter

- Availability: 99.5% monthly for internal business hours
- Booking actions: 95% of booking or cancellation requests complete within 2 seconds

## Alarms to configure

- service unavailable or failing health checks
- elevated 5xx responses
- PostgreSQL connectivity failures
- waitlist promotion failures
- Slack delivery failures above agreed threshold

## Common incidents

### Okta sign-in failures

Check:

- `OKTA_ISSUER`
- `OKTA_CLIENT_ID`
- `OKTA_CLIENT_SECRET` or `OKTA_CLIENT_SECRET_PARAMETER`
- redirect URI registration

### Database connection failures

Check:

- `DATABASE_URL` or `DATABASE_SECRET_ID`
- Aurora security groups and subnet routing
- SSL configuration in the connection string
- application IAM access to Secrets Manager when secrets are used

### Notifications not delivered

Check:

- `SLACK_WEBHOOK_URL` or `SLACK_WEBHOOK_URL_PARAMETER`
- outbound network access from the workload
- notification event records in `notification_events`

## Rollback

1. Identify the previously healthy image tag in the deployment workflow summary or container registry.
2. Re-deploy that known-good image through the Infinity deployment process.
3. Validate `/health`, Okta login, and a non-destructive booking read path.
4. If the issue is schema related, stop rollout and restore from the latest tested Aurora backup before retrying.

## Backup and restore

- Aurora automated backups must be enabled.
- Restore testing must be performed before launch and after any significant schema change.
- Snapshots must remain private.

## Data handling

Stored internal data includes:

- employee names
- employee emails
- booking and waitlist history
- guest contact data when users create guest bookings

Review GDPR/internal data handling before launch and document retention expectations.
