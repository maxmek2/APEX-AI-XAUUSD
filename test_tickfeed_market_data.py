from datetime import datetime, timezone
import pytest
import tickfeed_market_data as market


def _rows(n=60):
    rows=[]
    for i in range(n):
        dt=datetime(2026,11,19,10,0,tzinfo=timezone.utc).timestamp()+i*300
        stamp=datetime.fromtimestamp(dt,tz=timezone.utc).isoformat().replace('+00:00','Z')
        rows.append({'time':stamp,'open':4000+i,'high':4010+i,'low':3990+i,
                     'close':4005+i,'tick_volume':123+i,'complete':True})
    return rows


def test_xauusd_completed_candles_oldest_first(monkeypatch):
    rows=_rows()
    rows.append({'time':'2026-11-19T15:00:00Z','open':4060,'high':4070,
                 'low':4050,'close':4065,'tick_volume':90,'complete':False})
    calls=[]
    def fake(path, params=None, **kwargs):
        calls.append((path,params))
        return {'symbol':'XAUUSD','candles':rows}
    monkeypatch.setattr(market,'_get',fake)
    bars=market.fetch_xauusd_klines('5m',60)
    assert len(bars)==60
    assert bars[0].volume==123
    assert bars[-1].open_time>bars[0].open_time
    assert calls[0][0]=='/v1/candles/XAUUSD'
    assert calls[0][1]['timeframe']=='M5'


def test_rejects_other_instrument(monkeypatch):
    monkeypatch.setattr(market,'_get',lambda *a,**k:{'symbol':'NOT_XAUUSD','candles':_rows()})
    with pytest.raises(market.TickFeedError):
        market.fetch_xauusd_klines('5m',60)


def test_requires_tick_volume(monkeypatch):
    rows=_rows()
    rows[0].pop('tick_volume')
    monkeypatch.setattr(market,'_get',lambda *a,**k:{'symbol':'XAUUSD','candles':rows})
    with pytest.raises(market.TickFeedError,match='tick_volume'):
        market.fetch_xauusd_klines('5m',60)


def test_price_quote_and_freshness(monkeypatch):
    monkeypatch.setattr(market,'_get',lambda *a,**k:{'symbol':'XAUUSD','bid':'4000.1','ask':'4000.2',
        'tick_time':'2026-11-19T10:00:00Z','freshness':'fresh'})
    q=market.fetch_xauusd_price()
    assert q['symbol']=='XAUUSD' and abs(q['mid']-4000.15)<1e-9
    assert q['freshness']=='fresh'


def test_rejects_bad_timeframe_and_source():
    with pytest.raises(ValueError): market.fetch_xauusd_klines('2m',60)
    with pytest.raises(ValueError): market.fetch_xauusd_klines('5m',60,'other')


def test_gap_endpoint_is_xauusd_only(monkeypatch):
    calls=[]
    monkeypatch.setattr(market,'_get',lambda path,params=None,**k:(calls.append((path,params)) or {'gaps':[]}))
    market.fetch_xauusd_gaps('15m')
    assert calls[0][0]=='/v1/candles/XAUUSD/gaps'
    assert calls[0][1]['timeframe']=='M15'
