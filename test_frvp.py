from types import SimpleNamespace
import pytest
from frvp import calculate_frvp


def candles():
    return [SimpleNamespace(low=2000+i, high=2002+i, volume=100+i) for i in range(20)]


def test_profile_has_levels_and_value_area():
    result = calculate_frvp(candles(), 2, 15, rows=20)
    assert result['total_volume'] > 0
    assert result['val'] <= result['poc'] <= result['vah']
    assert len(result['levels']) == 20


def test_invalid_range_rejected():
    with pytest.raises(ValueError):
        calculate_frvp(candles(), 15, 2)
