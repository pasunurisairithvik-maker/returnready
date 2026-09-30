# ReturnReady

A private purchase, receipt, return-deadline and warranty tracker for everyday use. Python/Django, PostgreSQL, responsive server-rendered pages. AI-assisted student project; no fabricated usage or impact figures.

## Working scope

- Username/password accounts, CSRF-protected forms, server-side sessions and single-use recovery codes.
- Purchase creation/editing, four currencies without misleading mixed-currency totals, search, due-soon filters, returned status.
- Private JPEG/PNG/PDF receipts in the persistent database. Image metadata stripped; PDFs attachment-only, not malware-scanned.
- User timezones, calendar exports with one-day-before alarms, CSV exports protected against spreadsheet formula injection.
- Reversible trash, password changes and explicit permanent account deletion.
- Database readiness endpoint, CI on SQLite and real PostgreSQL, reproducible free Render configuration.

## Run locally

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
DEBUG=1 .venv/bin/python manage.py migrate
DEBUG=1 .venv/bin/python manage.py runserver
DEBUG=1 .venv/bin/python manage.py test
```

Local SQLite is for development only. Production refuses to start without a private SECRET_KEY and PostgreSQL DATABASE_URL. Configure Render Free and a dedicated Neon database/role; never reuse the OrderOps database role. Free hosting sleeps; reminders depend on the user's calendar, not a sleeping worker.

## Honest limits

100 beta accounts, 100 purchase records per account including trash, 10 receipts per account, 100 receipts globally, 2 MB upload limit. These are application caps, not a provider spending guarantee. CSV does not include receipt binaries; download receipts individually. No OCR, email delivery, automatic retailer-policy lookup, bank integration, mobile app-store package, or uptime SLA. Keep original receipts elsewhere. An independent security audit has not been performed.

## Monitoring and repair

Check /healthz with up to 90 seconds for free-host cold starts. A single timeout does not prove an outage. Check CI for the deployed commit; reproduce a failure and fix the smallest relevant change without weakening tests. Never inspect customer receipts or alter their data during monitoring. Test using local isolated accounts and synthetic fixtures. Do not send reminders to other people or spend money.
