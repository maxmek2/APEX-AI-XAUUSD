"""Regression tests for UTC paper-account day boundaries."""
import time

import paper_engine


def _fixed_utc_struct():
    return time.struct_time((2026, 11, 22, 0, 0, 0, 6, 326, 0))


def test_paper_engine_today_uses_utc(monkeypatch):
    monkeypatch.setattr(paper_engine, "gmtime", lambda *_: _fixed_utc_struct())
    engine = paper_engine.PaperEngine(starting_balance=100, fee_rate=0)
    assert engine._today() == "2026-11-22"


def test_closed_trade_date_is_stamped_in_utc(monkeypatch):
    monkeypatch.setattr(paper_engine, "gmtime", lambda *_: _fixed_utc_struct())
    monkeypatch.setattr(paper_engine, "time", lambda: 1795305600.0)
    engine = paper_engine.PaperEngine(starting_balance=100, fee_rate=0)
    opened = engine.open_position("XAUUSD", "BUY", 100, 99, 102)
    trade = engine.close_position(opened["position"]["id"], 101)
    assert trade["date"] == "2026-11-22"
    assert engine._daily_realized_pnl() == trade["pnl"]
