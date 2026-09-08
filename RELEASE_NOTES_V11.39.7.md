# V11.39.7 — Opportunity Lifecycle & Coherent Shadow Book

This release combines the V11.39.6 execution-realistic Signal Lab with an
evidence-gated opportunity lifecycle. It remains research-only.

- Separates discovery, specialist verification, technical trigger and risk capacity.
- Tracks Core, SMID and Crypto sleeves independently.
- Uses next-session virtual fills with sleeve-specific costs and slippage.
- Sizes virtual positions from ATR risk, portfolio correlation, sector caps and a weekly risk budget.
- Applies deterministic stop, 2R target and 20-session time exits.
- Prevents duplicate virtual positions when multiple signals describe one opportunity.
- Persists an auditable Shadow Book and reports it in Investment Desk and Discord.
- Adds watchdog freshness and one bounded recovery attempt.
- Contains no broker integration and cannot create or transmit an order.

No backtest profitability is claimed. Results require forward evidence and
human review before any separate paper-trading integration is considered.
