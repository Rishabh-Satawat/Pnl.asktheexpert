# Private Quant Desk P&L Engine -- Setup & Run Guide

## 1. Prerequisites
- Windows 11 (tested)
- Python 3.11+ (download from python.org)
- Git (optional, for version control)

## 2. Create Virtual Environment
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

## 3. Install Dependencies
```powershell
pip install -r requirements.txt
```

## 4. Install Playwright Chromium Browser
```powershell
playwright install chromium
```
Note: One-time download (~150MB). Required for PDF report generation.

## 5. Optional: Install Tesseract OCR
- Download from UB-Mannheim: https://github.com/UB-Mannheim/tesseract/wiki
- Add to PATH after installation
- Used as absolute last-resort fallback if Gemini API is unavailable

## 6. Database Setup
- SQLite database auto-created at `data/quant_desk.db` on first run
- Market knowledge and broker charge schedules auto-seeded
- No external database server needed

## 7. Configure API Keys
Two options:
**Option A (Recommended):** Use the in-app Settings wizard (Page 3) on first run
**Option B:** Copy `.env.example` to `.env` and fill in:
- `GEMINI_API_KEY` (required for screenshot OCR)
- `DHAN_CLIENT_ID` (optional -- pipeline works without)
- `DHAN_ACCESS_TOKEN` (optional -- pipeline works without)

## 8. Run the Application
```powershell
streamlit run app.py
```
Opens at http://localhost:8501

## 9. Daily Workflow
1. Upload 1-5 post-market screenshots (Tradetron cards, Zerodha positions, contract note)
2. Review extracted data -- verify Capital Deployed and Strategy Names (yellow-flagged low confidence fields)
3. Click Approve -> Generate -> Save to DB + Download PDF/Excel

## 10. Historical Dashboard
- Navigate to Page 2 for cumulative equity curve, calendar heatmap, rolling metrics
- Use date range pills (Today, 7D, 30D, MTD, QTD, YTD, Custom)
- Click calendar squares to drill into daily details

## 11. Further Reading
- [Quant Trading Agent Knowledge Base](file:///C:/Users/Dell/Documents/Master%20Algo%20Trading/Manus%20learning%20Md%20files/KIte%20DHan%20Tradetron/Quant%20Trading%20Agent%20Knowledge%20Base.md)
- [CTO Master Plan -- Kite, Dhan, Tradetron](file:///C:/Users/Dell/Documents/Master%20Algo%20Trading/Manus%20learning%20Md%20files/KIte%20DHan%20Tradetron/CTO%20Master%20Plan%20%E2%80%94%20Kite%20%E2%86%94%20Dhan%20%E2%86%94%20Tradetron.md)
- [DhanHQ v2 Python Integration Guide](file:///C:/Users/Dell/Documents/Master%20Algo%20Trading/Manus%20learning%20Md%20files/Dhan%20API%20Sandox%20webhooks%20doc/DhanHQ%20v2%20Python%20Integration%20%E2%80%94%20AI-Agent%20Master%20Guide.md)
