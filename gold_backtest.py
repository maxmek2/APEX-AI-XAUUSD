"""Conservative XAUUSD ICT + FRVP historical simulation; no order routing."""
from __future__ import annotations
from dataclasses import asdict
from analysis_engine import analyze
from market_models import Candle
from frvp import calculate_frvp


def _resample(candles: list[Candle], factor: int) -> list[Candle]:
    """Build aligned higher-timeframe bars; discard incomplete/gapped groups."""
    if factor < 1:
        raise ValueError("factor must be positive")
    base_ms = 300_000
    target_ms = base_ms * factor
    grouped: dict[int, list[Candle]] = {}
    for candle in candles:
        bucket = (candle.open_time // target_ms) * target_ms
        grouped.setdefault(bucket, []).append(candle)
    out=[]
    for bucket, chunk in sorted(grouped.items()):
        by_time = {x.open_time: x for x in chunk}
        expected = [bucket + n * base_ms for n in range(factor)]
        if any(ts not in by_time for ts in expected):
            continue
        ordered = [by_time[ts] for ts in expected]
        out.append(Candle(
            open_time=bucket, open=ordered[0].open,
            high=max(x.high for x in ordered), low=min(x.low for x in ordered),
            close=ordered[-1].close, volume=sum(x.volume for x in ordered),
            close_time=bucket + target_ms - 1,
            quote_volume=sum(x.quote_volume for x in ordered),
            trades=sum(x.trades for x in ordered), taker_buy_base=0.0, taker_buy_quote=0.0))
    return out


def run_xauusd_backtest(candles: list[Candle], starting_balance: float = 100.0,
                        risk_percent: float = 0.01, fee_rate: float = 0.0005,
                        slippage_bps: float = 2.0, max_holding_bars: int = 24) -> dict:
    if len(candles) < 800:
        raise ValueError("At least 800 M5 candles are required for M15/H1 confirmation warm-up")
    if starting_balance <= 0 or not 0 < risk_percent <= .02 or not 0 <= fee_rate < .01 or not 0 <= slippage_bps < 100 or max_holding_bars < 1:
        raise ValueError("Invalid backtest parameters")
    balance=starting_balance; peak=balance; max_dd=0.0; trades=[]; position=None
    evaluated=0; ict_candidates=0; rejected_mtf=0; rejected_frvp=0
    slip=slippage_bps/10000
    # Use a bounded window to control runtime. All signals use closed candles only.
    for i in range(720, len(candles)-1):
        bar=candles[i]
        if position:
            age=i-position["entry_index"]
            hit_sl = bar.low <= position["sl"] if position["side"]=="BUY" else bar.high >= position["sl"]
            hit_tp = bar.high >= position["tp"] if position["side"]=="BUY" else bar.low <= position["tp"]
            exit_price=None; reason=None
            if hit_sl: exit_price=position["sl"]; reason="SL"  # conservative if both touched
            elif hit_tp: exit_price=position["tp"]; reason="TP"
            elif age >= max_holding_bars: exit_price=bar.close; reason="TIME"
            if exit_price is not None:
                direction=1 if position["side"]=="BUY" else -1
                exit_fill=exit_price*(1-direction*slip)
                gross=(exit_fill-position["entry_fill"])*position["qty"]*direction
                fees=(position["entry_fill"]*position["qty"]+exit_fill*position["qty"])*fee_rate
                net=gross-fees; balance+=net
                trades.append({"side":position["side"],"entry_time":position["entry_time"],"exit_time":bar.close_time,
                               "entry":round(position["entry_fill"],3),"exit":round(exit_fill,3),"qty":round(position["qty"],5),
                               "net_pnl":round(net,4),"reason":reason,"bars_held":age})
                peak=max(peak,balance); max_dd=max(max_dd,(peak-balance)/peak if peak else 0)
                position=None
            continue
        history=candles[max(0,i-299):i+1]
        m15=_resample(candles[:i+1],3)[-160:]
        h1=_resample(candles[:i+1],12)[-100:]
        if len(m15)<60 or len(h1)<60: continue
        evaluated+=1
        report=analyze(history,"XAUUSD","spot_gold","5m")
        side=report.get("status")
        if side not in ("BUY_CANDIDATE","SELL_CANDIDATE"): continue
        ict_candidates+=1
        m15r=analyze(m15,"XAUUSD","spot_gold","15m")
        h1r=analyze(h1,"XAUUSD","spot_gold","1h")
        bias="bullish" if side=="BUY_CANDIDATE" else "bearish"
        if m15r.get("bias_ema20_50")!=bias or h1r.get("bias_ema20_50")!=bias:
            rejected_mtf+=1; continue
        profile=calculate_frvp(history,start_index=max(0,len(history)-96),end_index=len(history)-1,rows=48,value_area_percent=70)
        price=bar.close; atr=report.get("atr14") or 0.0; tol=max(atr*.25,price*.0001)
        levels=[profile["poc"]]
        levels += [profile["val"] if bias=="bullish" else profile["vah"]]
        levels += [x["price"] for x in profile["hvn"]]
        if not any(abs(price-level)<=tol for level in levels):
            rejected_frvp+=1; continue
        sl=report.get("provisional_stop_loss"); tp=report.get("provisional_take_profit")
        if not sl or not tp: continue
        entry=candles[i+1].open; direction=1 if bias=="bullish" else -1
        risk=abs(entry-sl)
        if risk<=0: continue
        qty=(balance*risk_percent)/risk
        entry_fill=entry*(1+direction*slip)
        position={"side":"BUY" if direction==1 else "SELL","entry_index":i+1,"entry_time":candles[i+1].open_time,
                  "entry_fill":entry_fill,"qty":qty,"sl":sl,"tp":tp}
    if position:
        last=candles[-1]; direction=1 if position["side"]=="BUY" else -1
        exit_fill=last.close*(1-direction*slip); gross=(exit_fill-position["entry_fill"])*position["qty"]*direction
        fees=(position["entry_fill"]+exit_fill)*position["qty"]*fee_rate; net=gross-fees; balance+=net
        trades.append({"side":position["side"],"entry_time":position["entry_time"],"exit_time":last.close_time,
                       "entry":round(position["entry_fill"],3),"exit":round(exit_fill,3),"qty":round(position["qty"],5),
                       "net_pnl":round(net,4),"reason":"END_OF_DATA","bars_held":len(candles)-1-position["entry_index"]})
    wins=sum(1 for t in trades if t["net_pnl"]>0); losses=sum(1 for t in trades if t["net_pnl"]<0)
    gross_profit=sum(t["net_pnl"] for t in trades if t["net_pnl"]>0)
    gross_loss=abs(sum(t["net_pnl"] for t in trades if t["net_pnl"]<0))
    return {"symbol":"XAUUSD","strategy":"ICT+FRVP_M5_M15_H1","provider":"TICKFEED_STORED_HISTORY",
            "volume_type":"TICKFEED_TICK_VOLUME_PROXY_NOT_CENTRALIZED_SPOT_VOLUME","starting_balance":starting_balance,
            "ending_balance":round(balance,4),"net_pnl":round(balance-starting_balance,4),
            "return_percent":round((balance/starting_balance-1)*100,3),"trades":len(trades),"wins":wins,"losses":losses,
            "win_rate_percent":round(wins/len(trades)*100,2) if trades else 0,
            "profit_factor":round(gross_profit/gross_loss,3) if gross_loss else None,
            "max_drawdown_percent":round(max_dd*100,3),"diagnostics":{"evaluated":evaluated,"ict_candidates":ict_candidates,
            "rejected_mtf":rejected_mtf,"rejected_frvp":rejected_frvp},"trade_history":trades,
            "execution":"BACKTEST_ONLY","real_orders_enabled":False}
