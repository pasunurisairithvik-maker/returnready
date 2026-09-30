# Security boundary

ReturnReady uses account ownership checks, HTTPS/secure cookies, CSRF protection, private attachment downloads and bounded storage. Owner-scoped form submission nonces protect browser purchase creation from duplicate retries; clients that omit a nonce do not receive that guarantee. A changed payload with the same nonce is rejected. Permanent deletion also removes the retained nonce; old forms must not be resubmitted after deletion.

Database constraints reject negative amounts, invalid date ordering, unsupported states/currencies and oversized or unsupported receipt types. This supplements form validation; it does not sanitize arbitrary database imports. TLS is required for external PostgreSQL. Authentication keys canonicalize whitespace, case and Unicode normalization; global and per-identity rate gates bound attempts. Password changes and account deletion have additional limits.

Do not load or upload private production data to CI. Do not commit keys, dumps, session cookies, receipt archives or real usernames. A sanitized issue may describe a reproducible defect using invented data; never include a working exploit against another user, credentials or private records. For sensitive disclosures, first agree on a private communication channel with the owner; no public contact address is invented here.

No independent penetration test, compliance certification, MFA/SSO integration, immutable audit store or enterprise SLA is claimed. Python dependency scanning does not prove absence of vulnerabilities and does not scan container OS packages. Do not disable failing tests, remove safeguards, or ignore vulnerability findings simply to make CI green.
