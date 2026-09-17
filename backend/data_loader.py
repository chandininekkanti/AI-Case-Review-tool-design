"""
Loads the raw case CSV and enriches it with cross-case signals that can't be
seen by looking at a single row in isolation (e.g. the same claim_number
being submitted under two different case_ids).
"""
import csv
from collections import Counter
from pathlib import Path

NUMERIC_INT_FIELDS = [
    "claim_amount_usd",
    "duplicate_service_billed",
    "weekly_visit_frequency",
    "member_provider_distance_miles",
    "prior_claims_last_12mo",
    "shared_contact_with_provider",
    "amount_vs_peer_avg_pct",
    "recent_policy_change_flag",
    "service_overlap_other_provider",
]
NUMERIC_FLOAT_FIELDS = ["weekend_billing_ratio", "round_dollar_billing_ratio"]


def load_cases(csv_path: str) -> dict:
    """Returns {case_id: case_dict} with cross-case signals attached."""
    path = Path(csv_path)
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    for row in rows:
        for field in NUMERIC_INT_FIELDS:
            row[field] = int(row[field])
        for field in NUMERIC_FLOAT_FIELDS:
            row[field] = float(row[field])

    # Cross-case signal: has this exact claim_number been submitted more than
    # once, under a different case_id? This is a classic duplicate-billing /
    # resubmission pattern that only shows up when you look across the queue.
    claim_number_counts = Counter(row["claim_number"] for row in rows)
    for row in rows:
        row["duplicate_claim_number_across_cases"] = int(
            claim_number_counts[row["claim_number"]] > 1
        )

    return {row["case_id"]: row for row in rows}
