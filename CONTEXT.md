# Investment Desk context

Market Screener Pro is a Python/Streamlit investment desk for opportunity discovery, asset analysis, comparison, watchlists, portfolio context, alerts, and decision support.

It covers equities, ETFs, fixed income, commodities, and crypto with asset-specific analysis. Public and free data sources are preferred, with caching, freshness controls, rate limits, and duplicate-call prevention.

The US-equity catalyst workflow uses `config/mandates/us_equities_catalyst.json`. It is long-only research plus internal virtual simulation. It requires a fresh official catalyst, specialist evidence, a technical entry condition, multi-timeframe confirmation, and available risk capacity. It never connects to a broker.

The virtual Shadow Book is an evaluation ledger, not an account. Its fills, stops, exits, returns, and NAV are simulated measurements used to validate the process.
