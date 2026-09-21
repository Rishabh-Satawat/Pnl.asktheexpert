from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.dhan_integration import DhanDataProvider, DhanApiError


# ------------------------------------------------------------------
# TR-8.1  None credentials -> no crash, graceful disconnected state
# ------------------------------------------------------------------

def test_tr_8_1_none_credentials_no_crash():
    provider = DhanDataProvider(client_id=None, access_token=None)
    assert provider.connected is False

    result = provider.healthcheck()
    assert result["connected"] is False
    assert "optional" in result.get("user_action", "").lower() or "optional" in str(result).lower()
    # No exception raised -- test passes if we reach this point.


# ------------------------------------------------------------------
# TR-8.2  Offline provider returns structured unavailable responses
# ------------------------------------------------------------------

def test_tr_8_2_offline_returns_structured_error():
    provider = DhanDataProvider(client_id=None, access_token=None)

    positions = provider.get_today_positions()
    assert positions["status"] == "unavailable"
    assert positions["data"] == []

    trades = provider.get_today_trades()
    assert trades["status"] == "unavailable"
    assert trades["data"] == []

    funds = provider.get_funds_limits()
    assert funds["status"] == "unavailable"
    assert funds["data"] == {}

    ltp = provider.get_marketfeed_ltp([])
    assert ltp["status"] == "unavailable"
    assert ltp["data"] == {}


# ------------------------------------------------------------------
# TR-8.3  Hot-path import does not crash without Dhan library
# ------------------------------------------------------------------

def test_tr_8_3_hot_path_import_no_error():
    from src.dhan_integration import DhanDataProvider as DP, DhanApiError as DAE

    assert isinstance(DP, type)
    assert issubclass(DAE, Exception)

    provider = DP()
    assert provider.connected is False
