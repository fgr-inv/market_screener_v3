# Market Screener Pro V8 — Production-Hardened Research Terminal

V8 focuses on reliability, persistence, auditability and portfolio risk rather than adding more indicators.

## What changed in V8

### Production hardening
- Sectioned Streamlit navigation: Market / Research / Portfolio / Quant / Operations.
- Snapshot-first dashboard retained and expanded with **What Changed?**.
- Structured runtime error logging and System Health visibility.
- GitHub Actions updated to `checkout@v5` and `setup-python@v6` with pip cache.
- Workflow concurrency and timeouts.
- Daily refresh runs as a Python module with explicit `PYTHONPATH`.

### Persistent alerts
- Alert definitions support `cooldown_minutes` and `repeat_while_true`.
- Edge-triggering: default alert behavior is `FALSE -> TRUE`, avoiding hourly spam.
- Persistent alert state: last hit, last trigger, last evaluation, trigger count.
- `DATABASE_URL` (Postgres/Supabase) is preferred for shared Streamlit/GitHub state.
- CSV + GitHub commit remains a durable fallback when cloud storage is not configured.

### Missing-data-safe scoring
- Missing data is **not** silently converted to 0 or neutral 50 in the Opportunity model.
- Available factor weights are re-normalized.
- `Model_Coverage_%` and `Available_Factors` are exposed.
- Confidence is no longer treated as an alpha factor; it gates trust/action quality.
- Low coverage / low confidence can force `WAIT` instead of a misleading buy label.
- Opportunity Model v8.0.0 registered in `data/model/model_registry.json`.

### Portfolio risk
- Covariance-based **Risk Contribution %** per position.
- Standalone volatility and Risk/Weight ratio.
- CVaR 95% and historical portfolio max drawdown.
- Thematic exposure across GICS boundaries (AI, data centers, power, crypto, etc.).
- High-correlation pair diagnostics.

### Research process
- Portfolio page now includes a **Thesis Tracker**:
  - thesis
  - catalysts
  - invalidation
  - target
  - review date
  - status
- Factor Lab includes score-correlation / de-duplication diagnostics.
- Dashboard includes latest material score/action changes.
- Explainability now follows missing-aware V8 model weights.

### Testing
- 28 deterministic unit tests pass in the shipped build.
- Added tests for alert state transitions, cooldowns, missing-aware scoring,
  thematic exposure, factor redundancy, change detection and portfolio risk contribution.

## Architecture

```text
app.py
core/                 # analytics, models, storage, providers, risk
views/                # Streamlit UI
scripts/              # scheduled/background jobs
.github/workflows/    # CI, snapshots, alerts
data/                  # tracked fallbacks + snapshots; local DB/cache ignored
tests/                 # deterministic tests
```

## Deploy on Streamlit Cloud

- Branch: `main`
- Main file path: `app.py`

## Recommended secrets

### Streamlit Cloud secrets

```toml
APP_PASSWORD = ""
DATABASE_URL = ""
GITHUB_REPO = "mfig1098/market_screener_v3"
GITHUB_PAT = ""
ALERT_WEBHOOK_URL = ""
```

Optional provider keys are documented in `.streamlit/secrets.toml.example`.

### GitHub Actions secrets

For shared alert state, configure the same:

```text
DATABASE_URL
ALERT_WEBHOOK_URL
EIA_API_KEY          # optional
```

If `DATABASE_URL` is absent, `data/alerts.csv` and `data/alert_state.csv` act as the GitHub-persisted fallback.

## Important research limitations

The terminal intentionally does not fabricate institutional datasets.

- Yahoo/public feeds can be delayed, incomplete or revised.
- Fundamental/revision backtests require true point-in-time data to avoid look-ahead bias.
- Historical universe backtests require historical constituents to avoid survivorship bias.
- Factor proxies are not Barra/Axioma.
- Options/short-interest/on-chain depth depends on configured providers.

Treat scores as a research framework, not as guaranteed forecasts or automated trade instructions.

## Professional analysis architecture (V8.2)
The application routes assets to different analytical frameworks instead of applying an equity template everywhere. Equity analysis is sector/industry-aware and combines technical regime, company fundamentals, valuation, revisions and event risk. Fixed income separates rates, duration and credit; crypto uses weekly cycle, volatility-normalized location and derivatives/liquidity context; commodities use group-specific macro/supply drivers; FX uses relative-policy/carry logic when data exist; ETFs/indices are evaluated on their underlying exposure rather than corporate ratios.

The Technical Engine V2 adds confirmed swing structure, weekly confirmation, anchored VWAP, relative volume, up/down-volume participation, volatility regime and a daily-bar volume-at-price proxy. It explicitly reports unavailable horizons (for example, 4H is not fabricated from daily data) and labels proxy data so the UI does not imply institutional tick-level coverage that is not present.


## V8.3 — Data Coverage & Professional Inputs

The app now separates **model coverage** from **data coverage**. A high technical or opportunity score is not presented as equally reliable when industry-specific data are unavailable. The Asset Analysis page reports core-data coverage, specialist-data coverage, missing critical metrics, and recommended sources.

Examples: banks flag missing NIM/CET1/deposit/credit-quality metrics; REITs flag FFO/AFFO/NAV/occupancy; crypto flags funding/OI/basis/liquidations/ETF flows/on-chain metrics; fixed income flags duration/convexity/OAS/key-rate data; FX flags carry and real-yield differentials; commodities flag futures curve, inventories and COT positioning. Missing inputs are disclosed rather than fabricated.

### Optional data keys

- `FRED_API_KEY`: strongly recommended for reliable official US macro/rates/inflation data. The app retains a best-effort public CSV fallback and cache.
- `EIA_API_KEY`: recommended for oil/energy inventory analysis.
- `COINGECKO_API_KEY`: optional **free Demo key** for higher/stabler CoinGecko limits; public fallback works without it.
- CoinGlass and Trading Economics are no longer required by the free-first V8.5 stack.
- `FMP_API_KEY`, `FINNHUB_API_KEY`, `POLYGON_API_KEY`: optional equity estimate/insider/market-data enrichment depending on provider plan.
- `NASDAQ_DATA_LINK_API_KEY`: optional commodity/economic datasets.

FRED API notice: **This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis.**

## V8.4 — Live specialist API integrations

V8.4 turns the previously-declared optional providers into active data sources. The app still works without them and falls back gracefully; missing premium data is shown as missing rather than imputed.

### Streamlit Cloud secrets

```toml
FRED_API_KEY = "..."                 # already supported; macro/rates
EIA_API_KEY = "..."                  # energy inventories
FMP_API_KEY = "..."                  # equity ratios/metrics/estimates
COINGLASS_API_KEY = "..."            # crypto OI/funding/liquidations/ETF flows
TRADINGECONOMICS_API_KEY = "..."     # foreign policy rates/global macro/calendar
```

If the scheduled GitHub Action should use the same providers, add the same names under **GitHub → Settings → Secrets and variables → Actions**. The workflow now forwards all five secrets to `scripts.daily_refresh`.

### What each integration does

- **FRED:** official macro/rates series with cached fallback.
- **EIA API v2:** commercial crude (`WCESTUS1`), gasoline (`WGTSTUS1`) and distillate (`WDISTUS1`) inventories, weekly changes and a same-week seasonal z-score for oil analysis.
- **FMP stable API:** profile, TTM ratios, key metrics, financial health scores and analyst estimates. Values enrich Yahoo only when fields are missing; provider-specific metrics (ROIC, FCF yield, Piotroski, Altman Z) remain explicit.
- **CoinGlass V4:** aggregated futures open interest, OI-weighted funding, liquidations and BTC/ETH ETF flows when the subscribed plan exposes the endpoints. Binance/CoinGecko stay as fallbacks.
- **Trading Economics:** foreign central-bank/policy-rate coverage for FX carry before falling back to selected FRED series, plus the existing macro calendar.

No API key is hard-coded in the repository. A configured key can still have endpoint/plan restrictions; System Health reports provider status instead of silently treating restricted data as valid.


## V8.5 — Zero-cost professional data stack

V8.5 removes the practical dependency on paid CoinGlass and Trading Economics for the core analysis path. The default stack is designed to run at **$0 provider cost** using FRED, EIA, FMP free tier, CoinGecko Demo/Public, Binance Futures public endpoints, Bybit public endpoints, OKX public endpoints, CFTC public COT, Yahoo Finance and Blockchain.com public on-chain charts.

### Recommended secrets

```toml
FRED_API_KEY = "..."        # free; macro/rates/release calendar
EIA_API_KEY = "..."         # free; US energy inventories
FMP_API_KEY = "..."         # free tier; equity enrichment within plan limits
COINGECKO_API_KEY = "..."   # optional free Demo key; public fallback works without it
```

The scheduled GitHub Action forwards those four keys. Binance, Bybit, OKX and CFTC public data require no key.

### Free professional routing

- **Crypto:** CoinGecko market breadth + Binance/Bybit/OKX funding, open interest and perp basis. Binance public OI history supplies a 24h OI-change proxy. Aggregate historical liquidations and ETF flows stay explicitly missing because the project does not use a brittle or paid source to fabricate them.
- **FX:** carry/policy proxies come from FRED and selected OECD/global rate series mirrored by FRED. This is a slower macro layer, not a substitute for an institutional cross-currency swap curve.
- **Commodities:** EIA inventories + public CFTC COT + price/macro framework. Contract-level futures curve data remain a separate coverage item unless a reliable free curve is available.
- **US macro calendar:** FRED release dates replace the paid Trading Economics dependency. The calendar intentionally does not invent consensus forecasts.

Paid connectors remain in legacy helper code only for backward compatibility and are not required for the V8.5 analysis workflow.

## V8.6 — free specialist sector data

The zero-cost stack now adds official/public specialist sources rather than treating every equity with generic ratios:

- **SEC EDGAR Company Facts / XBRL** (no API key): standardized filing facts used for sector context such as deposits/loans/credit-loss allowance where tagged, inventory, capex, SBC, deferred revenue, R&D, debt and cash-flow facts.
- **ClinicalTrials.gov API v2** (no API key): trial counts, active trials, phases and statuses for biotech/pharma companies when sponsor matching succeeds.
- **openFDA** (no API key for the low-volume usage here): drug-label footprint as additional pharma context. It is not treated as a pipeline or approval probability model.
- **CFTC COT** (public): mapped commodity contracts now expose non-commercial net positioning and net positioning as a percentage of open interest when the public report contains the required columns.

These sources are best-effort. Non-standard KPIs such as bank CET1/NIM/ROTCE, REIT AFFO/NAV, SaaS NRR/ARR, biotech probability-of-success/rNPV, or E&P hedge books may still require company-specific filing/supplement parsing. They remain explicitly missing in Data Coverage instead of being imputed.

## V8.7 — Professional crypto models (free-data stack)
Crypto is no longer treated as one homogeneous asset class. The app routes BTC, ETH, L1/L2, DeFi, stablecoins and speculative tokens to different specialist frameworks. Bitcoin adds public network/miner/issuance metrics; Ethereum/L1/L2/DeFi use CoinGecko + DefiLlama context where available; tokenomics uses market-cap/FDV/supply/liquidity fields; derivatives remain multi-exchange (Binance/Bybit/OKX). Missing realized-cap cohort metrics, ETF flows, unlock schedules, reserve attestations, etc. remain explicitly missing rather than being estimated from price. No new API key is required beyond the existing free stack.

## V8.8 — Professional Equity Industry Engine

V8.8 makes equity research business-model-aware instead of applying one generic stock framework across every sector.

### New professional sub-industry models
- Semiconductors: AI accelerators/GPU, memory, foundry, equipment, analog/mixed signal, connectivity/networking, EDA/IP.
- Software/technology: SaaS, cybersecurity, IT services, technology hardware.
- Financials: money-center banks, regional banks, insurance, asset managers, exchanges/market infrastructure, payments, consumer finance.
- Real estate: data-center, industrial/logistics, residential, retail, healthcare and tower REITs plus a general REIT fallback.
- Energy: E&P, integrated oil, oilfield services, midstream, refining and LNG.
- Health care: biotech, pharma, MedTech, managed care, hospitals/providers and life-science tools.
- Industrials: aerospace & defense, automation/robotics, electrical/grid equipment, machinery, engineering & construction, transportation, airlines and waste services.
- Materials: copper miners, gold miners, steel, chemicals and general materials/mining.
- Consumer: retail, restaurants, autos, homebuilders, travel/leisure, apparel/luxury and staples.
- Communication services: telecom, streaming/media and internet/digital platforms.
- Utilities: regulated utilities and renewable/power developers.

### How the model works
For each stock, the app now identifies the business model and changes:
- critical operating KPIs;
- quality-pillar weights;
- preferred valuation methods;
- peer group;
- catalyst checklist;
- risk checklist;
- opportunity-factor weights;
- specialist data-coverage requirements.

Quality and valuation are separate scores. Peer valuation uses sub-industry peers when at least three comparable observations exist. Accounting multiples are deliberately de-emphasized where they are structurally weak (for example biotech and REITs). Missing non-standard KPIs such as ARR, NRR, CET1, AFFO, AISC, RASM or rate-base growth remain explicitly missing rather than being fabricated.

### Free-data discipline
V8.8 keeps the free-only provider stack. It uses Yahoo Finance, SEC EDGAR/XBRL, FMP free when configured, ClinicalTrials.gov/openFDA for biopharma, and existing public macro/commodity sources. Company supplements and filings are listed as recommended sources when a professional KPI is not available in a standardized free feed.

### Validation
- `python -m compileall -q core views tests` — passed.
- `pytest -q` — **52 passed** with the temporary Streamlit cache stub required by the artifact container.
- Live provider connectivity was **not** validated in the artifact container; use the deployed **System Health** page for real endpoint checks.

## V8.9 — Professional Crypto Regime & Execution Engine
Crypto now separates **cycle/regime**, **structural trend**, **long-term opportunity**, **entry timing**, **overextension**, and **leverage risk**. Bull-market momentum (including high-but-not-extreme RSI or price discovery) is no longer automatically treated as a bad entry. Breakout, trend-continuation and pullback entries are distinct. The engine remains probabilistic: it never assumes or guarantees a new ATH.

## V8.10 — Professional Research & Scenario Engine

V8.10 adds a dedicated institutional-style research layer for equities. It keeps alpha scoring separate from research evidence and adds four workstreams: true business-model peer benchmarking, estimate/revision research, catalyst/event mapping, and explicit bear/base/bull scenario analysis.

Key principles:
- Peers are restricted to the same professional subindustry/model whenever the current screener universe provides enough comparable names.
- Revisions distinguish signal strength from evidence confidence and surface target upside, latest earnings surprise, analyst count, and proximity to earnings.
- Catalysts separate structural industry catalysts/risks from dated events and recent-news evidence. No sentiment is invented from incomplete headlines.
- Bear/base/bull outputs are transparent decision ranges built from technical invalidation, setup targets, consensus targets, and factor quality. They are explicitly labeled as scenario analysis, not a DCF or guaranteed intrinsic-value target.
- Scenario coverage is disclosed so sparse free-data inputs cannot masquerade as precise institutional valuation.

New module: `core/professional_research_engine.py`.

## V9.0 — Institutional Multi-Asset Research Engine

V9.0 adds an integrated institutional evidence layer across equities, commodities and portfolio context without changing the principle that missing data is never treated as neutral or fabricated data. New modules include reverse-DCF and scenario DCF, earnings-quality/financial-resilience/capital-allocation diagnostics, macro-regime classification, commodity physical-market/curve/positioning aggregation, factor exposure, portfolio-fit aware sizing, options intelligence and a thesis/invalidation/execution summary. True historical valuation percentiles remain explicitly unavailable until point-in-time historical fundamentals have been accumulated; the application does not create pseudo-history from today's EPS/FCF.

## V10.0 — Zero-Cost Institutional Research Platform

V10 adds the infrastructure required to move from a feature-rich screener to an auditable research process without pretending that paid institutional history is free:

- immutable point-in-time research snapshots and explicit zero-cost historical data contracts;
- FRED/ALFRED vintage adapter for macro observations *as known at the time*;
- score and probability calibration primitives, forward-return attachment and event-study tooling;
- missing-aware cross-sectional relative-value ranking;
- ETF look-through aggregation with explicit holdings coverage and concentration/effective-holdings metrics;
- signal-agreement diagnostics so conflicting models are visible rather than hidden in an average;
- evidence lineage/freshness tables (source, observation date, age, stale/current status);
- a new Institutional Research Lab page and a zero-cost provider coverage map.

The design rule remains: **missing data is not neutral data and is never fabricated.** Historical fundamentals/consensus/options/holdings that cannot be obtained point-in-time from a reliable free source are accumulated prospectively or remain explicitly missing. This avoids look-ahead bias and false institutional precision.

## V11.0 — Complete Zero-Cost Professional Analysis Layer

V11 closes the remaining *architecture* gaps that can be addressed with public/free data without pretending premium datasets exist. It adds a master free-data source catalog, official/public provider contracts (SEC submissions/Form discovery, FINRA short-volume contract, Coin Metrics Community, mempool.space, BLS, BEA, Treasury FiscalData, GDELT), deeper pure analytical engines for fundamental acceleration, accounting forensics, capital allocation, moat proxies, futures-curve/COT history, fixed-income curve regimes, FX drivers, crypto liquidity/token dilution, correlation regimes, portfolio stress, execution quality, source reconciliation, signal disagreement, cross-asset relative value, walk-forward validation, probability metrics, decision attribution and model drift.

### Professional data rule

V11 does **not** manufacture unavailable historical consensus, true dealer GEX, paid on-chain cohorts, proprietary ETF flows, or other premium data. Missing fields lower coverage and confidence. Point-in-time history is only called point-in-time when captured prospectively or obtained from a vintage-aware official source.

### New free/public providers represented

- SEC EDGAR/submissions: filings and discovery of Form 4, 13F-HR and NPORT-P.
- FINRA public-data contract: daily short-sale volume when available; never treated as short interest.
- Coin Metrics Community API: public community network/on-chain metrics.
- mempool.space: BTC fees, mempool, difficulty and mining endpoints.
- BLS Public API: CPI/PPI/employment/productivity.
- BEA API: GDP/income/industry accounts with free key.
- US Treasury FiscalData: public fiscal/debt data.
- GDELT: global news/event attention (context, not authoritative sentiment).
- Existing FRED/ALFRED, EIA, CFTC, CoinGecko, DefiLlama, Binance/Bybit/OKX, ClinicalTrials.gov and openFDA remain part of the stack.


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

### V11.6 — Screener modes separated by analysis type
Professional Screener now separates **Análisis** (`Técnico`, `Fundamental`, `Combinado`) from **Profundidad** (`Rápido`, `Balanceado`, `Profundo`). Technical-only mode never runs the deep equity provider bundle (SEC/FMP/fundamentals/analyst/event/DCF/scenarios). Technical depth controls local price-analysis work/history; fundamental/combo depth controls the candidate enrichment budget as well. This reduces unnecessary API usage and rate-limit exposure when users only want technical discovery.


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

## V11.10 - Fundamental leaders vs opportunities + resilient peer rank

- Fundamental Screener now separates **Fundamental Opportunities** from **Fundamental Leaders**.
- `Fundamental_Opportunity_Score` rewards quality + valuation + revisions + financial resilience and does not use technical timing.
- `Fundamental_Leader_Score` is quality-first: company quality, financial resilience, earnings quality, capital allocation and management execution. A great but expensive company can rank highly here without being labeled a current valuation opportunity.
- `Peer_Rank_Score` now uses a transparent hierarchy when the exact business-model peer group is too small: `MODEL -> INDUSTRY -> SECTOR -> UNIVERSE`.
- Added `Peer_Rank_Source` and `Peer_Rank_Peer_Count` so every non-empty peer rank states exactly how it was constructed.

## V11.11 - Rate-limit-aware cache policy
- Added a centralized cache policy (`core/cache_policy.py`) so slow accounting data and fast market data no longer share ad-hoc TTLs.
- Fundamentals and specialist accounting inputs: 7 days; analyst revisions and earnings-event metadata: 12 hours; FRED/macro calendar: 12 hours; market-sensitive valuation overlay: 24 hours; news/options: 30 minutes; prices: 30-minute Streamlit cache with a 60-minute persistent price-cache freshness window.
- Asset Analysis now reuses the same persistent deep cache as the screeners instead of relying on an effectively unbounded per-session fundamental cache. A separate daily valuation overlay keeps price-sensitive multiples fresher than weekly accounting data. This reduces duplicate Yahoo/FMP/SEC calls and keeps Asset Analysis and screener freshness rules aligned.
- Manual/forced refresh still bypasses the deep disk TTL when explicitly requested by screener controls. No missing observation is fabricated to improve freshness or coverage.


## V11.12 - Layered market-price freshness
- Live/last prices now refresh on a 5-minute TTL.
- Long historical OHLCV remains on a 60-minute cache, so a fresh quote does not trigger another multi-year download.
- Technical-computation policy is documented at 15 minutes, while RS/sector context keeps slower intraday TTLs.
- Asset Analysis overlays a 5-minute live Yahoo quote on top of the cached historical analysis, preserving API efficiency while making the displayed/current valuation entry price materially fresher.
- `PRICE_TTL` remains as a backwards-compatible alias for the live quote TTL; new code should prefer `LIVE_PRICE_TTL` or `HISTORICAL_PRICE_TTL` explicitly.


## V11.13 — Shared live-quote cache

Live quotes now use a two-layer cache: Streamlit process cache plus a persistent per-ticker disk cache under `data/cache/live_quotes`. A best-effort per-ticker lock de-duplicates simultaneous refreshes, so multiple users requesting the same ticker within the 5-minute TTL normally reuse one provider response. For horizontally scaled deployments with multiple containers/hosts, replace the disk layer with Redis/Upstash or another shared external cache.

## V11.15 — subscriptions, quotas and OWNER bypass

V11.15 adds server-side commercial access control on top of the existing shared caches.

Plans:
- FREE: Technical Screener, basic Asset Analysis, 100 assets max, conservative daily/monthly quotas.
- PRO: Technical + Fundamental + Combined, 300 assets max, deep enrichment Top 20.
- PREMIUM: higher quotas, 500 assets max, deep enrichment Top 40.
- OWNER/ADMIN: no commercial daily/monthly quotas and all product features enabled. OWNER is **not** assignable by billing; grant it only server-side.

OWNER configuration examples (server-side secrets/environment):

```toml
DEV_USER_ID = "owner"
DEV_USER_EMAIL = "you@example.com"
DEV_USER_ROLE = "OWNER"
# Or production allow-lists:
OWNER_USER_IDS = "auth-user-id-1,auth-user-id-2"
OWNER_EMAILS = "you@example.com"
```

Important: OWNER bypasses product quotas only. It still uses shared caches and the process-global provider safety limiter, so an owner session cannot intentionally bypass API protection.

Production persistence:
- `DATABASE_URL` -> PostgreSQL/Supabase tables `app_users`, `subscriptions`, `usage_events`.
- Without `DATABASE_URL`, usage falls back to a local JSONL development log.
- `set_subscription(...)` accepts FREE/PRO/PREMIUM only. OWNER must come from the server-side allow-list/role.

Asset Analysis now exposes `Técnico`, `Fundamental`, and (when entitled) `Completo`. A fully fresh deep bundle is treated as a cache-served analysis and uses zero quota units; stale/new deep analysis consumes quota. Fundamental/Combined screeners are blocked before execution when the plan does not permit them.

Per-user safety budgets are also enforced before a new job starts: FREE 20 API units/hour and 1 concurrent job; PRO 100/hour and 2 jobs; PREMIUM 300/hour and 3 jobs. OWNER bypasses these *commercial per-user* budgets, but the global deep-provider limiter remains active for everybody.

## V11.16 — Saved Alerts production hardening

- Saved Alerts creation form now renders in the main page (not hidden in the sidebar).
- Per-user alert ownership (`user_id`) for multi-user deployments.
- FREE/PRO/PREMIUM saved-alert caps: 3 / 25 / 100; OWNER unlimited commercially.
- Persistent Postgres storage health indicator and explicit production warning when DATABASE_URL is missing.
- Collision-resistant alert IDs for concurrent users.
- PRICE_ABOVE / PRICE_BELOW rules use the shared 5-minute live quote cache, with daily-price fallback.
- Secure user-scoped enable/delete operations.
- Edge-triggering, cooldown and manual evaluation retained.
