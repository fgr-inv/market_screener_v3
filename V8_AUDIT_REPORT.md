# V8 Production Hardening — Audit Report

This build was created from the uploaded `market_screener_v3-main.zip`.

## Critical issues addressed

1. **Alert persistence split-brain**
   - V7 could read `data/alerts.csv` in GitHub Actions while Streamlit wrote DuckDB locally.
   - V8 uses the same storage API everywhere, prefers Postgres/Supabase when `DATABASE_URL` is configured, and keeps GitHub CSV as fallback.

2. **Repeated alerts every hour**
   - Added persistent alert state and edge-triggering.
   - Default behavior: notify only on `FALSE -> TRUE`.
   - Optional `repeat_while_true` obeys a configurable cooldown.

3. **Missing data treated as neutral**
   - Opportunity model no longer silently substitutes missing revisions/valuation/RS with 50.
   - Available weights are re-normalized.
   - Added `Model_Coverage_%` and action gating for incomplete data.

4. **Confidence mixed with alpha factors**
   - V8 removes confidence from the alpha score.
   - Confidence now describes data/model trust and gates actions.

5. **Portfolio weight != portfolio risk**
   - Added covariance-based component risk contribution.
   - Added CVaR, historical drawdown, standalone volatility and Risk/Weight.

6. **Hidden thematic concentration**
   - Added cross-sector theme exposure (AI, data centers, power/electrification, crypto, etc.).

7. **Score factor double-counting risk**
   - Factor Lab now includes score correlation and redundant-factor diagnostics.

8. **No investment thesis persistence**
   - Added Thesis Tracker to Portfolio with thesis, catalysts, invalidation, target, review date and status.

9. **Silent operational errors**
   - Added structured error logging and surfaced it in System Health.
   - Core refresh and market-data failures are logged rather than silently swallowed.

10. **Workflow maintenance**
    - Upgraded GitHub Actions to Node-24-ready major versions.
    - Added pip cache, concurrency and timeouts.

## Validation performed

- `python -m compileall -q .` — passed.
- `pytest -q` — **28 passed** in the build environment for deterministic tests.
- Runtime integration with Streamlit/DuckDB was not executable in the artifact container because those packages are not installed there; they are declared in `requirements.txt` and are installed by Streamlit/GitHub Actions during deployment.

## Remaining institutional limitations

These are data-provider limitations, not missing UI features:

- true point-in-time analyst estimates/revisions;
- historical index constituents for unbiased universe backtests;
- institutional dealer gamma/GEX history;
- securities-lending/borrow-cost history;
- full futures curves/COT/inventory history across all commodities;
- complete ETF/crypto flow history;
- production-grade centralized logs/metrics service.

The application deliberately reports missing coverage rather than fabricating these datasets.

V8.6 adds free specialist SEC EDGAR, ClinicalTrials.gov, openFDA and scored CFTC positioning integrations.

## V8.8 professional equity-industry upgrade

V8.8 adds `core/professional_equity_engine.py` and changes the equity research path from broad sector weights to business-model-specific research profiles.

The new engine explicitly separates:
- business-model classification;
- professional KPI expectations;
- fundamental quality;
- valuation methodology;
- comparable-peer grouping;
- catalysts;
- risks;
- model coverage vs specialist data coverage.

It also changes equity opportunity weights for selected models (for example SaaS, memory, banks, biotech, E&P, copper/gold miners, utilities and data-center REITs), because macro, revisions, valuation and quality do not deserve identical weights in every industry.

Professional peer valuation is now based on the detected sub-industry rather than only broad sector P/E. It combines available P/E, EV/EBITDA, P/B, sales multiples and FCF yield only when appropriate and when enough peers exist. Biotech valuation intentionally reports low coverage without observed rNPV/pipeline valuation data.

Validation for this build:
- compileall passed;
- **52 deterministic tests passed** with a temporary Streamlit stub because Streamlit is not installed in the artifact container;
- live API connectivity was not asserted and should be checked in deployed System Health.

## V8.9 crypto decision-engine hardening
- Replaced one-dimensional crypto entry logic with regime-aware cycle + execution analysis.
- Separates Structural Trend, Cycle, Long-Term Opportunity, Entry Timing, Overextension Risk, Leverage Risk and Cycle Risk.
- Adds breakout/price-discovery, trend-continuation and pullback/accumulation entry archetypes.
- High RSI or distance from EMA is no longer an automatic bearish/trim condition during confirmed bull expansion.
- Crypto opportunity scoring gives long-term/cycle structure more weight than exact short-term timing.
- Crypto action labels no longer default to EXTENDED/TRIM solely because momentum is strong.
- New ATH remains a scenario, never an assumption or guarantee.

## V8.10 audit — research workstation

Added a professional research layer without changing the free-data-only policy. The new engine separates peer benchmarking, revisions, catalysts, and scenario valuation from the underlying Opportunity Score. This avoids double-counting analyst targets or scenario outputs as if they were independent alpha factors.

Validation: `compileall` passed and 58 tests passed under the temporary Streamlit cache stub required by the execution environment. External-provider connectivity was not live-validated here and should still be checked from the deployed System Health view.

## V9.0 institutional extension

Added institutional valuation, financial forensics, macro regime, commodity physical-market aggregation, factor/portfolio intelligence, options integration and thesis generation. The design keeps alpha/opportunity, confidence, data coverage and scenario analysis separate. Reverse DCF is used to expose what growth current enterprise value requires; DCF scenarios are transparent assumption ranges rather than guaranteed price targets. Historical multiple percentiles are deliberately not backfilled using current fundamentals because that would introduce look-ahead bias.

## V10.0 audit addendum

V10 introduces a zero-cost point-in-time and model-validation layer. Macro history can use FRED/ALFRED vintages. SEC EDGAR remains the authoritative free filing/XBRL source, and EIA remains the free-key physical-energy source. The platform does not claim free historical analyst consensus, dealer GEX, complete exchange/on-chain history, or historical ETF holdings when a reliable point-in-time feed is unavailable. Such fields are represented as missing/coverage gaps and may be accumulated prospectively.

New controls: immutable snapshots, source/freshness lineage, missing-aware relative value, ETF look-through coverage, event-study primitives, probability calibration, and explicit signal disagreement.

## V11.0 audit addendum — complete free-data professional layer

Added architecture for the remaining zero-cost professional-analysis domains: institutional/insider/fund filing discovery, short-market contracts, additional official macro sources, community crypto network data, BTC mining/mempool data, historical COT/curve analysis, fundamental acceleration and forensics, capital-allocation/moat proxies, fixed-income and FX regime drivers, crypto liquidity/token dilution, global relative value, execution quality, regime correlations, stress testing, source reconciliation, lineage, walk-forward validation, probability calibration, attribution and model drift.

Important governance constraint: a connector contract is not the same as guaranteed live coverage. Network/API schemas and provider rate limits can change. Live connectivity must be checked in the deployed app; unavailable datasets remain MISSING and do not receive neutral scores.


## V11.3 — Equity enrichment pipeline hardening
- Professional Screener enrichment stages now fail independently instead of silently dropping all fundamental/revision scores.
- Yahoo `.info` failures fall back to Yahoo financial statements; FMP and SEC are independent fallbacks/enrichers.
- Cached fundamental errors are retried rather than reused indefinitely.
- Revision score receives the analyst engine fallback even when optional analyst tables are unavailable.
- Standalone valuation no longer manufactures a neutral 50 when no valuation evidence exists.
- Diagnostic status/source fields are stored per enriched ticker for troubleshooting.


## V11.4 — Empty equity scores root-cause fix
- Equity forward enrichment is always enabled for the Professional Screener; it can no longer be accidentally disabled while professional columns remain visible.
- Removed stale/empty session-cache bypass: `get_fundamentals()` is called directly and relies on its own TTL cache.
- Added per-provider status (`YahooInfo`, `YahooStatements`, `FMP`, `SEC`) to the fundamental payload.
- Added a final rescue pass for candidate equities: analyst score falls back to 50/NEUTRAL, quality falls back to the observed fundamental score, and valuation is retried from observed multiples.
- No fabricated quality/valuation values are inserted when there is no observed evidence.
- Validation: compileall passed; 80 tests passed with temporary Streamlit/yfinance test stubs in this execution environment.


## V11.5 — Faster Professional Screener
- Two-stage scan: fast price/technical/macro ranking over the full universe, then deep fundamentals/revisions/events only for the top N candidates.
- Bounded parallel deep enrichment (1–8 workers; default 4) to reduce wall-clock latency while respecting free/public provider limits.
- Persistent disk cache for deep data: fundamentals 6h, analyst data 1h, earnings/event data 30m.
- Analyst earnings date is reused to avoid a duplicate Yahoo calendar request whenever possible.
- Optional force-refresh and cache-clear controls.
- Per-stage timing diagnostics and per-ticker deep-fetch/cache diagnostics.
- No missing value is fabricated: caching changes latency only, not evidence rules.

## V11.6 — Analysis-type separation
- Professional Screener now exposes analysis type separately from depth.
- `Técnico`: zero deep equity enrichment calls; ranks by Technical Score.
- `Fundamental`: uses the fast market pass only to select candidates, then ranks enriched candidates by observed Quality/Valuation/Revisions.
- `Combinado`: keeps full Opportunity Score workflow.
- Technical `Rápido` skips the professional TA layer; `Balanceado` enables it; `Profundo` uses 5y history where available and gives stronger weight to structure/weekly/participation confirmation.
- This materially reduces provider/API pressure for technical-only scans.


## V11.7 — Specialized screener pages + context/peer valuation repair
- Professional Screener is split into Technical Screener, Fundamental Screener and Combined Screener.
- All three pages use one shared screener engine (`views/screener_shared.py`) to avoid duplicated scoring logic.
- Technical Screener never enables SEC/FMP/fundamental/analyst deep enrichment for equities.
- Scan results are stored per screener mode while the latest scan remains compatible with Decision Center.
- Equity `Asset_Context_Score` is now a local, missing-aware blend of sector strength, macro fit, relative strength and trend; it requires no extra API calls.
- `PE_Sector_Percentile` now uses the observed sector peer set when at least two P/E observations exist and transparently falls back to the enriched universe for singleton sectors. `PE_Percentile_Source` and `PE_Peer_Count` expose the evidence source.


## V11.8 - Specialized screener result persistence fix
- Fixed specialized Technical/Fundamental/Combined pages showing a completed scan but no table.
- The shared screener now persists both `scan_results` and the page-specific `scan_results_tecnico`, `scan_results_fundamental`, or `scan_results_combinado` key used by the renderer.
- If the scan has data but the preliminary setup filter removes every row, the UI now explains that explicitly and offers an expander with unfiltered top results.
- Regression coverage added for mode-specific result persistence.


## V11.9 - Mode-specific screener presentation
- Technical Screener now renders only technical/context columns and never shows fundamental score columns.
- Fundamental Screener now renders only fundamental/valuation/revision/coverage columns and hides technical indicator tables.
- Combined Screener keeps the integrated technical + fundamental view.
- Secondary tables and empty-result previews are also mode-specific, preventing stale or irrelevant fields from appearing on the wrong page.

## V11.10 - Fundamental ranking semantics and peer fallback

Resolved two interpretation/data-coverage issues in the equity fundamental screener. Fundamental leaders and current fundamental opportunities are now separate rankings, and peer ranking no longer disappears simply because too few exact business-model peers survived the current enrichment batch. Peer benchmarking falls back hierarchically to industry, sector, then the enriched universe, with source/count exposed for auditability. No missing company metric is fabricated.

## V11.11 audit addendum - cache/freshness policy
The application now separates cache freshness by data velocity. Corporate accounting fundamentals are cached for seven days, analyst/event metadata for twelve hours, FRED for twelve hours, prices/news/options on intraday horizons, and a central policy module documents the intended TTLs. Asset Analysis consumes the shared persistent deep bundle, preventing session-local caches from silently outliving the documented fundamental TTL. Event-driven invalidation remains a future enhancement; manual force refresh is supported where exposed.


## V11.12 audit addendum - live quote vs historical bars
Price freshness is now split into separate layers. A single-asset live quote is cached for five minutes, while multi-year daily OHLCV remains cached for sixty minutes. Asset Analysis overlays the live quote without forcing a historical redownload. This reduces stale displayed prices while avoiding a proportional increase in Yahoo historical calls. Technical TTL is documented at fifteen minutes; no missing quote is fabricated if Yahoo cannot provide one.

### V11.15 access-control hardening
- Added FREE / PRO / PREMIUM commercial plans plus OWNER/ADMIN role alias.
- OWNER is quota-exempt but not exempt from shared cache/provider safety controls.
- Added daily/monthly usage events and PostgreSQL/Supabase schema for subscriptions.
- Added Account & Plan page.
- Added Asset Analysis levels and cache-aware deep-analysis charging.
- Added process-global conservative deep-provider limiter as a safety backstop. Multi-instance production should move limiter state to Redis/Upstash.
- Validation in build environment: `compileall` passed; full test suite passed with temporary Streamlit/yfinance import stubs (not included in artifact).
- Enforced per-user hourly API-unit budgets and in-process concurrent-job leases. OWNER bypasses those commercial per-user limits only; provider safety remains global.
