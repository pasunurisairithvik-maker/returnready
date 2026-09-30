# Deployment and recovery runbook

## Current deployment boundary
ReturnReady is a single-owner private vault with a bounded free deployment. Software hardening is implemented; enterprise uptime, compliance, SSO, MFA, centralized immutable audit retention, automated off-site backups and independent penetration testing are not claimed. Do not market the service as certified or highly available.

## Runtime
`python ops/start.py` validates production settings, applies forward migrations, removes expired sessions and obsolete rate counters, then starts Gunicorn. One worker and four threads are the defaults. `WEB_CONCURRENCY` and `WEB_THREADS` are bounded at 8 each; do not increase them without measuring database and memory capacity. Recycling workers every 500 requests, with jitter, limits accumulation. Existing free-plan capacity caps remain intentional.

Use the provider-assigned HTTPS hostname in `ALLOWED_HOSTS`; never use a wildcard. Preserve `SECRET_KEY` privately across deploys. Never enable DEBUG on the public service. Trust `X-Forwarded-Proto` only behind a proxy that removes client-supplied forwarding headers. Do not expose this Gunicorn listener directly to untrusted clients behind an incorrectly configured proxy.

The small Neon deployment uses direct sessions: a Neon `-pooler` hostname is normalized to the corresponding direct endpoint so PostgreSQL session timeouts are honored. SQL statements are limited to 15 seconds, lock waits to 5 seconds, idle transactions to 30 seconds; connection establishment has a 10-second timeout. Do not assume these settings work through an arbitrary transaction pooler. Migrations that exceed these limits fail and must be planned separately, rather than weakening live request limits without review.

## Health and errors
- `/livez`: process-only check, no database dependency.
- `/healthz`: verifies application table readiness, returns 503 when unavailable.
- Free hosting may take up to roughly a minute to wake; confirm with a bounded retry before declaring an outage. These checks do not establish an uptime SLA.
- Operational database failures in views return 503 with `Retry-After: 30`. Other unhandled faults return a generic error page, not a traceback.
- Every response includes a server-generated `X-Request-ID`. Logs contain route names, method, status and duration. They exclude paths, query strings, cookies, usernames, passwords, receipt contents and exception messages. Privileged purchases/backup/password/account actions emit allowlisted events. This is operational logging, not an immutable compliance audit trail.

## Deploy and rollback
1. Require green CI: SQLite/PostgreSQL tests, production checks, dependency audit, synthetic restore drill and non-root container smoke test.
2. Review migrations and storage/CPU/connection headroom before deployment. Never run tests against the operational database.
3. Deploy the reviewed commit. Confirm `/healthz`, `/livez` and essential browser workflows with disposable synthetic fixtures.
4. For code rollback, redeploy the preceding compatible commit; do not force push. Added nullable submission columns remain compatible with 1.0 code. Do not reverse migrations automatically or delete records to hide invalid data. Constraint validation failure requires an explicit, reviewed data-repair decision.
5. An old code deploy cannot undo a user's confirmed permanent deletion. Restoration is a separate recovery operation.

## Container
`docker build -t returnready:reviewed .` creates a multi-stage image running as UID/GID 10001, with no credentials in build arguments. Runtime secrets come from the deployment environment. For a local smoke test only: `docker run --rm -p 127.0.0.1:10000:10000 -e DEBUG=1 returnready:reviewed`. Production requires PostgreSQL, a strong private key, host configuration and a trusted TLS proxy. The CI smoke test checks development-mode startup; production settings and PostgreSQL behavior are separately checked. Rebuild base images regularly and scan their OS packages before enterprise adoption; the Python audit alone does not scan the container OS.

## Operator database backups
Install a PostgreSQL client at least as new as the server (currently use 18 for Neon PostgreSQL 18). Set `PG_BIN_DIR` to the directory containing matching `pg_dump` and `pg_restore` binaries (for example `/usr/lib/postgresql/18/bin` on Debian/Ubuntu); do not mix archive client versions. Keep a direct TLS `DATABASE_URL` in a private environment or secret manager. Never paste it into command arguments, logs or a public repository.

Create a private destination directory (`umask 077; mkdir -p backups`), then run:

```sh
python ops/db_backup.py backup backups/reviewed-snapshot.dump
```

The tool refuses overwrite, creates a mode-0600 custom-format archive, checks its table of contents and prints its SHA-256 and size. Protect the resulting file and hash separately. SHA-256 detects corruption; it is not encryption or proof of who produced the archive. Use trusted encryption and independent storage for operational backups. No operational backup is uploaded or enabled automatically by this repository.

For a safe drill, provision a fresh, empty database whose name ends in `_restore_drill`. Put its private direct TLS URL in `RESTORE_DATABASE_URL`, set `ALLOW_ISOLATED_RESTORE=1`, then:

```sh
python ops/db_backup.py restore backups/reviewed-snapshot.dump --sha256 VERIFIED_HASH
```

Restore never uses `--clean` and refuses an existing schema/data or a non-drill database name. Run against a disposable isolated destination, then verify rows and receipt binaries before designing a separately approved operational recovery. The safety naming gate is a guardrail, not authorization to use arbitrary credentials. Only trusted database archives may be restored: PostgreSQL archives can contain executable database definitions.

CI proves a full PostgreSQL dump/restore of fictional records and checks receipt bytes and purchase value. Its timing is a fixture observation, not a production RTO. CI never exports the operational database. Backup cadence, retention, encryption keys and actual RPO/RTO must be chosen and tested before enterprise rollout.

## Housekeeping and incidents
`python manage.py housekeeping` deletes only expired sessions and obsolete rate counters. It preserves live sessions, capacity lock rows, purchases and receipts. Startup invokes it; choose an external scheduler for more frequent cleanup if required. No paid scheduler is provisioned.

On an incident: capture request IDs and aggregate statuses; check deploy status and readiness; reproduce with synthetic data; use a compatible code rollback when justified. Never put private receipts, credentials or user-entered data into public issues. Restrict operator log access and define retention before adding a centralized sink. The current daily monitor is not 24/7 incident response.

## References
- Django deployment checklist: https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/
- OWASP logging guidance: https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html
- PostgreSQL backup/restore: https://www.postgresql.org/docs/18/app-pgdump.html and https://www.postgresql.org/docs/18/app-pgrestore.html
- PyPA dependency audit: https://github.com/pypa/pip-audit
