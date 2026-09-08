# V11.39.5 — Compatibility repair

This release reconciles the Daily Technical Signal Lab with the later V11.39.1–V11.39.4 automation, persistence, market-calendar, UI and crypto-watchlist changes.

- Restores `CRYPTO_RESEARCH_WATCHLIST` with BTC, ETH, SOL, AAVE, ZEC and UNI.
- Preserves ZEC and UNI in the expanded Crypto view.
- Preserves resilient Postgres persistence, automation recovery, holiday-aware scheduling, expanded large/mid/small-cap discovery and current Discord reporting.
- Keeps Daily Technical Signal Lab and Weekly Champion/Challenger Review.
- Restores the Signal Lab UI and Automation Health checks on top of the current Investment Desk.
- Makes news freshness tests deterministic by accepting an explicit observation time.
- Keeps Shadow Mode and contains no broker/order path.

Validation: `293 passed` after applying the merged source and compiling all application modules.
