"""APEX AI XAUUSD-only API. TickFeed data, ICT/FRVP analysis and paper simulation."""
from __future__ import annotations

import os
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from frvp import calculate_frvp
from tickfeed_market_data import fetch_xauusd_klines, fetch_xauusd_price, fetch_feed_health
from gold_strategy import analyze_xauusd
from gold_backtest import run_xauusd_backtest
from paper_engine import PaperEngine

app = FastAPI(
    title="APEX AI XAUUSD",
    version="1.1.0",
    description="XAUUSD-only ICT + FRVP analysis, historical simulation and paper trading. No live orders.",
)
DASHBOARD = Path(__file__).parent / "dashboard.html"
paper = PaperEngine(starting_balance=100.0, risk_fraction=0.01, fee_rate=0.0005)

class PaperOrder(BaseModel):
    symbol: str = Field(pattern=r"^XAUUSD$")
    side: str
    entry: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    take_profit: float = Field(gt=0)

class PaperClose(BaseModel):
    exit_price: float = Field(gt=0)

class FRVPCandle(BaseModel):
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    volume: float = Field(ge=0)

class FRVPRequest(BaseModel):
    candles: list[FRVPCandle] = Field(min_length=8)
    start_index: int = Field(default=0, ge=0)
    end_index: int | None = Field(default=None, ge=0)
    rows: int = Field(default=48, ge=8, le=300)
    value_area_percent: float = Field(default=70.0, ge=50, le=99)

@app.get("/", response_class=HTMLResponse)
def home():
    if not DASHBOARD.exists():
        raise HTTPException(status_code=404, detail="Dashboard file not found")
    return DASHBOARD.read_text(encoding="utf-8")

@app.get("/api/health")
def health():
    return {"app":"APEX AI XAUUSD", "status":"OK", "version":app.version,
            "market_focus":["XAUUSD"], "real_trading_enabled":False, "real_orders_enabled":False}

@app.get("/api/config")
def config():
    return {
        "project":"APEX AI XAUUSD ONLY", "market_focus":["XAUUSD"],
        "strategy":"M5_SCALPING", "timeframes":["5m","15m","1h"],
        "indicators":["ICT_LIQUIDITY_SWEEP","FVG","FRVP","POC","VAH","VAL","HVN","LVN","EMA_20_50","RSI_14","ATR_14"],
        "frvp":{"value_area_percent":70,"default_rows":48,"volume_source":"TickFeed tick-volume proxy; not centralized spot volume"},
        "data_provider":"TICKFEED", "demo_capital":100, "execution_mode":"PAPER_ONLY",
        "real_trading":"DISABLED", "real_orders_enabled":False,
        "tickfeed_api_key_configured":bool(os.getenv("TICKFEED_API_KEY")),
        "execution_platform_target":"MT5_NOT_CONNECTED",
    }

@app.get("/api/safety")
def safety():
    return {"app":"APEX AI", "analysis_enabled":True, "backtesting_enabled":True,
            "paper_trading_enabled":True, "real_trading_enabled":False,
            "real_orders_enabled":False, "live_order_routing":"NOT_IMPLEMENTED"}

@app.post("/api/indicators/frvp")
def api_frvp(request: FRVPRequest):
    try:
        result=calculate_frvp(request.candles, request.start_index, request.end_index,
                              request.rows, request.value_area_percent)
        result.update({"symbol":"XAUUSD", "volume_interpretation":"TICK_VOLUME_PROXY_FOR_OTC_SPOT_GOLD"})
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@app.get("/api/xauusd/price")
def xauusd_price():
    try: return {**fetch_xauusd_price(), "provider":"TICKFEED", "real_orders_enabled":False}
    except Exception as exc: raise HTTPException(status_code=502, detail=f"TickFeed price unavailable: {exc}")

@app.get("/api/xauusd/feed-health")
def xauusd_feed_health():
    try: return {**fetch_feed_health(), "provider":"TICKFEED", "real_orders_enabled":False}
    except Exception as exc: raise HTTPException(status_code=502, detail=f"TickFeed health unavailable: {exc}")

@app.get("/api/xauusd/market")
def xauusd_market(interval: str="5m", limit: int=300, source: str="live"):
    try:
        candles=fetch_xauusd_klines(interval, limit, source)
        return {"symbol":"XAUUSD", "provider":"TICKFEED", "interval":interval,
                "candle_count":len(candles), "candles":[c.__dict__ for c in candles],
                "volume_type":"TICKFEED_TICK_VOLUME_PROXY_NOT_CENTRALIZED_SPOT_VOLUME",
                "source":source, "execution":"READ_ONLY", "real_orders_enabled":False}
    except Exception as exc: raise HTTPException(status_code=502, detail=f"TickFeed XAUUSD data unavailable: {exc}")

@app.get("/api/xauusd/analyze")
def xauusd_analyze(limit: int=500):
    if not 120 <= limit <= 5000: raise HTTPException(status_code=400, detail="limit must be between 120 and 5000")
    try: return analyze_xauusd(limit)
    except Exception as exc: raise HTTPException(status_code=502, detail=f"TickFeed XAUUSD analysis unavailable: {exc}")

@app.get("/api/xauusd/backtest")
def xauusd_backtest(limit: int=1200, starting_balance: float=100.0, risk_percent: float=0.01,
                    fee_rate: float=0.0005, slippage_bps: float=2.0, max_holding_bars: int=24):
    if not 800 <= limit <= 5000: raise HTTPException(status_code=400, detail="limit must be between 800 and 5000")
    try:
        candles=fetch_xauusd_klines("5m", limit, source="stored")
        return run_xauusd_backtest(candles, starting_balance, risk_percent, fee_rate, slippage_bps, max_holding_bars)
    except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc: raise HTTPException(status_code=502, detail=f"TickFeed XAUUSD backtest unavailable: {exc}")

@app.get("/api/paper/account")
def paper_account(): return paper.account()

@app.post("/api/paper/order")
def paper_order(order: PaperOrder):
    try: return paper.open_position(order.symbol, order.side, order.entry, order.stop_loss, order.take_profit)
    except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc))

@app.post("/api/paper/close/{position_id}")
def paper_close(position_id: int, payload: PaperClose):
    try: return paper.close_position(position_id, payload.exit_price)
    except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc))
