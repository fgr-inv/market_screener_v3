# V11.39 — Daily Technical Signal Lab

## Outcome

Market Screener Pro now builds forward evidence for explicit technical setups without changing production behavior. It records virtual signals every weekday and reviews Champion/Challenger variants weekly.

## Daily experiment

- Balanced coverage of the active desk list, portfolio, large caps, S&P MidCap 400, S&P SmallCap 600 and selected cross-assets.
- Setup families: breakout + RVOL, EMA pullback, rolling volume-weighted price reclaim, DMI/ADX onset, volatility expansion, contextual engulfing candles and relative strength versus SPY.
- Frozen signal inputs and idempotent signal keys.
- Outcomes at 1, 3, 5, 10 and 20 trading days.
- Return, SPY-relative alpha, MFE and MAE.
- Partial provider failures remain visible without discarding valid ticker results.

## Weekly review

- Chronological train/validation split.
- At least 30 matured primary-horizon outcomes, 10 validation observations and 5 unique tickers per eligible variant.
- Champion/Challenger comparison with return, alpha, hit rate and adverse-excursion guards.
- A challenger may create a `HUMAN_REVIEW_REQUIRED` proposal only.

## Safety and operations

- Shadow Mode only; no broker or order path.
- No automatic rule, threshold, model, ranking or code changes.
- Existing bounded confidence calibration remains separate.
- One bounded, user-scoped ledger update avoids adding a second SQLite database or one database write per signal.
- Daily and weekly heartbeats are included in Automation Health.
- Discord reports are deduplicated by run key.

## Validation

- `python -m compileall -q app.py core views scripts tests`
- `python -m pytest -q`
- Result: **270 passed**.

No performance or backtest result is claimed. The lab begins accumulating true forward observations only after deployment.
