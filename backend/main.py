import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # allow `import data_loader` etc.

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from data_loader import load_cases
from ai_engine import get_engine
from store import CaseStore

BASE_DIR = Path(__file__).parent.parent
DATA_CSV = BASE_DIR / "data" / "sample_cases.csv"
STORE_PATH = BASE_DIR / "case_store.json"
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(title="Junior AI Investigator")

CASES = load_cases(str(DATA_CSV))
ENGINE = get_engine()
STORE = CaseStore(str(STORE_PATH))

# Cache assessments in-memory so we don't re-run "reasoning" on every click.
_ASSESSMENT_CACHE: dict[str, dict] = {}


def get_assessment(case_id: str) -> dict:
    if case_id not in _ASSESSMENT_CACHE:
        _ASSESSMENT_CACHE[case_id] = ENGINE.assess_case(CASES[case_id])
    return _ASSESSMENT_CACHE[case_id]


class DecisionBody(BaseModel):
    decision: str  # accepted | rejected


class NoteBody(BaseModel):
    note: str


class ChatBody(BaseModel):
    question: str


@app.get("/api/health")
def health():
    return {"status": "ok", "engine": ENGINE.source, "case_count": len(CASES)}


@app.get("/api/queue")
def get_queue():
    """The 'morning brief': every case with its AI assessment, sorted highest risk first."""
    rows = []
    for case_id, case in CASES.items():
        assessment = get_assessment(case_id)
        action_state = STORE.get(case_id)
        rows.append({
            "case_id": case_id,
            "claim_number": case["claim_number"],
            "claim_date": case["claim_date"],
            "care_type": case["care_type"],
            "claim_amount_usd": case["claim_amount_usd"],
            "state": case["state"],
            "risk_level": assessment["risk_level"],
            "risk_score": assessment["risk_score"],
            "confidence": assessment["confidence"],
            "summary": assessment["summary"],
            "decision": action_state["decision"],
        })
    rows.sort(key=lambda r: r["risk_score"], reverse=True)

    counts = {"low": 0, "medium": 0, "high": 0}
    for r in rows:
        counts[r["risk_level"]] += 1

    return {
        "engine": ENGINE.source,
        "total": len(rows),
        "counts": counts,
        "cases": rows,
    }


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    if case_id not in CASES:
        raise HTTPException(404, "case not found")
    assessment = get_assessment(case_id)
    return {
        "case": CASES[case_id],
        "assessment": assessment,
        "investigator_state": STORE.get(case_id),
    }


@app.post("/api/cases/{case_id}/decision")
def set_decision(case_id: str, body: DecisionBody):
    if case_id not in CASES:
        raise HTTPException(404, "case not found")
    if body.decision not in ("accepted", "rejected", "pending"):
        raise HTTPException(400, "decision must be accepted, rejected, or pending")
    return STORE.set_decision(case_id, body.decision)


@app.post("/api/cases/{case_id}/notes")
def add_note(case_id: str, body: NoteBody):
    if case_id not in CASES:
        raise HTTPException(404, "case not found")
    return STORE.add_note(case_id, body.note)


@app.post("/api/cases/{case_id}/chat")
def chat(case_id: str, body: ChatBody):
    if case_id not in CASES:
        raise HTTPException(404, "case not found")
    assessment = get_assessment(case_id)
    state = STORE.get(case_id)
    answer = ENGINE.answer_question(CASES[case_id], assessment, state["chat_history"], body.question)
    STORE.append_chat(case_id, "investigator", body.question)
    STORE.append_chat(case_id, "assistant", answer)
    return {"answer": answer}


# --- static frontend (must be mounted last so /api/* routes above take priority) ---
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
