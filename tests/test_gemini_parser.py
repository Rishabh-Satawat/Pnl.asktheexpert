from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.gemini_parser import (
    DependenciesMissingError,
    GeminiScreenshotParser,
    TRADETRON_STRATEGY_CARDS_PROMPT,
    ZERODHA_KITE_POSITIONS_PROMPT,
    ZERODHA_VIRTUAL_CONTRACT_NOTE_PROMPT,
)


def test_tr_7_1_no_key_graceful_error():
    """TR-7.1: parse_image raises DependenciesMissingError when no API key."""
    parser = GeminiScreenshotParser(api_key=None)
    # Clear env var to ensure no key is found
    import os
    old = os.environ.pop("GEMINI_API_KEY", None)
    try:
        parser._api_key = None  # ensure cleared after __init__
        dummy_image = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        with pytest.raises(DependenciesMissingError) as exc_info:
            parser.parse_image(dummy_image)
        error = exc_info.value
        assert "Gemini API key" in error.user_action or "Settings page" in error.user_action
        assert error.user_action  # non-empty
    finally:
        if old is not None:
            os.environ["GEMINI_API_KEY"] = old


def test_tr_7_2_retry_exactly_once():
    """TR-7.2: _parse_with_retry calls callable at most twice (1 retry)."""
    parser = GeminiScreenshotParser(api_key="FAKE_KEY_FOR_TEST")

    call_count = 0

    def mock_callable(extra_instruction=""):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ValueError("Simulated first-call parse failure")
        # Second call returns valid data
        return {
            "screen_type": "TRADETRON_STRATEGY_CARD",
            "broker_identified": "TRADETRON",
            "overall_confidence": 0.9,
            "visible_underlying_levels": {},
            "processing_status": "PARSED",
            "strategy_cards": [],
        }

    result = parser._parse_with_retry(mock_callable, "TRADETRON_STRATEGY_CARD")
    assert call_count == 2, f"Expected exactly 2 calls, got {call_count}"
    assert result["overall_confidence"] == 0.9
    assert result["processing_status"] == "PARSED"


def test_tr_7_3_prompt_templates_exist():
    """TR-7.3: All 3 prompt templates are non-empty and contain key phrases."""
    # TRADETRON prompt
    assert isinstance(TRADETRON_STRATEGY_CARDS_PROMPT, str)
    assert len(TRADETRON_STRATEGY_CARDS_PROMPT) > 50
    assert "strategy_cards" in TRADETRON_STRATEGY_CARDS_PROMPT
    assert "JSON" in TRADETRON_STRATEGY_CARDS_PROMPT

    # ZERODHA_KITE prompt
    assert isinstance(ZERODHA_KITE_POSITIONS_PROMPT, str)
    assert len(ZERODHA_KITE_POSITIONS_PROMPT) > 50
    assert "kite_positions" in ZERODHA_KITE_POSITIONS_PROMPT or "positions" in ZERODHA_KITE_POSITIONS_PROMPT
    assert "JSON" in ZERODHA_KITE_POSITIONS_PROMPT

    # CONTRACT NOTE prompt
    assert isinstance(ZERODHA_VIRTUAL_CONTRACT_NOTE_PROMPT, str)
    assert len(ZERODHA_VIRTUAL_CONTRACT_NOTE_PROMPT) > 50
    assert "contract_note" in ZERODHA_VIRTUAL_CONTRACT_NOTE_PROMPT or "reconciliation_boolean" in ZERODHA_VIRTUAL_CONTRACT_NOTE_PROMPT
    assert "JSON" in ZERODHA_VIRTUAL_CONTRACT_NOTE_PROMPT
