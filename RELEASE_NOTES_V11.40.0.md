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

## Developed notification analysis

- Saved asset alerts now explain market structure, score context, participation, risk, portfolio context, confirmation and invalidation in narrative form.
- Material and daily CIO reports open with an executive interpretation and connect confidence, verification and evidence instead of presenting isolated labels or scores.
- The macro and sector report remains the writing standard: evidence first, explicit uncertainty, and conditions under which the reading improves or deteriorates.

## Persistent agent operating layer

- Every desk run now creates a versioned Research Packet manifest so specialists share the same frozen data, freshness state and source inventory.
- Agent handoffs and workflow states are persisted with explicit partial, stale, rejected and failed outcomes; missing evidence cannot silently become a complete result.
- Thesis memory is versioned per asset and records prior conclusions, contradictions and sources without modifying the user's thesis.
- CIO briefs compare themselves with the previous comparable run and highlight only material changes.
- Investment Desk exposes workflow tasks, handoffs, packet identity and persistent thesis memory for human review.
- Agent permissions and reporting lines are explicit; every role remains research-only, non-publishing and non-executing.

## Evidence-backed agent playbooks

- Added atomic `WHEN/THEN` playbook entries derived only from matured Shadow outcomes.
- Every entry records hits, misses, sample size, unique tickers, confidence, evidence references and its primary validation horizon.
- Playbooks use append/amend delta operations (`ADD`, `HIT`, `MISS`, `AMEND`, `PRUNE`) and forbid bulk rewrites.
- Active entries provide narrative context only; they cannot alter signals, thresholds, theses, code, portfolio rules or execution.
- CIO market, portfolio, opportunity and decision blocks now use analyst-style explanations instead of internal status strings.
- Saved technical alerts explain trend, participation, relative strength, risk levels, portfolio fit, confirmation and invalidation in complete sentences.
