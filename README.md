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
