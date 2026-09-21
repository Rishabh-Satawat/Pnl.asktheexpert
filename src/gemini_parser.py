"""Gemini multimodal screenshot parser — uses google-genai SDK (v1+)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class GeminiAuthError(RuntimeError):
    """Raised when Gemini API authentication or project enablement fails."""

    def __init__(self, error_code: str, original_error: str, key_format: str | None = None):
        self.error_code = error_code
        self.original_error = original_error
        self.key_format = key_format or "unknown"
        
        # Map error codes to actionable user messages
        if "API_KEY_SERVICE_BLOCKED" in error_code or "API_KEY_SERVICE_BLOCKED" in original_error:
            user_action = (
                "🚨 GEMINI API DISABLED IN PROJECT\n\n"
                "Your Google Cloud project does NOT have the Generative Language API enabled.\n\n"
                "Fix: https://console.cloud.google.com/apis/library/generativelanguage.googleapis.com\n"
                "1. Click that link → select your project → click ENABLE\n"
                "2. Wait 30-60 seconds for changes to propagate\n"
                "3. Refresh this app and try again\n\n"
                "Your API key (AQ.Ab8...) is VALID. The issue is project-level, not the key."
            )
        elif "PERMISSION_DENIED" in error_code or "403" in original_error:
            user_action = (
                "🔑 GEMINI API KEY OR PERMISSIONS ISSUE\n\n"
                "Option 1 - Enable the API (most common fix):\n"
                "https://console.cloud.google.com/apis/library/generativelanguage.googleapis.com\n\n"
                "Option 2 - Create a new API key:\n"
                "https://aistudio.google.com/app/apikey\n"
                "Copy the new key (starts with AQ.Ab8...) → paste in Settings page\n\n"
                "Option 3 - Check key restrictions:\n"
                "Ensure the key is NOT restricted to IP/domain (or unrestricted keys may be blocked after Sept 2026)"
            )
        elif "401" in str(error_code) or "Unauthorized" in original_error or "UNAUTHENTICATED" in original_error:
            user_action = (
                "❌ GEMINI API KEY INVALID\n\n"
                "Your API key is invalid, expired, or incorrectly formatted.\n\n"
                "Fix: Create a new API key at https://aistudio.google.com/app/apikey\n"
                "- Copy the FULL key (starts with AQ.Ab8... or AIza...)\n"
                "- Go to Settings page → paste in GEMINI_API_KEY field\n"
                "- Save and refresh the app"
            )
        else:
            user_action = (
                "⚠️ GEMINI API ERROR\n\n"
                f"Error: {original_error}\n\n"
                "Troubleshooting steps:\n"
                "1. Check API key at: https://aistudio.google.com/app/apikey\n"
                "2. Enable API at: https://console.cloud.google.com/apis/library/generativelanguage.googleapis.com\n"
                "3. Try manual CSV upload as fallback (no Gemini required)"
            )
        
        msg = f"Gemini API Error [{error_code}]: {original_error}"
        super().__init__(msg)
        self.user_action = user_action


class DependenciesMissingError(RuntimeError):
    """Raised when Gemini API key not configured or SDK missing."""

    def __init__(self, message: str, user_action: str | None = None):
        super().__init__(message)
        self.user_action = user_action or (
            "Gemini API key not configured. Settings page: go to "
            "https://aistudio.google.com/app/apikey, create a new API key "
            "(starts with AQ.Ab8...), paste it in Streamlit Cloud Secrets as "
            "GEMINI_API_KEY = \"AQ.Ab8...\". Then reboot the app."
        )


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

UNIVERSAL_EXTRACTION_PROMPT = """You are an expert Indian F&O quant analyst. Carefully analyze this screenshot.

It may be one of these types:
1. Tradetron strategy deployment card — shows strategy name, multiplier (1x/2x), P&L, capital deployed/allocated
2. Tradetron positions modal popup — shows a table with Date, Time, Condition (Entry/Universal Exit), Instrument (OPTIDX_* format), Quantity, Price, Amount columns
3. Zerodha Kite positions table — shows instrument symbols (like NIFTY2692224000CE), qty, avg price, LTP, day P&L columns
4. Zerodha virtual contract note / charges popup — shows brokerage, STT, GST, stamp duty line items

Return EXACTLY this JSON structure. Fill every visible field. Use null for invisible fields. Use [] for empty lists.

{
  "screen_type": "TRADETRON_STRATEGY_CARD|TRADETRON_POSITION_MODAL|ZERODHA_KITE_POSITIONS|ZERODHA_VIRTUAL_CONTRACT_NOTE|UNKNOWN",
  "broker_identified": "TRADETRON|ZERODHA|null",
  "overall_confidence": 0.9,
  "strategy_cards": [
    {
      "strategy_name": "SENSEX BFO Dynamic Inside-Day Short Strangle v1",
      "deployment_status": "LIVE_AUTO",
      "multiplier_x": 2,
      "booked_gross_pnl": 1970.00,
      "card_roi_pct": 0.66,
      "capital_deployed_allocated": 300000.0,
      "broker": "Zerodha",
      "entry_timestamp_ist": "2026-09-21T09:15:00",
      "exit_timestamp_ist": null,
      "legs": []
    }
  ],
  "executions": [
    {
      "vendor_symbol": "OPTIDX_SENSEX_24SEP2026_PE_74300",
      "trade_date": "2026-09-21",
      "execution_time": "09:30:02",
      "condition": "Entry",
      "side": "SELL",
      "quantity": 40,
      "price": 193.75,
      "amount": -7750.0,
      "exchange": "BSE",
      "segment": "SENSEX",
      "parsing_confidence": 0.95
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
      "exchange": "NSE",
      "segment": "BANKNIFTY"
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
- For Tradetron strategy card: strategy_name is the card heading, booked_gross_pnl is the P&L number shown (can be negative), capital is in Lakhs (₹3.00 L = 300000.0)
- For Tradetron position modal: extract ALL rows (Entry AND Universal Exit). condition = "Entry" or "Universal Exit". side: Entry with negative qty = "SELL", Universal Exit with positive qty = "BUY"
- For Kite positions: negative quantity = SELL side
- EXCHANGE & SEGMENT INFERENCE (always apply to executions and kite_positions):
  * Symbol contains "SENSEX" → exchange="BSE", segment="SENSEX"
  * Symbol contains "BANKNIFTY" → exchange="NSE", segment="BANKNIFTY"
  * Symbol contains "FINNIFTY" → exchange="NSE", segment="FINNIFTY"
  * Symbol contains "MIDCPNIFTY" or "MIDCAP" → exchange="NSE", segment="MIDCPNIFTY"
  * Symbol contains "NIFTY" (but NOT BANKNIFTY/FINNIFTY/MIDCPNIFTY) → exchange="NSE", segment="NIFTY"
- For Tradetron position modals: vendor_symbol is the instrument shown (e.g. OPTIDX_SENSEX_24SEP2026_PE_74300). Extract date as YYYY-MM-DD from "21 Sep" → "2026-09-21". Extract time as HH:MM:SS from "09:30:02 AM" → "09:30:02"
- Return ONLY the JSON — no markdown fences (```), no explanation text

FEW-SHOT EXAMPLE for Tradetron position modal:
If the modal shows:
  Date=21 Sep, Time=09:30:02 AM, Condition=Entry, Instrument=OPTIDX_SENSEX_24SEP2026_PE_74300, Quantity=-40, Price=₹193.75, Amount=₹-7750
  Date=21 Sep, Time=10:36:25 AM, Condition=Universal Exit, Instrument=OPTIDX_SENSEX_24SEP2026_PE_74300, Quantity=40, Price=₹218.35, Amount=₹8734

Then executions should be:
  {"vendor_symbol":"OPTIDX_SENSEX_24SEP2026_PE_74300","trade_date":"2026-09-21","execution_time":"09:30:02","condition":"Entry","side":"SELL","quantity":40,"price":193.75,"amount":-7750.0,"exchange":"BSE","segment":"SENSEX"}
  {"vendor_symbol":"OPTIDX_SENSEX_24SEP2026_PE_74300","trade_date":"2026-09-21","execution_time":"10:36:25","condition":"Universal Exit","side":"BUY","quantity":40,"price":218.35,"amount":8734.0,"exchange":"BSE","segment":"SENSEX"}
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

    def _extract_error_code(self, exception: Exception) -> tuple[str, str]:
        """Extract error code and message from API exception."""
        error_str = str(exception)
        
        # Try to parse JSON error response
        if "API_KEY_SERVICE_BLOCKED" in error_str:
            return "API_KEY_SERVICE_BLOCKED", error_str
        if "PERMISSION_DENIED" in error_str or "403" in error_str:
            return "PERMISSION_DENIED", error_str
        if "401" in error_str or "Unauthorized" in error_str or "UNAUTHENTICATED" in error_str:
            return "UNAUTHENTICATED", error_str
        if "400" in error_str or "Invalid" in error_str:
            return "BAD_REQUEST", error_str
        
        return "UNKNOWN_ERROR", error_str

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

    def _parse_via_rest_api(self, image_bytes: bytes, prompt: str) -> dict:
        """Fallback: call Gemini REST API directly without using SDK."""
        try:
            import base64
            import httpx
        except ImportError as e:
            raise DependenciesMissingError(
                f"REST API fallback requires httpx: {e}",
                "Install httpx: pip install httpx"
            )
        
        try:
            url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
            
            # Detect image mime type
            if image_bytes[:3] == b'\xff\xd8\xff':
                mime_type = "image/jpeg"
            elif image_bytes[:4] == b'\x89PNG':
                mime_type = "image/png"
            else:
                mime_type = "image/png"
            
            b64_image = base64.b64encode(image_bytes).decode()
            payload = {
                "contents": [{
                    "parts": [
                        {"inline_data": {"mime_type": mime_type, "data": b64_image}},
                        {"text": prompt}
                    ]
                }]
            }
            
            with httpx.Client(timeout=120.0) as client:
                response = client.post(
                    f"{url}?key={self._api_key}",
                    json=payload,
                )
                
                if response.status_code >= 400:
                    error_body = response.text
                    error_code, error_msg = self._extract_error_code(
                        Exception(f"HTTP {response.status_code}: {error_body}")
                    )
                    raise GeminiAuthError(error_code, error_msg, "AQ.Ab8")
                
                result = response.json()
                text = result["candidates"][0]["content"]["parts"][0]["text"]
                
                # Strip markdown if present
                if text.startswith("```json"):
                    text = text[7:]
                elif text.startswith("```"):
                    text = text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()
                
                return json.loads(text)
        except (httpx.RequestError, httpx.HTTPError) as e:
            raise GeminiAuthError(
                "NETWORK_ERROR",
                f"REST API call failed: {e}",
                "AQ.Ab8"
            )

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
        """Parse one screenshot. Returns structured dict with dual-mode fallback."""
        # Get bytes
        if isinstance(image_path_or_bytes, bytes):
            img_bytes = image_path_or_bytes
        else:
            with open(image_path_or_bytes, "rb") as f:
                img_bytes = f.read()
            filename = filename or Path(str(image_path_or_bytes)).name

        image_part = self._prepare_image_part(img_bytes, filename)
        prompt = UNIVERSAL_EXTRACTION_PROMPT

        # Mode A: Try SDK first (preferred)
        def _call_sdk(extra: str = "") -> dict:
            from google.genai import types  # type: ignore
            try:
                client = self._get_client()
                full_prompt = prompt + extra
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[
                        types.Part.from_bytes(
                            data=image_part["data"],
                            mime_type=image_part["mime_type"],
                        ),
                        full_prompt,
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
            except (GeminiAuthError, DependenciesMissingError):
                raise
            except Exception as e:
                # Convert other exceptions to GeminiAuthError
                error_code, error_msg = self._extract_error_code(e)
                raise GeminiAuthError(error_code, error_msg, "AQ.Ab8")

        try:
            return self._parse_with_retry(_call_sdk)
        except GeminiAuthError as auth_err:
            # Mode B: Fallback to REST API if SDK fails with auth error
            if auth_err.error_code in ("API_KEY_SERVICE_BLOCKED", "PERMISSION_DENIED"):
                try:
                    return self._parse_via_rest_api(img_bytes, prompt)
                except (GeminiAuthError, Exception):
                    # Both failed, re-raise original SDK error with full context
                    raise auth_err
            raise

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
            except GeminiAuthError:
                # Re-raise auth errors immediately — don't retry
                raise
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

    @staticmethod
    def _infer_exchange(symbol: str) -> Tuple[str, str]:
        """Infer (exchange, segment) from symbol string. Used as post-processing fallback."""
        s = symbol.upper()
        if "SENSEX" in s:
            return "BSE", "SENSEX"
        if "BANKNIFTY" in s:
            return "NSE", "BANKNIFTY"
        if "FINNIFTY" in s:
            return "NSE", "FINNIFTY"
        if "MIDCPNIFTY" in s or "MIDCAP" in s:
            return "NSE", "MIDCPNIFTY"
        if "NIFTY" in s:
            return "NSE", "NIFTY"
        return "NSE", "UNKNOWN"

    @staticmethod
    def _apply_exchange_inference(rows: List[dict]) -> List[dict]:
        """Apply _infer_exchange to any row where exchange or segment is missing/None."""
        out = []
        for row in rows:
            r = dict(row)
            sym = r.get("vendor_symbol") or r.get("instrument") or ""
            if not r.get("exchange") or not r.get("segment"):
                exch, seg = GeminiScreenshotParser._infer_exchange(sym)
                if not r.get("exchange"):
                    r["exchange"] = exch
                if not r.get("segment"):
                    r["segment"] = seg
            out.append(r)
        return out

    def parse_screenshots(
        self,
        image_bytes_list: List[bytes],
        filenames: List[str] | None = None,
    ) -> Dict[str, Any]:
        """Parse multiple screenshots and merge results.

        All images are parsed independently and merged:
        - executions[] (Tradetron position modal rows) — appended from all images
        - kite_positions[] (Zerodha Kite rows) — appended from all images
        - strategy_cards[] — appended from all images
        - contract_note — first found wins
        """
        executions: List[dict] = []
        positions: List[dict] = []
        strategy_cards: List[dict] = []
        contract_note: Optional[dict] = None

        for i, img_bytes in enumerate(image_bytes_list):
            fname = (filenames[i] if filenames and i < len(filenames) else "")
            try:
                result = self.parse_image(img_bytes, filename=fname)
            except (DependenciesMissingError, GeminiAuthError):
                raise
            except Exception:
                continue

            # Merge executions (Tradetron position modal)
            raw_execs = result.get("executions") or []
            executions.extend(self._apply_exchange_inference(raw_execs))

            # Merge kite positions (Zerodha)
            raw_kite = result.get("kite_positions") or []
            positions.extend(self._apply_exchange_inference(raw_kite))

            # Merge strategy cards
            strategy_cards.extend(result.get("strategy_cards") or [])

            # Contract note — first found wins
            cn = result.get("contract_note_charges")
            if cn and contract_note is None:
                contract_note = cn

        return {
            "executions": executions,
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
