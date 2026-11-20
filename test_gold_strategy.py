from gold_strategy import _near


def test_frvp_proximity_filter():
    assert _near(2350.10, 2350.00, 0.11)
    assert not _near(2350.20, 2350.00, 0.11)


def test_resample_keeps_only_complete_bars():
    from gold_backtest import _resample
    from market_models import Candle
    candles=[]
    for i in range(4):
        candles.append(Candle(i*300000, 10+i, 12+i, 9+i, 11+i, 2, (i+1)*300000-1, 22, 1, 0, 0))
    out=_resample(candles,3)
    assert len(out)==1
    assert out[0].open==10 and out[0].close==13
    assert out[0].high==14 and out[0].low==9


def test_resample_rejects_missing_m5_bar():
    from gold_backtest import _resample
    from market_models import Candle
    candles=[]
    for i in (0, 2):
        candles.append(Candle(i*300000, 10+i, 12+i, 9+i, 11+i, 2, (i+1)*300000-1, 22, 1, 0, 0))
    assert _resample(candles,3) == []
