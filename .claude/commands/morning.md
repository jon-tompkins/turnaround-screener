---
description: Analyze today's pending turnaround candidates and update the daily report
---

You are the analyst layer of the turnaround stock screener. The 9am cron has already
run the screener, enriched the new names, and dumped one JSON dossier per ticker to
`data/pending/<TODAY>/`. Your job is to do the deep analysis on each pending dossier
that the deterministic enrichment couldn't do — looking up recent news, checking
filings, sanity-checking the setup — and write a structured analysis back to disk.

## Workflow

1. **Find today's pending dossiers.** List files in `data/pending/`. Pick the most
   recent date directory. If `data/pending/` is empty or the latest date dir is
   empty, tell the user "no pending tickers" and stop.

2. **For each dossier file (`data/pending/<DATE>/<TICKER>.json`):**
   - Read the full dossier — it contains overview, options summary, insider activity,
     `screen_mode` (either "recovering" or "basing"), and `screen_metrics`.
   - Do real research, not just rephrasing the dossier:
     - WebSearch for recent news on the company (last 3 months)
     - WebSearch for the catalyst the dossier hints at (earnings dates, FDA decisions,
       leadership changes, activist filings, etc.)
     - If the dossier mentions a sector trend, check whether it's bullish or bearish
       broadly
     - For biotechs: check whether there's a near-term clinical readout
     - For consumer names: check whether comp sales are turning
   - Form a view. Be honest and skeptical. Most names that pass technical screens
     are NOT good trades. Reserve high conviction scores (8+) for setups with
     multiple catalysts, real businesses, and identifiable asymmetric payoffs.
   - Treat `screen_mode` correctly:
     - **recovering** — turnaround has started, judge whether momentum continues
     - **basing** — bottom may be in but not confirmed, longer horizon, cheaper
       entry but higher risk of re-breakdown

3. **Write the analysis** to `data/analyzed/<SAME_DATE>/<TICKER>.json` matching
   exactly this schema:

   ```json
   {
     "ticker": "STR",
     "company_name": "STR",
     "sector": "STR",
     "industry": "STR",
     "turnaround_reason": "STR — 1-2 sentences on what beat it down and why it might recover",
     "bullish_points": ["STR", "..."],
     "bearish_points": ["STR", "..."],
     "catalyst": "STR — the specific event that could drive the move",
     "catalyst_timing": "STR — when (e.g. 'Q2 2026 earnings', 'FDA decision by July')",
     "options_liquid": true,
     "conviction_score": 5,
     "suggested_trade": "STR — specific: 'Spot only', 'Jan 2027 $15 calls', etc.",
     "key_risk": "STR — the one thing most likely to invalidate the thesis",
     "estimated_upside_pct": 50,
     "estimated_downside_pct": 25,
     "would_skip_if": "STR — conditions that would make you pass"
   }
   ```

4. **Merge.** After all analyses are written, run:
   `.venv/bin/python scripts/merge_analyses.py`
   This updates the watchlist DB and regenerates today's markdown report with
   the full analyses.

5. **Commit and push.** Stage the new files and push:
   ```
   git add data/pending data/analyzed data/reports data/pipeline.db
   git commit -m "Daily analysis for <DATE>"
   git push
   ```

6. **Summarize for the user.** Print a short list: ticker, conviction, suggested
   trade. Flag the 1-2 names you think are most actionable. The user is going to
   look at this and decide what to act on, so be direct.

## Notes

- If a ticker's dossier has very little usable data (e.g. yfinance returned mostly
  None), say so explicitly in `bearish_points` and lower the conviction. Don't
  fabricate detail.
- If the screen says "recovering" but the most-recent news is materially bearish
  (e.g. a fraud lawsuit, key customer loss, executive departure), the screen has
  a stale view — call that out and lower conviction.
- For names you've never heard of, that's normal — the screen surfaces 2nd/3rd-tier
  small caps. Treat unknown names with extra skepticism, not extra optimism.
