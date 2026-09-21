# Manual End-to-End Test Checklist

> **Instructions**: Walk through each step sequentially. Mark `[x]` when passed, add failure notes inline.
> **Environment**: Streamlit app running locally via `streamlit run app.py`

---

## A. Smoke Test (Blank Keys + Manual CSV)

1. [ ] Start app with no `.env` file → First-run wizard renders on Settings page
2. [ ] Upload manual CSV template on Daily Processing page → No crash
3. [ ] Approve staged data → Pipeline stages 4-9 complete without Gemini
4. [ ] Download Excel → 5 sheets present, readable in Excel/LibreOffice
5. [ ] Download CSV zip → 3 CSV files present

## B. Gemini Real Screenshot Test

6. [ ] Upload Tradetron strategy card screenshot → Strategy Name extracted correctly
7. [ ] Upload Zerodha Kite positions screenshot → Instrument symbols match
8. [ ] Upload Zerodha Virtual Contract Note → 6-tuple charges extracted
9. [ ] Capital Deployed values match screenshot (INR X.XXL → rupees conversion)
10. [ ] MIS/NRML product types correctly identified

## C. Charges Reconciliation

11. [ ] REALIZED charges from contract note match exactly (green badge)
12. [ ] FORMULA charges compute correctly when contract note missing (amber badge)
13. [ ] REALIZED vs FORMULA divergence shown on Audit page (Page 4)
14. [ ] Brokerage component matches expected value per lot
15. [ ] STT/CTT values align with exchange-published rates

## D. Historical Dashboard Seeding

16. [ ] Seed 30 days of data → Equity curve renders with cumulative line
17. [ ] Calendar heatmap shows green/red squares correctly
18. [ ] Rolling 30-day win rate displays
19. [ ] Best/worst day cards show correct values
20. [ ] Calendar drill-down navigates to Page 1 with date context

## E. Mid-Month Edit Propagation

21. [ ] Edit a mid-month day's net P&L → Rerun historical
22. [ ] Verify cumulative equity shifts downstream (all subsequent days updated)
23. [ ] Strategy-level subtotals recalculate after edit

## F. PDF Report Quality

24. [ ] PDF contains 6 KPI values in header strip
25. [ ] PDF has 3 analytics charts (donut, bars, waterfall)
26. [ ] Strategy cards match Tradetron-like layout (name, multiplier, status pill)
27. [ ] Disclaimer footer is bold and prominent on every page
28. [ ] No text clipping or cut-off cards across page breaks
