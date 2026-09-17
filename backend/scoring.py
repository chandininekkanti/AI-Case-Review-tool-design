"""
Deterministic signal-scoring engine.

This plays two roles in the system:
  1. It is the MOCK reasoner used when no LLM key is configured, so the
     prototype is fully runnable with zero external dependencies/cost.
  2. Even when a real LLM is wired in (see ai_engine.py), this module is what
     computes the ground-truth risk score and evidence list that gets
     *handed to* the LLM. The LLM is only allowed to narrate and answer
     questions about numbers this module already computed -- it is not
     asked to invent a score from scratch. This is the main lever we use to
     keep the AI grounded and reduce hallucination (see write-up).

Each rule returns (points, human_reason) or None if the signal didn't fire.
Thresholds below are intentionally simple, documented assumptions -- in a
real system these would be learned / peer-group-specific rather than
hardcoded globals (see README "Assumptions").
"""
from dataclasses import dataclass, field


@dataclass
class Indicator:
    signal: str
    value: object
    points: int
    explanation: str


def _rule_duplicate_service(case):
    if case["duplicate_service_billed"] == 1:
        return Indicator(
            "duplicate_service_billed", 1, 18,
            "The same service appears to have been billed more than once on this claim."
        )


def _rule_shared_contact(case):
    if case["shared_contact_with_provider"] == 1:
        return Indicator(
            "shared_contact_with_provider", 1, 18,
            "The member and the provider share contact information -- a common "
            "indicator of a fabricated or collusive provider relationship."
        )


def _rule_service_overlap(case):
    if case["service_overlap_other_provider"] == 1:
        return Indicator(
            "service_overlap_other_provider", 1, 15,
            "Another provider billed for overlapping service dates, suggesting care "
            "may not have been rendered as billed."
        )


def _rule_duplicate_claim_number(case):
    if case.get("duplicate_claim_number_across_cases"):
        return Indicator(
            "duplicate_claim_number_across_cases", case["claim_number"], 20,
            f"Claim number {case['claim_number']} was submitted more than once in the "
            "queue under different case IDs -- possible duplicate/resubmission fraud."
        )


def _rule_weekend_billing(case):
    r = case["weekend_billing_ratio"]
    if r > 0.35:
        return Indicator("weekend_billing_ratio", r, 14,
            f"{r:.0%} of billed visits fall on weekends, well above the typical range.")
    if r > 0.2:
        return Indicator("weekend_billing_ratio", r, 6,
            f"{r:.0%} of billed visits fall on weekends, somewhat above the typical range.")


def _rule_amount_vs_peer(case):
    p = case["amount_vs_peer_avg_pct"]
    if p > 100:
        return Indicator("amount_vs_peer_avg_pct", p, 18,
            f"Billed amount is {p}% above the peer average for this care type.")
    if p > 50:
        return Indicator("amount_vs_peer_avg_pct", p, 12,
            f"Billed amount is {p}% above the peer average for this care type.")
    if p > 25:
        return Indicator("amount_vs_peer_avg_pct", p, 5,
            f"Billed amount is {p}% above the peer average for this care type.")


def _rule_round_dollar(case):
    r = case["round_dollar_billing_ratio"]
    if r > 0.5:
        return Indicator("round_dollar_billing_ratio", r, 10,
            f"{r:.0%} of line items are round-dollar amounts, more consistent with "
            "estimated than itemized billing.")
    if r > 0.3:
        return Indicator("round_dollar_billing_ratio", r, 4,
            f"{r:.0%} of line items are round-dollar amounts, somewhat higher than typical.")


def _rule_distance(case):
    d = case["member_provider_distance_miles"]
    if d > 150:
        return Indicator("member_provider_distance_miles", d, 12,
            f"Member lives {d} miles from the provider, far beyond a plausible "
            "in-home/day-care service radius.")
    if d > 60:
        return Indicator("member_provider_distance_miles", d, 7,
            f"Member lives {d} miles from the provider, beyond the typical local service radius.")
    if d > 30:
        return Indicator("member_provider_distance_miles", d, 3,
            f"Member lives {d} miles from the provider, somewhat beyond the typical radius.")


def _rule_visit_frequency(case):
    v = case["weekly_visit_frequency"]
    if v > 12:
        return Indicator("weekly_visit_frequency", v, 8,
            f"Billed visit frequency of {v}/week is well above the typical 2-5/week range.")
    if v > 8:
        return Indicator("weekly_visit_frequency", v, 4,
            f"Billed visit frequency of {v}/week is above the typical 2-5/week range.")


def _rule_prior_claims(case):
    n = case["prior_claims_last_12mo"]
    if n > 8:
        return Indicator("prior_claims_last_12mo", n, 6,
            f"Member has {n} prior claims in the last 12 months, a notably high volume.")
    if n > 5:
        return Indicator("prior_claims_last_12mo", n, 3,
            f"Member has {n} prior claims in the last 12 months, above typical volume.")


def _rule_policy_change(case):
    if case["recent_policy_change_flag"] == 1:
        return Indicator("recent_policy_change_flag", 1, 6,
            "A recent policy change (e.g. contact/bank details) increases scrutiny "
            "when paired with unusual billing patterns.")


RULES = [
    _rule_duplicate_claim_number,
    _rule_duplicate_service,
    _rule_shared_contact,
    _rule_service_overlap,
    _rule_amount_vs_peer,
    _rule_weekend_billing,
    _rule_round_dollar,
    _rule_distance,
    _rule_visit_frequency,
    _rule_prior_claims,
    _rule_policy_change,
]


def score_case(case: dict):
    """Returns (risk_score:int 0-100, risk_level:str, indicators:list[Indicator] sorted desc)."""
    indicators = [r(case) for r in RULES]
    indicators = [i for i in indicators if i is not None]
    indicators.sort(key=lambda i: i.points, reverse=True)

    raw_score = sum(i.points for i in indicators)
    risk_score = min(100, raw_score)

    strong_indicator_count = sum(1 for i in indicators if i.points >= 12)

    if risk_score >= 55 or strong_indicator_count >= 2:
        risk_level = "high"
    elif risk_score >= 25 or strong_indicator_count == 1:
        risk_level = "medium"
    else:
        risk_level = "low"

    return risk_score, risk_level, indicators


RECOMMENDED_ACTION = {
    "low": "Likely false positive. Clear with a light spot-check; no further action needed.",
    "medium": "Request supporting documentation (visit logs, provider invoices) before "
              "clearing. Spot-check with the member if the pattern persists.",
    "high": "Escalate to the Special Investigations Unit (SIU) for full review; "
            "consider a provider-level audit.",
}


def confidence_for(risk_score: int, indicators) -> str:
    strong = sum(1 for i in indicators if i.points >= 12)
    if strong >= 2 or risk_score <= 10:
        return "high"
    if strong == 1 or risk_score >= 55:
        return "medium"
    return "low"
