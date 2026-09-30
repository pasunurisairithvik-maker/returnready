# Hardening release 1.1

Implemented: database invariants, owner-scoped duplicate browser submission handling, canonical authentication rate keys, sensitive-action rate limits, JSON operational logs with request IDs and private-data exclusion, generic errors and retryable database failures, distinct liveness/readiness, bounded database waits, non-root Docker packaging, validated startup and worker recycling, safe expired-session cleanup, dependency auditing/SBOM in CI, and a synthetic PostgreSQL backup/restore drill.

The release expands the software's deployment controls. It does not turn the current free single-instance hosting into redundant infrastructure. Before enterprise use, define supported traffic and recovery objectives; independently test security; configure encrypted off-site backups and restore rehearsals; arrange continuous monitoring and incident response; and decide whether organization login, MFA, access roles and compliance controls are required. No money is spent or new access granted by this release.

Verification is recorded in the commit's GitHub Actions run. A skipped PostgreSQL concurrency test is not a pass; the PostgreSQL job must run it. Container smoke tests prove build/non-root startup only, not production load capacity. Review [OPERATIONS.md](OPERATIONS.md) and [SECURITY.md](../SECURITY.md) before deployment.
