# V11.39.6 — Realistic Signal Validation

The Technical Signal Lab now uses an executable, deliberately conservative forward methodology.

- A setup is detected only after its signal bar closes.
- The virtual entry occurs at the next session open, including adverse slippage.
- Round-trip commission is deducted.
- Each experiment uses a 1.5 ATR initial stop and a 2R target.
- Opening gaps through a level are filled at the next observed opening price.
- If one daily bar touches stop and target, the stop is assumed first because OHLC cannot establish intrabar order.
- MFE and MAE stop accumulating when the virtual trade exits.
- Simultaneous triggers for one ticker/date/direction share one independent opportunity key and expose their confluence.
- Asset trend, SPY regime and volatility regime are frozen at signal time.
- Weekly evidence is separated by setup version and market regime. V1 close-entry outcomes are not mixed with V2 evidence.
- Structural changes remain `HUMAN_REVIEW_REQUIRED`; no strategy, ranking, portfolio or order changes automatically.

Validation: **296 tests passed** before packaging. No performance result is claimed until new V2 signals mature prospectively.
