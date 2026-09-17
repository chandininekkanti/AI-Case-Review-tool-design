"""
The "Junior AI Investigator" reasoning layer.

Design principle: the LLM (real or mock) is NEVER asked to invent a risk
score from raw signals. `scoring.py` computes the score and the evidence
list deterministically from the CSV data first. The LLM's job is narrower
and safer: turn that already-computed, already-grounded evidence into a
readable narrative, and answer follow-up questions -- strictly using the
case's own data. This is what keeps the system explainable and resistant to
hallucination even when the underlying model is a full LLM.

Two engines share one interface (`assess_case`, `answer_question`):
  - MockEngine:   template-based narration. Zero cost, deterministic,
                  no API key needed. Used by default in this prototype.
  - ClaudeEngine: real Claude call. Used automatically if ANTHROPIC_API_KEY
                  is set in the environment (see README). Falls back to
                  MockEngine on any API error so the UI never breaks.

Swap points are marked with `# STUB:` where a real key would light this up.
"""
import os
import json
from scoring import score_case, RECOMMENDED_ACTION, confidence_for


# ---------------------------------------------------------------------------
# Shared: build the grounded "evidence packet" every engine works from
# ---------------------------------------------------------------------------
def build_evidence(case: dict) -> dict:
    risk_score, risk_level, indicators = score_case(case)
    confidence = confidence_for(risk_score, indicators)
    return {
        "case_id": case["case_id"],
        "risk_score": risk_score,
        "risk_level": risk_level,
        "confidence": confidence,
        "recommended_action": RECOMMENDED_ACTION[risk_level],
        "indicators": [
            {"signal": i.signal, "value": i.value, "explanation": i.explanation, "weight": i.points}
            for i in indicators
        ],
    }


# ---------------------------------------------------------------------------
# Mock engine (default -- no API key required)
# ---------------------------------------------------------------------------
class MockEngine:
    source = "mock"

    def assess_case(self, case: dict) -> dict:
        evidence = build_evidence(case)
        evidence["summary"] = self._narrate(case, evidence)
        evidence["source"] = self.source
        return evidence

    def _narrate(self, case, evidence):
        top = evidence["indicators"][:3]
        care_type = case["care_type"]
        amount = case["claim_amount_usd"]

        if evidence["risk_level"] == "low":
            if not top:
                return (
                    f"This {care_type} claim (${amount:,}) shows no triggered fraud signals -- "
                    "billing frequency, amounts, and distances all fall within normal ranges. "
                    "This looks like a routine referral, most likely a false positive."
                )
            reasons = "; ".join(i["explanation"] for i in top)
            return (
                f"This {care_type} claim (${amount:,}) has only minor anomalies ({reasons}). "
                "None of them are individually strong enough to warrant escalation."
            )

        if evidence["risk_level"] == "medium":
            reasons = " Also, ".join(i["explanation"] for i in top)
            return (
                f"This {care_type} claim (${amount:,}) has one or two signals worth a second "
                f"look: {reasons} On its own this pattern is inconclusive -- it warrants "
                "documentation review before it's cleared or escalated."
            )

        reasons = " In addition, ".join(i["explanation"] for i in top)
        return (
            f"This {care_type} claim (${amount:,}) shows multiple independent, strong fraud "
            f"indicators: {reasons} Taken together, this combination is unlikely to occur by "
            "chance and warrants a full investigation."
        )

    def answer_question(self, case: dict, evidence: dict, history: list, question: str) -> str:
        q = question.lower()

        # Grounded keyword lookup over the case's own fields -- the mock
        # engine will say "I don't have that" rather than invent an answer.
        field_aliases = {
            "distance": "member_provider_distance_miles",
            "frequency": "weekly_visit_frequency",
            "visit": "weekly_visit_frequency",
            "weekend": "weekend_billing_ratio",
            "amount": "claim_amount_usd",
            "peer": "amount_vs_peer_avg_pct",
            "round": "round_dollar_billing_ratio",
            "prior claim": "prior_claims_last_12mo",
            "shared contact": "shared_contact_with_provider",
            "overlap": "service_overlap_other_provider",
            "duplicate service": "duplicate_service_billed",
            "duplicate claim": "duplicate_claim_number_across_cases",
            "policy change": "recent_policy_change_flag",
            "state": "state",
            "care type": "care_type",
            "date": "claim_date",
        }

        for phrase, field in field_aliases.items():
            if phrase in q:
                return (
                    f"`{field}` for {case['case_id']} is **{case.get(field, 'n/a')}**. "
                    + next((i["explanation"] for i in evidence["indicators"] if i["signal"] == field), "")
                )

        if "why" in q and ("risk" in q or "flag" in q or "score" in q):
            if not evidence["indicators"]:
                return "No fraud signals triggered on this case, which is why it's scored low risk."
            bullets = "\n".join(f"- {i['explanation']}" for i in evidence["indicators"])
            return f"The {evidence['risk_level']} risk score comes from:\n{bullets}"

        if "action" in q or "next step" in q or "recommend" in q:
            return evidence["recommended_action"]

        if "confidence" in q:
            return (
                f"Confidence is **{evidence['confidence']}** "
                f"({len([i for i in evidence['indicators'] if i['weight'] >= 12])} strong, "
                "independent indicator(s) found)."
            )

        return (
            "I can only answer from this case's own record, and I don't see a field that "
            "matches that question. Try asking about a specific signal (distance, visit "
            "frequency, weekend billing, peer amount, shared contact, overlap, duplicates, "
            "policy change), or ask 'why is this flagged' / 'what's the recommended action'."
        )


# ---------------------------------------------------------------------------
# Real Claude engine -- activates automatically if ANTHROPIC_API_KEY is set
# ---------------------------------------------------------------------------
class ClaudeEngine:
    source = "llm"

    SYSTEM_PROMPT = """You are a fraud-triage assistant helping a human investigator \
at a long-term-care insurer. You will be given a JSON "evidence packet" that was \
already computed deterministically from claim data: a risk score, a risk level, and \
a list of specific triggered indicators with their raw values and one-line explanations.

Rules:
- Only use the numbers and indicators given to you. Never invent a signal, value, or \
fact that isn't in the evidence packet or case record.
- If asked something the data can't answer, say so plainly instead of guessing.
- Keep responses concise and written for a busy investigator, not a general audience.
- Do not change the risk_level or recommended_action that were computed for you -- \
you may explain them, not override them.
"""

    def __init__(self):
        # STUB: real usage does `from anthropic import Anthropic; self.client = Anthropic()`
        # which reads ANTHROPIC_API_KEY from the environment automatically.
        from anthropic import Anthropic  # noqa: F401 (imported lazily so mock mode has no dependency)
        self.client = Anthropic()
        self.model = "claude-sonnet-4-6"

    def assess_case(self, case: dict) -> dict:
        evidence = build_evidence(case)
        prompt = (
            "Write a 2-4 sentence narrative summary of this case for an investigator, "
            "based strictly on this evidence packet:\n\n"
            f"{json.dumps({'case': case, 'evidence': evidence}, indent=2)}\n\n"
            "Return ONLY the narrative text, no preamble, no JSON."
        )
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=300,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            evidence["summary"] = "".join(b.text for b in resp.content if b.type == "text").strip()
            evidence["source"] = self.source
        except Exception as e:  # noqa: BLE001 -- never break the UI on an API hiccup
            fallback = MockEngine()
            evidence = fallback.assess_case(case)
            evidence["source"] = f"mock (llm error: {e})"
        return evidence

    def answer_question(self, case: dict, evidence: dict, history: list, question: str) -> str:
        transcript = "\n".join(f"{m['role']}: {m['content']}" for m in history)
        prompt = (
            f"Case record:\n{json.dumps(case, indent=2)}\n\n"
            f"Evidence packet:\n{json.dumps(evidence, indent=2)}\n\n"
            f"Conversation so far:\n{transcript}\n\n"
            f"Investigator's new question: {question}\n\n"
            "Answer using only the case record and evidence packet above."
        )
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=400,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            return "".join(b.text for b in resp.content if b.type == "text").strip()
        except Exception as e:  # noqa: BLE001
            return MockEngine().answer_question(case, evidence, history, question) + \
                f"\n\n_(LLM call failed, showing rule-based answer instead: {e})_"


def get_engine():
    """STUB swap point: set ANTHROPIC_API_KEY in the environment to light up
    real Claude reasoning. With no key (or if the `anthropic` package isn't
    installed), the app runs entirely on the deterministic mock engine."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return ClaudeEngine()
        except Exception:
            pass
    return MockEngine()
