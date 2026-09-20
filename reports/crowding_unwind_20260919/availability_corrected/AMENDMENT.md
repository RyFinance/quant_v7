Availability correction, 2026-09-19

The original completed results are retained in the parent directory. During causal verification, two availability issues were found: the interruption delay could override an even later vendor publication date, and a newly available report's rolling features could use predecessor reports that the conservative interruption rule still classified as unavailable.

The correction takes the maximum of all publication bounds, then a cumulative maximum in report-date order within each contract. Thus a report and its rolling features wait for all predecessor reports. No signal thresholds, universe, costs, weighting, or evaluation periods changed. This is a conservative operational correction after observing the original failed results, not a new independent trial. The corrected results supersede the original results. Publication timestamps remain vendor metadata with conservative buffers, not a certified historical vintage database.
