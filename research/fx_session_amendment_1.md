# Operational amendment, before fixing-strategy returns are calculated

The initial run rejected the entire fixing strategy because EUR/USD had no
14:00 entry bar on 2016-12-26. No fixing-strategy P&L was calculated. The two
signal-strategy results are already observed and remain failed candidates.

Amend execution consistently for all arms: if a scheduled entry open is absent,
the order cannot fill and that leg stays in cash. This depends only on information
observable at entry. If an entry fills but the scheduled exit is missing, fail the
candidate rather than deleting a position with an unknown result. Log each no-fill
with its timestamp. Do not change dates, directions, costs, thresholds or sizing.

This is an operational correction after a data-quality error, not a pristine
preregistration. Retain the original results and original code hash.
