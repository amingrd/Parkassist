# Parking Booking Internal Tool

A local-first internal parking booking tool that runs with only Python 3. It now includes:

- a calendar-first main view instead of a generic dashboard
- a quieter premium UI with only small best-practice transitions and reduced-motion support
- LM-specific inventory for `P5/P6` elevating car parks plus `P14-P21`
- name + email-confirmation sign-in flow for local prototype access
- hard rules for 1-week booking window, 3 days per work week, 2 consecutive days, and no same-day cancellation unless sick
- waitlist marketplace with automatic promotion when a spot is released
- admin tools for bans, rules, overrides, audit history, and notification events

## Run locally

```bash
python3 app.py
```

The app starts on `http://127.0.0.1:8000`.

## Login flow

- Enter your full name
- Enter your email twice to confirm it
- Existing users are matched by email
- New users are created locally as employees

Seeded admin:

- `Alex Morgan` / `alex.morgan@example.com`

## Local architecture

- `parking_app/server.py`: HTTP routing and calendar/dashboard composition
- `parking_app/services.py`: booking rules, cancellations, height checks, waitlist promotion
- `parking_app/repository.py`: SQLite persistence, LM spot inventory, user bans, and audit storage
- `parking_app/auth.py`: local cookie auth with an Okta-ready seam
- `static/style.css`: calmer translucent UI and garage visualizer styling
- `static/app.js`: minimal page-entry enhancement only

## Production follow-up

- Replace local auth with Okta OIDC or company SSO
- Swap the SQLite repository path for company-managed PostgreSQL
- Point `SLACK_WEBHOOK_URL` at a real Slack incoming webhook
- Add server-side CSRF/session hardening before broader internal rollout
- Replace the local email-confirmation step with real mailbox verification if needed
