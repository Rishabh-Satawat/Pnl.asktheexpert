"""Gemini 1.5 Flash multimodal screenshot parser with 3 specialized prompt templates."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class DependenciesMissingError(RuntimeError):
    """Raised when Gemini API key not configured. Contains user_action field."""

    def __init__(self, message: str, user_action: str | None = None):
        super().__init__(message)
        self.user_action = user_action or (
            "Paste your Gemini API key on Settings page (Page 3) or set "
            "GEMINI_API_KEY in .env file. Alternatively use Manual CSV "
            "template for data entry."
        )


# ---------------------------------------------------------------------------
# Prompt template constants
# ---------------------------------------------------------------------------

TRADETRON_STRATEGY_CARDS_PROMPT = """You are an expert Indian F&O quant analyst. Extract data from the Tradetron strategy card screenshot.

Return a JSON object matching this schema:
{
  "screen_type": "TRADETRON_STRATEGY_CARD",
  "broker_identified": "TRADETRON",
  "overall_confidence": <float 0-1>,
  "visible_underlying_levels": {"NIFTY": <float>, "BANKNIFTY": <float>, ...},
  "strategy_cards": [
    {
      "strategy_name": "<string>",
      "deployment_status": "LIVE_AUTO|EXITED|PARTIAL|OTHER",
      "multiplier_x": <int>,
      "counter_int": <int or null>,
      "booked_gross_pnl": <float>,
      "capital_deployed_allocated": <float>,
      "entry_timestamp_ist": "<ISO timestamp or null>",
      "exit_timestamp_ist": "<ISO timestamp or null>",
      "legs": [
        {
          "vendor_symbol": "<string>",
          "side": "BUY|SELL",
          "lots": <int>,
          "lot_size": <int>,
          "quantity": <int>,
          "execution_price": <float>,
          "ltp": <float>,
          "individual_leg_pnl": <float>,
          "option_type": "CE|PE|FUT"
        }
      ]
    }
  ],
  "processing_status": "PARSED"
}

1-shot example:
{
  "screen_type": "TRADETRON_STRATEGY_CARD",
  "broker_identified": "TRADETRON",
  "overall_confidence": 0.92,
  "visible_underlying_levels": {"NIFTY": 24350.50},
  "strategy_cards": [
    {
      "strategy_name": "Bull Call Spread NIFTY",
      "deployment_status": "LIVE_AUTO",
      "multiplier_x": 1,
      "counter_int": 3,
      "booked_gross_pnl": -1250.00,
      "capital_deployed_allocated": 125000.0,
      "entry_timestamp_ist": null,
      "exit_timestamp_ist": null,
      "legs": [
        {
          "vendor_symbol": "NIFTY24JUN24350CE",
          "side": "BUY",
          "lots": 1,
          "lot_size": 25,
          "quantity": 25,
          "execution_price": 210.5,
          "ltp": 195.0,
          "individual_leg_pnl": -387.50,
          "option_type": "CE"
        }
      ]
    }
  ],
  "processing_status": "PARSED"
}

IMPORTANT: Return only valid JSON, no markdown fences, no extra text.
"""

ZERODHA_KITE_POSITIONS_PROMPT = """You are an expert Indian F&O quant analyst. Extract trade data from the Zerodha Kite positions table screenshot.

Return a JSON object matching this schema:
{
  "screen_type": "ZERODHA_KITE_POSITIONS",
  "broker_identified": "ZERODHA",
  "overall_confidence": <float 0-1>,
  "visible_underlying_levels": {"NIFTY": <float>, "BANKNIFTY": <float>, ...},
  "kite_positions": [
    {
      "vendor_symbol": "<string>",
      "product_type": "MIS|NRML|CNC",
      "quantity": <int>,
      "avg_price": <float>,
      "ltp": <float>,
      "pnl": <float>,
      "side": "BUY|SELL",
      "exchange": "NSE|BSE"
    }
  ],
  "processing_status": "PARSED"
}

Extract ALL rows visible in the positions table. Map column headers to fields.
IMPORTANT: Return only valid JSON, no markdown fences, no extra text.
"""

ZERODHA_VIRTUAL_CONTRACT_NOTE_PROMPT = """You are an expert Indian F&O quant analyst. Extract charge breakdowns from the Zerodha virtual contract note / charges popup screenshot.

Return a JSON object matching this schema:
{
  "screen_type": "ZERODHA_VIRTUAL_CONTRACT_NOTE",
  "broker_identified": "ZERODHA",
  "overall_confidence": <float 0-1>,
  "contract_note_charges": {
    "brokerage_amount": <float>,
    "exchange_turnover_fee_amount": <float>,
    "securities_transaction_tax_stt": <float>,
    "sebi_turnover_charges": <float>,
    "stamp_duty": <float>,
    "gst": <float>,
    "total_charges_grand_total": <float>,
    "reconciliation_boolean": <bool>,
    "diff_rupees": <float>
  },
  "processing_status": "PARSED"
}

The reconciliation_boolean should be true if sum of individual charges matches total within 0.01 INR.
Extract every charge line item visible. Match amounts precisely.
IMPORTANT: Return only valid JSON, no markdown fences, no extra text.
"""


# Map source types to prompt templates
_PROMPT_MAP: Dict[str, str] = {
    "TRADETRON_STRATEGY_CARD": TRADETRON_STRATEGY_CARDS_PROMPT,
    "ZERODHA_KITE_POSITIONS": ZERODHA_KITE_POSITIONS_PROMPT,
    "ZERODHA_VIRTUAL_CONTRACT_NOTE": ZERODHA_VIRTUAL_CONTRACT_NOTE_PROMPT,
}

# Classification prompt used when auto-detecting source type
_CLASSIFY_PROMPT = """Look at this screenshot and classify it as one of:
- TRADETRON_STRATEGY_CARD (Tradetron strategy deployment cards)
- ZERODHA_KITE_POSITIONS (Zerodha Kite positions table)
- ZERODHA_VIRTUAL_CONTRACT_NOTE (Zerodha contract note / charges popup)
- UNKNOWN

Return ONLY the classification label, nothing else."""


class GeminiScreenshotParser:
    """Multimodal screenshot parser using Gemini 1.5 Flash."""

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self._model = None

    def configure(self, api_key: str) -> None:
        """Set or update the Gemini API key."""
        self._api_key = api_key
        self._model = None  # force re-init on next call

    def _get_model(self):
        """Lazy-import google.generativeai, configure, and return the model."""
        if not self._api_key:
            raise DependenciesMissingError(
                "Gemini API key is not configured. Cannot call Vision API.",
                user_action=(
                    "Paste your Gemini API key on Settings page (Page 3) or "
                    "set GEMINI_API_KEY in .env file. Alternatively use Manual "
                    "CSV template for data entry."
                ),
            )
        if self._model is not None:
            return self._model

        try:
            import google.generativeai as genai  # lazy import
        except ImportError:
            raise DependenciesMissingError(
                "google-generativeai package is not installed.",
                user_action=(
                    "Run: pip install google-generativeai  -- then restart. "
                    "Or use Manual CSV template for data entry."
                ),
            )
        genai.configure(api_key=self._api_key)
        self._model = genai.GenerativeModel("gemini-1.5-flash")
        return self._model

    # ------------------------------------------------------------------
    # Source-type classification
    # ------------------------------------------------------------------

    def classify_source_type(
        self,
        image_path_or_bytes: str | bytes | Path,
        hint: str | None = None,
    ) -> str:
        """Return one of the known source-type labels or UNKNOWN.

        If *hint* is provided it is validated and returned directly.
        Otherwise uses heuristics on the image path name, falling back
        to Gemini auto-classification when an API key is available.
        """
        valid_types = {
            "TRADETRON_STRATEGY_CARD",
            "ZERODHA_KITE_POSITIONS",
            "ZERODHA_VIRTUAL_CONTRACT_NOTE",
            "UNKNOWN",
        }
        if hint and hint.upper() in valid_types:
            return hint.upper()

        # Simple filename heuristics when we have a path string
        if isinstance(image_path_or_bytes, (str, Path)):
            fname = str(image_path_or_bytes).lower()
            if "tradetron" in fname or "strategy" in fname:
                return "TRADETRON_STRATEGY_CARD"
            if "kite" in fname or "position" in fname:
                return "ZERODHA_KITE_POSITIONS"
            if "contract" in fname or "charge" in fname:
                return "ZERODHA_VIRTUAL_CONTRACT_NOTE"

        # Attempt Gemini-based classification (best-effort)
        try:
            model = self._get_model()
            image_part = self._prepare_image_part(image_path_or_bytes)
            response = model.generate_content([_CLASSIFY_PROMPT, image_part])
            label = response.text.strip().upper()
            if label in valid_types:
                return label
        except (DependenciesMissingError, Exception):
            pass

        return "UNKNOWN"

    # ------------------------------------------------------------------
    # Main parse entry point
    # ------------------------------------------------------------------

    def parse_image(
        self,
        image_path_or_bytes: str | bytes | Path,
        hint_source_type: str | None = None,
    ) -> dict:
        """Parse a screenshot and return a structured dict.

        Workflow:
        1. Classify source_type
        2. Select prompt template
        3. Call Gemini with image + prompt (JSON response)
        4. Validate via Pydantic; retry ONCE on failure
        5. Return parsed dict
        """
        source_type = self.classify_source_type(image_path_or_bytes, hint=hint_source_type)
        prompt = _PROMPT_MAP.get(source_type, TRADETRON_STRATEGY_CARDS_PROMPT)

        def _call_gemini(extra_instruction: str = "") -> dict:
            model = self._get_model()
            image_part = self._prepare_image_part(image_path_or_bytes)
            full_prompt = prompt + extra_instruction
            response = model.generate_content([full_prompt, image_part])
            text = response.text.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            return json.loads(text)

        return self._parse_with_retry(_call_gemini, source_type)

    def _parse_with_retry(
        self,
        callable_fn,
        source_type: str,
    ) -> dict:
        """Call callable_fn, validate with Pydantic, retry once on failure."""
        from src.models.pydantic_schemas import GeminiParseEnvelope

        for attempt in range(2):
            try:
                extra = ""
                if attempt == 1:
                    extra = (
                        "\n\nPREVIOUS ATTEMPT FAILED VALIDATION. "
                        "Please return strictly valid JSON matching the schema exactly. "
                        "Ensure all required fields are present and correctly typed."
                    )
                raw = callable_fn(extra)
                # Validate through Pydantic
                envelope = GeminiParseEnvelope(**raw)
                return envelope.model_dump()
            except DependenciesMissingError:
                raise
            except Exception:
                if attempt == 1:
                    # Second failure - return safe fallback
                    return {
                        "screen_type": source_type,
                        "overall_confidence": 0.5,
                        "processing_status": "NEEDS_REVIEW",
                        "strategy_cards": [],
                        "kite_positions": [],
                        "contract_note_charges": None,
                        "execution_rows": [],
                        "broker_identified": None,
                        "visible_underlying_levels": {},
                        "visible_margin_hud": None,
                    }
        # Should not reach here, but just in case
        return {}  # pragma: no cover

    # ------------------------------------------------------------------
    # Confidence classification
    # ------------------------------------------------------------------

    def classify_rows_by_confidence(
        self,
        parse_result: dict,
        threshold: float = 0.85,
    ) -> Tuple[List[dict], List[dict], List[dict]]:
        """Split rows into (ok, flagged_yellow, needs_review) by confidence.

        Returns:
            (ok_rows, flagged_yellow_rows, needs_review_rows)
        """
        ok: List[dict] = []
        flagged: List[dict] = []
        needs_review: List[dict] = []

        # Gather all row-like items from the parse result
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
    # Fallback local OCR
    # ------------------------------------------------------------------

    def fallback_local_ocr_tesseract(self, image_path: str | Path) -> dict:
        """Attempt OCR via pytesseract. Returns dict with extracted text."""
        try:
            import pytesseract  # type: ignore
            from PIL import Image  # type: ignore

            img = Image.open(str(image_path))
            text = pytesseract.image_to_string(img)
            return {
                "processing_status": "NEEDS_REVIEW",
                "overall_confidence": 0.3,
                "ocr_raw_text": text,
                "source": "tesseract_local",
            }
        except ImportError:
            return {
                "processing_status": "NEEDS_REVIEW",
                "overall_confidence": 0.3,
                "ocr_raw_text": "",
                "source": "tesseract_unavailable",
                "error": "pytesseract or Pillow not installed",
            }
        except Exception as exc:
            return {
                "processing_status": "NEEDS_REVIEW",
                "overall_confidence": 0.3,
                "ocr_raw_text": "",
                "source": "tesseract_error",
                "error": str(exc),
            }

    # ------------------------------------------------------------------
    # Batch parse entry point (used by Streamlit UI)
    # ------------------------------------------------------------------

    def parse_screenshots(self, image_bytes_list: List[bytes]) -> Dict[str, Any]:
        """Parse a list of screenshot byte payloads and merge results.

        Returns a dict with keys:
            "positions"       – list of dicts (from Zerodha kite_positions)
            "strategy_cards"  – list of dicts (from Tradetron strategy_cards)
            "contract_note"   – dict of charges (from contract note, or None)
        """
        positions: List[dict] = []
        strategy_cards: List[dict] = []
        contract_note: Optional[dict] = None

        for img_bytes in image_bytes_list:
            try:
                result = self.parse_image(img_bytes)
            except DependenciesMissingError:
                raise
            except Exception:
                continue

            kite_pos = result.get("kite_positions") or []
            positions.extend(kite_pos)

            sc = result.get("strategy_cards") or []
            strategy_cards.extend(sc)

            cn = result.get("contract_note_charges")
            if cn and contract_note is None:
                contract_note = cn

        return {
            "positions": positions,
            "strategy_cards": strategy_cards,
            "contract_note": contract_note,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _prepare_image_part(image_path_or_bytes: str | bytes | Path):
        """Convert file path or raw bytes into a format suitable for Gemini."""
        if isinstance(image_path_or_bytes, bytes):
            return {"mime_type": "image/png", "data": image_path_or_bytes}
        path = Path(image_path_or_bytes)
        suffix = path.suffix.lower()
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }.get(suffix, "image/png")
        with open(path, "rb") as f:
            data = f.read()
        return {"mime_type": mime, "data": data}
