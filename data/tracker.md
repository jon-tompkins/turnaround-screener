# Turnaround Screener Tracker

Track record of high-conviction names from the screener. Updated after each weekday run.

Last updated: 2026-06-25

## Active Names

| Ticker | Date Added | Conv | Entry Price | Current Price | Pct Chg | Max Gain | Max DD | Days | Status | Outcome |
|--------|------------|------|-------------|---------------|---------|----------|--------|------|--------|---------|
| **GO** | 2026-06-03 | 6/10 | $8.42 | $9.75 | +15.8% | +15.9% | 0.0% | 22 | active | earnings-pending |
| **FOXF** | 2026-06-03 | 6/10 | $18.00 | $19.21 | +6.7% | +6.7% | -3.3% | 22 | active | earnings-pending |
| **ACHC** | 2026-06-04 | 6/10 | $26.29 | $25.17 | -4.3% | 0.0% | -7.5% | 21 | active | earnings-pending |
| **SPSC** | 2026-06-05 | 7/10 | $57.10 | $54.97 | -3.7% | +1.1% | -3.7% | 20 | active | earnings-pending |
| **NSP** | 2026-06-15 | 6/10 | $35.88 | $36.60 | +2.0% | +5.3% | 0.0% | 10 | active | earnings-pending |
| **CERT** | 2026-06-17 | 5/10 | $6.00 | $6.00 | 0.0% | 0.0% | 0.0% | 8 | active | pending |
| **DV** | 2026-06-24 | 7/10 | $10.64 | $10.35 | -2.7% | 0.0% | -2.7% | 1 | active | earnings-pending |
| **GPK** | 2026-06-24 | 6/10 | $10.53 | $10.35 | -1.7% | 0.0% | -1.7% | 1 | active | earnings-pending |
| **XRAY** | 2026-06-25 | 7/10 | $10.92 | $10.88 | -0.4% | 0.0% | -0.4% | 0 | active | earnings-pending |
| **CNMD** | 2026-06-25 | 4/10 | $35.66 | $35.66 | 0.0% | 0.0% | 0.0% | 0 | active | pending |

## Exited Names

| Ticker | Date Added | Conv | Entry Price | Exit Price | Exit Date | Final Return | Max Gain | Max DD | Days Held | Reason | Outcome |
|--------|------------|------|-------------|------------|-----------|-------------|----------|--------|-----------|--------|---------|
| **CNXC** | 2026-06-05 | 7/10 | $28.56 | $25.08 | 2026-06-22 | -12.2% | 0.0% | -12.2% | 17 | Dropped from screen | thesis-broken — GBL exit, debt concerns, price never recovered |
| **SMPL** | 2026-06-19 | 4/10 | $12.63 | $12.63 | 2026-06-22 | 0.0% | 0.0% | 0.0% | 3 | Dropped from screen | value-trap — revenue -9%, GLP-1 headwind, impairment |

## Summary Stats (as of 2026-06-25)

| Metric | Value |
|--------|-------|
| Total names tracked | 12 |
| Active | 10 |
| Exited | 2 |
| Winners (positive return) | 3 (GO, FOXF, NSP) |
| Losers (negative return) | 5 |
| Flat | 2 (CERT, CNMD) |
| Exited losers | 1 (CNXC -12.2%) |
| Exited flat | 1 (SMPL 0%) |
| Best performer | GO +15.8% |
| Worst performer | CNXC -12.2% (exited) |
| Avg active return | +1.2% |
| Avg all (incl exited) | -0.2% |
| Hit rate (exited only) | 0/2 (0%) |
| Win rate (active >0) | 3/10 (30%) |

## Methodology

- **Date Added**: First date ticker appeared as a "New Name" or entered Top 5 with ≥4/10 conviction
- **Entry Price**: Closing price on the report date
- **Current Price**: From most recent report's Top 5 table
- **Max Gain / Max Drawdown**: Peak/trough price observed across all daily reports since entry vs entry price
- **Status**: `active` = still on screener watchlist; `dropped` = removed from screen
- **Outcome**: `pending` = waiting for catalyst; `earnings-pending` = Q2 earnings date set; `thesis-broken` = dropped with loss; `value-trap` = dropped, thesis didn't play
- Exited names move to the Exited table after dropping off the screener for ≥3 days

## Upcoming Catalyst Calendar

| Date | Ticker | Event | Days Away |
|------|--------|-------|-----------|
| Jul 9 | SMPL (exited) | Q3 FY26 earnings | 14 |
| Jul 28 | GPK | Q2 earnings | 33 |
| Jul 29 | ACHC | Q2 earnings | 34 |
| Jul 30 | NSP | Q2 earnings | 35 |
| Aug 4 | IT (not tracked) | Q2 earnings | 40 |
| Aug 5 | DV | Q2 earnings | 41 |
| Aug 5 | CNMD | Q2 earnings | 41 |
| Aug 6 | SPSC | Q2 earnings | 42 |
| Aug 6 | XRAY | Q2 earnings | 42 |
| Aug 6 | CERT | Q2 earnings | 42 |

## Update Cadence

Update after each weekday screener run (~13:30 UTC):
1. Pull latest report from `data/reports/YYYY-MM-DD.md`
2. Update current prices and pct change for active names
3. Recalculate max gain / max drawdown if new highs/lows
4. Add new high-conviction names (≥4/10)
5. Move names dropped for ≥3 days to Exited table with exit price and reason
6. Recalculate summary stats
7. Update catalyst calendar countdown

---

**Source reports**: `data/reports/YYYY-MM-DD.md` (daily pipeline snapshots) + `data/research/*.md` (deep dives)