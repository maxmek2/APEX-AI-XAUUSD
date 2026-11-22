# APEX AI Stage 5.2 — Repository Audit

Date: 2026-11-22
Target: `maxmek2/APEX-AI-XAUUSD`, branch `main`
Working branch: `stage-5.2-audit`

## Scope and separation

The attached Stage 5.1 PDF is a BTC/USD, Alpaca historical-data, read-only experiment. This repository is a separate XAUUSD-only application using TickFeed data and an ICT + FRVP strategy, with a JustMarkets Standard broker-aware research model. The PDF's BTC/USD metrics must not be presented as results for this XAUUSD repository or used to tune its parameters.

No live order routing exists in this repository. This audit does not enable it.

## Verified repository architecture

- `app.py`: FastAPI endpoints for TickFeed market data, analysis, historical backtests and paper-account operations.
- `tickfeed_market_data.py`: fixed XAUUSD symbol; excludes incomplete candles; validates OHLC and tick-volume; does not synthesize missing bars.
- `analysis_engine.py`: ICT liquidity sweep/FVG/structure and EMA/RSI/ATR confluence.
- `gold_strategy.py`: M5 candidate with M15 and H1 EMA bias confirmation plus FRVP level proximity.
- `broker_backtest.py`: JustMarkets Standard sizing model; M5 close signal / next M5 open entry; closed higher-timeframe bars only; spread, slippage and commission assumptions; conservative SL-first handling when SL and TP are both touched; data-gap exit.
- `broker_execution.py`: lot-step flooring and rejection when minimum lot exceeds the risk budget.
- `risk_controls.py`: daily loss and aggregate risk gates.
- `frvp.py`: OHLC-range allocation of TickFeed tick-volume proxy, explicitly not true exchange/footprint volume.
- `paper_engine.py`: in-memory paper positions and balance; no exchange credentials or live routing.

## Findings

### F-01 — Research artifact / repository mismatch (high)

The Stage 5.1 PDF tests BTC/USD with Alpaca data. This repository README and source code are XAUUSD-only and use TickFeed. Do not copy Stage 5.1 BTC/USD strategy selection or performance claims into the XAUUSD production path. Maintain separate experiment identifiers, datasets, costs and reports.

### F-02 — Paper daily-loss day boundary uses host local time (medium)

`paper_engine.py` imports `localtime` and uses it in both `_today()` and close-trade date stamping. The broker-aware backtest uses explicit UTC-day accounting. If the paper service host timezone differs from UTC, its daily loss lock can reset on a different boundary. Implemented on this branch: paper trade date stamps and daily aggregation now use UTC via `gmtime`; `test_paper_engine_utc.py` adds regression coverage for the UTC day stamp and daily P/L aggregation. The test suite still needs to be run in CI/Render before merge.

### F-03 — Paper position monitoring is caller-driven (medium)

`PaperEngine.check_positions()` only closes a paper position when a caller supplies a market price. The method docstring confirms it does not run automatically. The current API exposes price and paper endpoints separately; verify an external polling loop exists before describing paper SL/TP as continuously monitored. Do not imply automatic protection unless a monitored loop and failure handling are deployed.

### F-04 — FRVP is an approximation (medium)

`frvp.py` allocates each candle's tick-volume evenly across bins touched by its high-low range. This is not traded volume-at-price, order flow, footprint or exchange volume. Keep the existing disclosure in all API/report outputs and do not use FRVP as if it were precise volume-at-price evidence.

### F-05 — Validation gates are not yet a release gate in the API (medium)

The broker backtest returns trade counts and performance diagnostics, but its endpoint does not itself mark a strategy validated against minimum train/holdout trade counts, positive net expectancy after costs, or walk-forward criteria. Add a separate research-validation layer before any strategy can be promoted. A backtest result must not automatically become an enabled paper strategy.

### F-06 — Broker assumptions require account verification (medium)

The README documents a 100 XAU/lot contract, 0.01 minimum lot and 0.01 lot step, plus assumed spread and slippage. Commission defaults to zero pending verification. Treat these as research assumptions until confirmed against the user's exact account specification and observed execution costs.

## Existing safeguards verified

- TickFeed adapter is hard-locked to XAUUSD.
- Incomplete candles are excluded; missing bars are not fabricated.
- Broker-aware engine evaluates completed M5 signals and enters on the next M5 open.
- Higher-timeframe data is restricted to bars closed by the signal timestamp.
- Broker-aware sizing rejects minimum-lot trades that exceed the risk budget.
- Broker-aware backtest includes execution-cost assumptions and data-gap handling.
- App health/safety/config responses explicitly state that real trading and real order routing are disabled.
- No broker order API or live order routing was called as part of this audit.

## Stage 5.2 implementation sequence

1. Fix paper-engine UTC date accounting and add rollover regression tests.
2. Add an explicit paper-monitoring service/health state, or clearly label monitoring as manual if no reliable polling loop is deployed.
3. Add a validation/reporting layer with chronological train/validation/holdout splits, minimum sample counts per segment, net-of-cost metrics, and a strict no-holdout-tuning rule.
4. Add data-quality reporting: requested/returned bars, gaps, duplicates, incomplete bars removed, timestamp coverage and source.
5. Re-run XAUUSD-only broker-aware tests using the actual stored TickFeed dataset and account-specific costs.
6. Keep all execution paths paper-only; do not add live order routing as part of Stage 5.2 research.

## Release decision

**NOT VALIDATED — DO NOT PROMOTE TO AUTOMATED EXECUTION.**

This branch contains the audit, the UTC paper-account date fix, and regression tests. It does not claim a profitable strategy, does not change strategy parameters, and does not activate paper or live execution. The new tests have been added but have not been executed in this session.
