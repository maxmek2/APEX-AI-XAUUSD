# APEX AI — XAUUSD ONLY

Gold-only analysis and paper-simulation application. The market-data adapter is locked to the single instrument `XAUUSD` and uses TickFeed's documented REST API.

## XAUUSD data source

- Live quote: `GET https://api.tickfeed.pro/v1/price/XAUUSD`
- Candles: `GET https://api.tickfeed.pro/v1/candles/XAUUSD?timeframe=M5&limit=500&source=live`
- Historical candles: same endpoint with `source=stored`
- Feed health: `GET https://api.tickfeed.pro/health`
- Reported history gaps: `GET https://api.tickfeed.pro/v1/candles/XAUUSD/gaps?timeframe=M5`
- Authentication: `X-API-Key` header from `TICKFEED_API_KEY` environment variable.

Supported candle intervals: M1, M5, M15, H1, H4 and D1. TickFeed returns candles oldest-first and marks the currently forming candle with `complete: false`; this application excludes incomplete bars. Missing bars are not filled or fabricated. The adapter checks the returned symbol when supplied and rejects any instrument other than XAUUSD.

**Volume note:** XAUUSD is OTC spot gold. `tick_volume` is a provider quote/tick activity proxy, not centralized exchange-traded volume. The app does not pretend it is COMEX volume. The adapter does not fabricate quote volume or trade counts.

## Run

```bash
pip install -r requirements.txt
export TICKFEED_API_KEY="your_key"
uvicorn app:app --host 0.0.0.0 --port 8000
```

## Tests

```bash
python -m pytest -q
```

## Render

Create a Docker Web Service from the repository root. Leave Root Directory blank. Set `TICKFEED_API_KEY` in Render Environment Variables.

## Scope and safety

- Instrument: XAUUSD only.
- Analysis: M5 scalping with M15/H1 confirmation, ICT and FRVP.
- Simulation: historical backtest and $100 paper account.
- MT5 execution bridge is not implemented.
- Real trading and real order routing are disabled.

## Broker-aware backtest

The original diagnostic backtest remains available at `/api/xauusd/backtest`.
A separate broker-aware engine is available at:

```text
GET /api/xauusd/backtest/broker
```

Defaults are a $100 starting balance, 2% maximum research risk budget per trade,
$0.26 assumed spread, $0.02 assumed slippage per side, 0% commission until the
account's actual commission schedule is verified, a 3% UTC-day realized-loss lock, a pre-gap exit policy, and a 24-bar maximum hold.
The engine models the JustMarkets Standard contract as 100 XAU per lot, 0.01
minimum lot and 0.01 lot step. It rejects trades when the minimum lot would
exceed the risk budget. These are backtest assumptions, not a live quote or
guarantee of broker execution.

The broker-aware engine precomputes complete M15/H1 bars and only uses higher
timeframe bars that have closed by the M5 signal candle. Signals are evaluated
at M5 close and entries use the next M5 open. If SL and TP are both touched in
one candle, SL is assumed first. Gaps are not filled or fabricated. FRVP remains
an approximation based on candle tick-volume proxy.

This endpoint is backtest-only. It does not place demo or live orders; real
order routing remains disabled.


## Research indicators (non-production)

The following causal indicator calculations are available in `research_indicators.py`:
- Choppiness Index (CHOP)
- Kaufman Adaptive Moving Average (KAMA)
- Kaufman Efficiency Ratio (ER)
- Rolling realized volatility (sample standard deviation of log returns)
- UTC-day anchored tick-volume VWAP and rolling deviation Z-score

These functions are research diagnostics only. They are not enabled as production
entry rules and do not change the existing ICT + FRVP strategy. All outputs are
aligned to the input candles; warm-up values are `None`; calculations use only
current and earlier completed candles. The VWAP uses provider tick-volume proxy,
not centralized exchange volume.

### Research result on supplied XAUUSD M5 history

On the supplied 35,954-candle CSV (2026-03-26 through 2026-09-25), a predeclared
standalone-rule diagnostic used a chronological 60%/40% split, $100 starting
balance per segment, 10% research risk, 0.01 minimum lot, assumed $0.26 spread,
$0.02 slippage per side, ATR(14) x 1.5 stop, 1.5R target and 24-bar time exit.
The five holdout results were all negative:
- CHOP + Donchian breakout: -$54.17
- KAMA cross: -$62.59
- ER + Donchian breakout: -$57.89
- Realized-volatility expansion + Donchian breakout: -$57.34
- VWAP Z-score mean reversion: -$62.48

These are specific exploratory rules, not proof that the indicators have no
value as filters. They do not establish a profitable strategy. The supplied
CSV contains OHLC and tick-volume only; it cannot support true bid/ask footprint,
exchange CVD, or order-book imbalance. Do not optimize on the holdout segment.
Real orders remain disabled.
