# V11.40.0 — Agent Fleet Hardening

- Verification Agent V1.1 validates evidence values, sources and timestamps before trusting a `CURRENT` label.
- Fixed zero-value fundamental scores and missing technical values; technical calculation failures now fail closed.
- Fundamental snapshots persist in PostgreSQL, preserving the seven-day API budget across GitHub Actions workers.
- Every desk run uses one shared immutable context and one bounded price request.
- Webhook report delivery records completed parts and resumes without duplicating prior messages.
- Added a provider-neutral grounded narrator gate with deterministic fallback on invented numbers, missing sectors or unsupported references.
- Added a weekly Journal Agent with per-agent outcome metrics and recurring weakness detection. It cannot modify rules.
- All workflows share one Python setup action; the release quality gate now scans every Core and Scripts Python module for prohibited execution paths.
- The fleet registry explicitly assigns ownership while keeping `may_execute=False` for every agent.

The system remains research-only, broker-free and in Shadow Mode.
