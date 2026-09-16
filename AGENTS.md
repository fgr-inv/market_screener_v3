# Investment Desk agent rules

## Product boundary

- This repository is an investment research and virtual-simulation system.
- Never add broker connectivity, order submission, live execution, credential handling for brokerage accounts, or autonomous publication.
- Cash is a valid outcome. Missing, stale, or conflicting evidence must fail closed.
- Keep asset-specific models: equities, ETFs, fixed income, commodities, and crypto must not share one generic score.

## Architecture

- Keep financial calculations and policy gates deterministic and testable.
- Agents may research, classify, rank, explain, and verify; they may not silently change mandates, thresholds, risk limits, or production code.
- Preserve the separation between research, technical timing, portfolio risk, verification, CIO synthesis, and the journal.
- Use primary sources when a mandate requires an official catalyst. A technical setup alone cannot create an eligible idea.
- Every automated run must remain idempotent, auditable, bounded by API budgets, and explicit about data freshness.

## Verification

- Run `python -m compileall core views scripts` and the relevant pytest files after changes.
- Run `python scripts/run_quality_gate.py` before release.
- Do not weaken a test or governance boundary merely to make a change pass.
