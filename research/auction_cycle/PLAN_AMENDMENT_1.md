# Auction cycle: amendment 1 (data mapping; before any return was computed)

Written 2026-09-19, after PLAN.md was registered and before any price return, window return or
strategy return was computed. Found while checking the LSE vs fiscaldata auction-date union (dates and
labels only).

1. **Tenor from `security_term`, not `original_security_term`.** In fiscaldata, `original_security_term`
   is the tenor of the reopened CUSIP at first issue (e.g. an old 5-year note reopened as a 2-year in
   2015-05 is labelled "5-Year"). The tenor used is the auction's `security_term`: "2-Year" -> 2,
   "3-Year" -> 3, "5-Year" -> 5, "7-Year" -> 7, "10-Year" / "9-Year 10-Month" / "9-Year 11-Month" -> 10,
   "30-Year" / "29-Year 10-Month" / "29-Year 11-Month" -> 30. 20-year terms stay excluded. Positions
   depend only on auction dates, so this affects labels and the per-tenor event study, not candidates,
   except via item 2.
2. **Drop auctions announced on the auction day.** Two fiscaldata nominal auctions have
   `announcemt_date == auction_date` (2019-06-21 10-year reopening, off-cycle; 2021-12-02, a 20-year,
   already excluded). An auction not on the published schedule and announced the same day cannot be
   traded ahead of; it is dropped (applies to fiscaldata rows with announcement lead < 1 day; all other
   leads are 4-8 calendar days). LSE-calendar rows have no announcement field and are all regular.
3. Nothing else changes (candidates, windows, costs, gates, blend).
