# ReturnReady 1.1

Live website: https://returnready-nuwz.onrender.com/

Previous launch verification (before release 1.0): 25 tests passed on SQLite and PostgreSQL in CI; 9 public end-to-end checks passed using an isolated disposable account and fictional receipt. Daily read-only health and CI monitoring is configured; confirmed code failures may receive tested minimal repairs. This is not continuous monitoring or an uptime guarantee.

A private purchase, receipt, return-deadline and warranty tracker for everyday use. Python/Django, PostgreSQL, responsive server-rendered pages. AI-assisted student project; no fabricated usage or impact figures.

## Working scope

- Username/password accounts, CSRF-protected forms, server-side sessions and single-use recovery codes.
- Purchase creation/editing, four currencies without misleading mixed-currency totals, search, due-soon filters, returned status.
- Private JPEG/PNG/PDF receipts in the persistent database. Image metadata stripped; PDFs attachment-only, not malware-scanned.
- User timezones, calendar exports with one-day-before alarms, CSV exports protected against spreadsheet formula injection.
- Reversible trash, confirmed permanent purchase deletion to reclaim storage, full ZIP download, password changes and explicit permanent account deletion.
- Database readiness endpoint, CI on SQLite and real PostgreSQL, reproducible free Render configuration.

## Run locally

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
DEBUG=1 .venv/bin/python manage.py migrate
DEBUG=1 .venv/bin/python manage.py runserver
DEBUG=1 .venv/bin/python manage.py collectstatic --noinput
DEBUG=1 .venv/bin/python manage.py test tracker
```

Local SQLite is for development only. Production refuses to start without a private SECRET_KEY and PostgreSQL DATABASE_URL. Configure Render Free and a dedicated Neon database/role; never reuse the OrderOps database role. Free hosting sleeps; reminders depend on the user's calendar, not a sleeping worker.

## Honest limits

100 free-plan accounts, 100 purchase records per account including trash, 10 receipts per account, 100 receipts globally, 2 MB upload limit. These are application caps, not a provider spending guarantee. CSV contains purchase metadata. Full ZIP backup includes active and trashed purchases plus receipt binaries; keep it privately. Automatic backup re-import is not supported. No OCR, email delivery, automatic retailer-policy lookup, bank integration, mobile app-store package, or uptime SLA. Keep original receipts elsewhere. An independent security audit has not been performed.

## Monitoring and repair

Check /healthz with up to 90 seconds for free-host cold starts. A single timeout does not prove an outage. Check CI for the deployed commit; reproduce a failure and fix the smallest relevant change without weakening tests. Never inspect customer receipts or alter their data during monitoring. Test using local isolated accounts and synthetic fixtures. Do not send reminders to other people or spend money.

## Release 1.0

Includes protected full ZIP backups, password-and-confirmation gated permanent deletion from trash, CSV zero/boolean preservation, explicit 12-megapixel and 2-MB image bounds, and a one-file multipart limit. Capacity remains bounded for the free plan. No schema changes are required for this release.

Rollback: redeploy the preceding known good commit after checking database compatibility. A rollback does not restore records that a user explicitly deleted. Download a backup before deletion; automatic restore/import is outside the supported scope. Keep provider credentials and database exports private.

## Deployment hardening

See [hardening scope](docs/HARDENING.md), [operator runbook](docs/OPERATIONS.md) and [security boundary](SECURITY.md). CI now also audits dependencies, produces an SBOM, verifies a synthetic PostgreSQL restore and builds/smoke-tests a non-root container. The current hosting remains bounded and free; enterprise availability and certification are not claimed.
