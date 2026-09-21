"""Gemini multimodal screenshot parser — uses google-genai SDK (v1+)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class DependenciesMissingError(RuntimeError):
    """Raised when Gemini API key not configured or SDK missing."""

    def __init__(self, message: str, user_action: str | None = None):
        super().__init__(message)
        self.user_action = user_action or (
            "Gemini API key not configured. Settings page: go to "
            "https://aistudio.google.com/app/apikey, create a new API key "
            "(starts with AIza...), paste it in Streamlit Cloud Secrets as "
            "GEMINI_API_KEY = \"AIza...\". Then reboot the app."
        )


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

UNIVERSAL_EXTRACTION_PROMPT = """You are an expert Indian F&O quant analyst. Carefully analyze this screenshot.

It may be one of these types:
1. Tradetron strategy deployment card — shows strategy name, multiplier (1x/2x), P&L, capital deployed/allocated
2. Zerodha Kite positions table — shows instrument symbols (like NIFTY2692224000CE), qty, avg price, LTP, day P&L columns
3. Zerodha virtual contract note / charges popup — shows brokerage, STT, GST, stamp duty line items

Return EXACTLY this JSON structure. Fill every visible field. Use null for invisible fields. Use [] for empty lists.

{
  "screen_type": "TRADETRON_STRATEGY_CARD|ZERODHA_KITE_POSITIONS|ZERODHA_VIRTUAL_CONTRACT_NOTE|UNKNOWN",
  "broker_identified": "TRADETRON|ZERODHA|null",
  "overall_confidence": 0.9,
  "strategy_cards": [
    {
      "strategy_name": "SENSEX BFO Dynamic Inside-Day Short Strangle",
      "deployment_status": "LIVE_AUTO",
      "multiplier_x": 1,
      "booked_gross_pnl": 4250.00,
      "capital_deployed_allocated": 200000.0,
      "entry_timestamp_ist": "2026-09-21T09:15:00",
      "exit_timestamp_ist": null,
      "legs": []
    }
  ],
  "kite_positions": [
    {
      "vendor_symbol": "BANKNIFTY2692252000PE",
      "product_type": "MIS",
      "quantity": -30,
      "avg_price": 85.50,
      "ltp": 62.00,
      "pnl": 705.00,
      "side": "SELL",
      "exchange": "NSE"
    }
  ],
  "contract_note_charges": {
    "brokerage_amount": 40.00,
    "exchange_turnover_fee_amount": 12.50,
    "securities_transaction_tax_stt": 38.20,
    "sebi_turnover_charges": 0.45,
    "stamp_duty": 8.10,
    "gst": 9.45,
    "total_charges_grand_total": 108.70
  },
  "processing_status": "PARSED"
}

STRICT RULES:
- Extract EVERY visible row from tables — do not skip any
- For Tradetron: strategy_name is the card heading. booked_gross_pnl is the P&L number shown (can be negative)
- For Kite positions: negative quantity = SELL side
- Return ONLY the JSON — no markdown fences (```), no explanation text
"""

TRADETRON_STRATEGY_CARDS_PROMPT = UNIVERSAL_EXTRACTION_PROMPT
ZERODHA_KITE_POSITIONS_PROMPT = UNIVERSAL_EXTRACTION_PROMPT
ZERODHA_VIRTUAL_CONTRACT_NOTE_PROMPT = UNIVERSAL_EXTRACTION_PROMPT

_PROMPT_MAP: Dict[str, str] = {
    "TRADETRON_STRATEGY_CARD": UNIVERSAL_EXTRACTION_PROMPT,
    "ZERODHA_KITE_POSITIONS": UNIVERSAL_EXTRACTION_PROMPT,
    "ZERODHA_VIRTUAL_CONTRACT_NOTE": UNIVERSAL_EXTRACTION_PROMPT,
    "UNKNOWN": UNIVERSAL_EXTRACTION_PROMPT,
}


# ---------------------------------------------------------------------------
# Main parser class
# ---------------------------------------------------------------------------

class GeminiScreenshotParser:
    """Multimodal screenshot parser using google-genai SDK."""

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self._client = None

    def configure(self, api_key: str) -> None:
        self._api_key = api_key
        self._client = None

    def _get_client(self):
        """Lazy-init google.genai client."""
        if not self._api_key:
            raise DependenciesMissingError(
                "Gemini API key is not configured.",
            )
        if self._client is not None:
            return self._client
        try:
            from google import genai  # type: ignore
        except ImportError:
            raise DependenciesMissingError(
                "google-genai package not installed. Run: pip install google-genai"
            )
        self._client = genai.Client(api_key=self._api_key)
        return self._client

    # ------------------------------------------------------------------
    # Image part preparation
    # ------------------------------------------------------------------

    @staticmethod
    def _prepare_image_part(image_bytes: bytes, filename: str = "") -> dict:
        """Detect MIME type from magic bytes and return Part dict."""
        if image_bytes[:3] == b'\xff\xd8\xff':
            mime = "image/jpeg"
        elif image_bytes[:4] == b'\x89PNG':
            mime = "image/png"
        elif image_bytes[:4] == b'%PDF':
            mime = "application/pdf"
        else:
            # Fallback: use filename extension
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            mime = {
                "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "png": "image/png", "pdf": "application/pdf",
            }.get(ext, "image/png")
        return {"mime_type": mime, "data": image_bytes}

    # ------------------------------------------------------------------
    # Classification (heuristic only — no extra Gemini call needed)
    # ------------------------------------------------------------------

    def classify_source_type(
        self,
        image_path_or_bytes: str | bytes | Path,
        hint: str | None = None,
    ) -> str:
        valid = {"TRADETRON_STRATEGY_CARD", "ZERODHA_KITE_POSITIONS",
                 "ZERODHA_VIRTUAL_CONTRACT_NOTE", "UNKNOWN"}
        if hint and hint.upper() in valid:
            return hint.upper()
        if isinstance(image_path_or_bytes, (str, Path)):
            fname = str(image_path_or_bytes).lower()
            if "tradetron" in fname or "strategy" in fname:
                return "TRADETRON_STRATEGY_CARD"
            if "kite" in fname or "position" in fname:
                return "ZERODHA_KITE_POSITIONS"
            if "contract" in fname or "charge" in fname:
                return "ZERODHA_VIRTUAL_CONTRACT_NOTE"
        return "UNKNOWN"

    # ------------------------------------------------------------------
    # Core parse
    # ------------------------------------------------------------------

    def parse_image(
        self,
        image_path_or_bytes: str | bytes | Path,
        hint_source_type: str | None = None,
        filename: str = "",
    ) -> dict:
        """Parse one screenshot. Returns structured dict."""
        # Get bytes
        if isinstance(image_path_or_bytes, bytes):
            img_bytes = image_path_or_bytes
        else:
            with open(image_path_or_bytes, "rb") as f:
                img_bytes = f.read()
            filename = filename or Path(str(image_path_or_bytes)).name

        image_part = self._prepare_image_part(img_bytes, filename)

        def _call(extra: str = "") -> dict:
            from google.genai import types  # type: ignore
            client = self._get_client()
            prompt = UNIVERSAL_EXTRACTION_PROMPT + extra
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    types.Part.from_bytes(
                        data=image_part["data"],
                        mime_type=image_part["mime_type"],
                    ),
                    prompt,
                ],
            )
            text = response.text.strip()
            # Strip any markdown fences
            if text.startswith("```json"):
                text = text[7:]
            elif text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
            return json.loads(text)

        return self._parse_with_retry(_call)

    def _parse_with_retry(self, callable_fn, source_type: str = "UNKNOWN") -> dict:
        last_exc = None
        for attempt in range(2):
            try:
                extra = ""
                if attempt == 1:
                    extra = (
                        "\n\nIMPORTANT: Previous attempt failed JSON parsing. "
                        "Return ONLY raw JSON with no markdown, no prefix text. "
                        "Start your response with { and end with }."
                    )
                result = callable_fn(extra)
                if isinstance(result, dict):
                    return result
            except DependenciesMissingError:
                raise
            except Exception as exc:
                last_exc = exc
        return {
            "screen_type": "UNKNOWN",
            "overall_confidence": 0.0,
            "processing_status": "PARSE_FAILED",
            "strategy_cards": [],
            "kite_positions": [],
            "contract_note_charges": None,
            "_error": str(last_exc),
        }

    # ------------------------------------------------------------------
    # Batch parse (called by Streamlit UI)
    # ------------------------------------------------------------------

    def parse_screenshots(
        self,
        image_bytes_list: List[bytes],
        filenames: List[str] | None = None,
    ) -> Dict[str, Any]:
        """Parse multiple screenshots and merge results."""
        positions: List[dict] = []
        strategy_cards: List[dict] = []
        contract_note: Optional[dict] = None

        for i, img_bytes in enumerate(image_bytes_list):
            fname = (filenames[i] if filenames and i < len(filenames) else "")
            try:
                result = self.parse_image(img_bytes, filename=fname)
            except DependenciesMissingError:
                raise
            except Exception:
                continue

            positions.extend(result.get("kite_positions") or [])
            strategy_cards.extend(result.get("strategy_cards") or [])
            cn = result.get("contract_note_charges")
            if cn and contract_note is None:
                contract_note = cn

        return {
            "positions": positions,
            "strategy_cards": strategy_cards,
            "contract_note": contract_note,
        }

    # ------------------------------------------------------------------
    # Confidence classification
    # ------------------------------------------------------------------

    def classify_rows_by_confidence(
        self,
        parse_result: dict,
        threshold: float = 0.85,
    ) -> Tuple[List[dict], List[dict], List[dict]]:
        ok: List[dict] = []
        flagged: List[dict] = []
        needs_review: List[dict] = []
        rows: List[dict] = []
        for key in ("strategy_cards", "kite_positions", "execution_rows"):
            items = parse_result.get(key)
            if items and isinstance(items, list):
                rows.extend(items)
        overall_conf = parse_result.get("overall_confidence", 0.5)
        for row in rows:
            row_conf = row.get("parsing_confidence", overall_conf)
            if row_conf >= threshold:
                ok.append(row)
            elif row_conf >= 0.5:
                flagged.append(row)
            else:
                needs_review.append(row)
        return (ok, flagged, needs_review)

    # ------------------------------------------------------------------
    # Tesseract fallback
    # ------------------------------------------------------------------

    def fallback_local_ocr_tesseract(self, image_path: str | Path) -> dict:
        try:
            import pytesseract  # type: ignore
            from PIL import Image  # type: ignore
            img = Image.open(str(image_path))
            text = pytesseract.image_to_string(img)
            return {"processing_status": "NEEDS_REVIEW", "overall_confidence": 0.3,
                    "ocr_raw_text": text, "source": "tesseract_local"}
        except ImportError:
            return {"processing_status": "NEEDS_REVIEW", "overall_confidence": 0.3,
                    "ocr_raw_text": "", "source": "tesseract_unavailable"}
        except Exception as exc:
            return {"processing_status": "NEEDS_REVIEW", "overall_confidence": 0.3,
                    "ocr_raw_text": "", "source": "tesseract_error", "error": str(exc)}
