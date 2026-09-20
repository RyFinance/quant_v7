# Amendment 5: amendment 4's integrity check uses pairs at every strike

Written 2026-09-19, minutes after amendment 4 and before any code for it existed. No
signal–return statistic, portfolio return, Sharpe ratio or ranking of names by later performance had
been computed.

Amendment 4 step 1 restricted the check to pairs with |ln(K/S)| ≤ 0.10, where S is the recorded raw
close. When the recorded underlying is the wrong company (the DD case), its options trade at strikes
around the true price. Those can sit more than 10% from the wrong recorded spot, so a day could have
fewer than 3 qualifying pairs, go unchecked, and keep a contaminated H1 value.

Change: step 1 uses every call/put pair with the same strike and expiry, both traded that day and
7 ≤ DTE ≤ 60, **at any strike**. Put-call parity implies the spot at any strike; the median across
pairs absorbs the early-exercise bias of deep in-the-money American options. Everything else in
amendment 4 is unchanged: ≥ 3 pairs, the 5% threshold, and H1–H3 set missing on flagged name-days.
